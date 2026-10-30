"""추정 부하와 실제 지연이 대응하는지 확인하는 탐색 실험 (공식 파일럿 아님).

generator3로 인스턴스를 메모리에서 만들고 (파일을 쓰지 않음), 부하 수준별로
Greedy와 고정 가중치 CPR을 돌려 지연·효율 지표를 CSV로 남긴다.

사용 예:
    python src/simulation_engine/load_validation.py --sizes small medium --seeds 101-110
    python src/simulation_engine/load_validation.py --sizes large --seeds 101-105 --workers 8
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
for path in (REPO_DIR / "src", REPO_DIR / "data"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd  # noqa: E402

import dataset_generator3 as gen3  # noqa: E402
from policy.cpr.cpr_top_1_policy import CPRTop1Policy  # noqa: E402
from policy.greedy.greedy_policy import GreedyPolicy  # noqa: E402
from simulation_engine.disturbance import Disturbance, DisturbanceConfig  # noqa: E402
from simulation_engine.entities import AGV, Kit, KittingStation, Tote  # noqa: E402
from simulation_engine.load_estimator import remaining_load  # noqa: E402
from simulation_engine.orderManager import OrderManager  # noqa: E402
from simulation_engine.simulator import Simulator  # noqa: E402

DEFAULT_LOADS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
SIM_TIME_LIMIT = 172800
CPR_ALPHA = (0.70, 0.15, 0.15)  # gen3 medium s42 그리드 최선 조합 (이전 인스턴스 기준)


def make_policy(name: str):
    if name == "greedy":
        return GreedyPolicy()
    a1, a2, a3 = CPR_ALPHA
    return CPRTop1Policy(
        alpha_1=a1, alpha_2=a2, alpha_3=a3, w_s1=0.3, w_s2=0.7, g1=0.2, g2=0.3,
        lmb=0.006, p=2.0, margin_sec=1200, epsilon=0.2, beta=0.1,
    )


# 키트 투입 규칙 기본값: 여유 순 (납기 − 예상 작업 시간이 작은 키트 먼저, 같으면 번호 순).
# release_rule="edd" 또는 None이면 예전 방식(납기 순, 같은 납기는 번호 순)이다.
DEFAULT_RELEASE = "slack"


def build_simulator(data: dict, policy, disturbance: Disturbance | None = None,
                    release_rule="default") -> Simulator:
    if release_rule == "default":
        release_rule = DEFAULT_RELEASE
    if isinstance(release_rule, str):
        from simulation_engine.kit_release import make_release_rule

        release_rule = None if release_rule == "edd" else make_release_rule(data, release_rule)
    # 인스턴스에 레이아웃이 없으면(예전 생성기) 공용 레이아웃을 쓴다
    layout = data.get("layout") or gen3.load_json(gen3.LAYOUT_PATH)
    agv_rows = data.get("agvs") or gen3.load_json(gen3.DEFAULT_AGV_TEMPLATE)
    totes = [Tote.from_dict(json.loads(json.dumps(t))) for t in data["totes"]]
    kits = [Kit.from_dict(json.loads(json.dumps(k))) for k in data["kits"]]
    stations = [KittingStation.from_dict(s) for s in layout["kitting_stations"]]
    agvs = [AGV.from_dict(a) for a in agv_rows]
    return Simulator(
        agvs=agvs,
        stations=stations,
        totes=totes,
        order_manager=OrderManager(pending_kits=kits, release_rule=release_rule),
        policy=policy,
        sim_time_limit=SIM_TIME_LIMIT,
        disturbance=disturbance,
    )


def run_metrics(sim: Simulator) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        m = sim.run()
    kits = m.order_manager.get_all_kits()
    done = [k for k in kits if k.completed_time_sec is not None]
    unfinished = len(kits) - len(done)
    lateness = [k.completed_time_sec - k.deadline_time_sec for k in done]
    # 끝나지 않은 키트는 완료 시각을 시뮬레이션 제한 시간으로 본다
    lateness += [SIM_TIME_LIMIT - k.deadline_time_sec for k in kits if k.completed_time_sec is None]
    tardiness = [max(0.0, x) for x in lateness]
    left = [t for t in m.totes if not t.is_empty()]
    return {
        "completed_kits": len(done),
        "unfinished_kits": unfinished,
        "tardy_kits": sum(1 for x in tardiness if x > 1e-6),
        "total_tardiness": sum(tardiness),
        "max_tardiness": max(tardiness) if tardiness else 0.0,
        "min_margin": -max(lateness) if lateness else 0.0,
        "makespan": getattr(m, "makespan", math.nan),
        "dispatch": m.dispatched_count,
        "distance": m.total_agv_move_distance,
        "leftover_totes": len(left),
        "leftover_opened": sum(1 for t in left if t.assigned_history),
        "leftover_untouched": sum(1 for t in left if not t.assigned_history),
    }


def run_task(size: str, seed: int, load: float, policies: list[str], dist_cv: float,
             dist_seed: int) -> list[dict]:
    cfg = replace(gen3.PRESETS[size], target_load=load)
    data = gen3.generate(cfg, seed)
    summary = data["summary"]
    rows = []
    for name in policies:
        disturbance = None
        if dist_cv > 0:
            disturbance = Disturbance(
                DisturbanceConfig(travel_cv=dist_cv, picking_cv=dist_cv, seed=dist_seed)
            )
        sim = build_simulator(data, make_policy(name), disturbance)
        rho0 = remaining_load(sim.world_state, 0.0)["peak"]
        started = time.time()
        row = {
            "size": size,
            "seed": seed,
            "target_load": load,
            "policy": name,
            "dist_cv": dist_cv,
            "dist_seed": dist_seed,
            "est_peak": summary["load"]["peak"],
            "est_agv": summary["load"]["agv"],
            "est_slot": summary["load"]["slot"],
            "est_station": summary["load"]["station"],
            "bottleneck": summary["load"]["bottleneck"],
            "rho0_sim": rho0,
            "n_dispatch_est": summary["load"]["n_dispatch_estimate"],
            "n_totes": summary["n_totes"],
            "n_kits": summary["n_kits"],
            "parts_with_leftover": summary["parts_with_leftover"],
            "deadline_max": summary["deadline_max_sec"],
        }
        row.update(run_metrics(sim))
        row["wall_sec"] = time.time() - started
        rows.append(row)
    return rows


def parse_seeds(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="추정 부하 대 실제 지연 탐색 실험")
    parser.add_argument("--sizes", nargs="+", default=["small", "medium"])
    parser.add_argument("--seeds", default="101-110")
    parser.add_argument("--loads", nargs="+", type=float, default=DEFAULT_LOADS)
    parser.add_argument("--policies", nargs="+", default=["greedy", "cpr"])
    parser.add_argument("--dist-cv", type=float, default=0.0, help="교란 변동계수 (0이면 결정적)")
    parser.add_argument("--dist-seed", type=int, default=1)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--output", default="results/load_validation_results.csv")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    tasks = [
        (size, seed, load, args.policies, args.dist_cv, args.dist_seed)
        for size in args.sizes
        for seed in parse_seeds(args.seeds)
        for load in args.loads
    ]
    print(f"=== {len(tasks)}개 인스턴스 × 정책 {len(args.policies)}개, worker {args.workers}개 ===")
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_task, *task) for task in tasks]
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            rows.extend(result)
            r = result[0]
            print(
                f"[{done}/{len(tasks)}] {r['size']} s{r['seed']} L{r['target_load']:.2f} "
                + " ".join(f"{x['policy']}:tardy={x['tardy_kits']}" for x in result),
                flush=True,
            )
    df = pd.DataFrame(rows).sort_values(["size", "target_load", "seed", "policy"])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"=== 저장: {args.output} ===")
