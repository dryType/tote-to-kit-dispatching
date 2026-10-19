"""ATC형 CPR 변형 비교 그리드 (설계 탐색용, 공식 튜닝 아님).

인스턴스는 generator3로 메모리에서 만들고, 변형 × 파라미터 조합을 돌려 CSV로 남긴다.
--analyze로 결과를 납기 준수 우선 순서(실패 인스턴스 수 → 총 지연 → Greedy 대비 E 비율)로 요약한다.
E = 10 × 디스패치 + 거리 / 1.5 + c_R × 잔량 토트, c_R = 10 + (빈 이동 + 2 × 토트-스테이션) / 1.5 (인스턴스별).
E의 환산 단위와 집계 규칙은 아직 보류 중인 제안이며, 여기서는 탐색용으로만 쓴다.

사용 예:
    python src/simulation_engine/policy_design_grid.py --seeds 201-204 --loads 0.8 0.85 \
        --slack work deadline --delta ceil cont hybrid --denom avoidable full \
        --tote carton --kappa 2 8 32 --c 0 1 --baselines greedy cpr_old --output results/design_stage1.csv
    python src/simulation_engine/policy_design_grid.py --analyze results/design_stage1.csv
"""

from __future__ import annotations

import argparse
import itertools
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
from policy.cpr.atc_cpr_policy import ATCCPRPolicy  # noqa: E402
from simulation_engine.load_validation import build_simulator, make_policy, run_metrics  # noqa: E402

_INSTANCES: dict[tuple, dict] = {}


def instance(size: str, seed: int, load: float) -> dict:
    key = (size, seed, load)
    if key not in _INSTANCES:
        _INSTANCES[key] = gen3.generate(replace(gen3.PRESETS[size], target_load=load), seed)
    return _INSTANCES[key]


def config_label(cfg: dict) -> str:
    if cfg["policy"] == "new_cpr":
        label = f"new|k={cfg.get('kappa', 32):g}|c={cfg.get('c', 1):g}|cx={cfg.get('c_x', 0):g}"
        if cfg.get("holder_rule", "fit") != "fit":
            label += f"|rule={cfg['holder_rule']}"
        if cfg.get("holder_sticky"):
            label += "|sticky"
        if cfg.get("relax_sigma") is not None:
            label += f"|rs={cfg['relax_sigma']:g}"
        if cfg.get("relax_rho") is not None:
            label += f"|rr={cfg['relax_rho']:g}"
        if cfg.get("future_kits") is not None:
            label += f"|fk={cfg['future_kits']}"
        if cfg.get("rho_hi") is not None:
            label += f"|rho={cfg['rho_lo']:g}-{cfg['rho_hi']:g}"
        return label
    if cfg["policy"] == "atc_kit":
        return f"atc_kit|k={cfg['kappa']:g}"
    if cfg["policy"] == "cpr_alpha":
        return f"cpr|a=({cfg['a1']:.2f},{cfg['a2']:.2f},{cfg['a3']:.2f})"
    if cfg["policy"] != "atc":
        return cfg["policy"]
    tote = cfg["tote"] if cfg["c"] else "none"
    label = (
        f"atc|{cfg['slack']}|{cfg['delta']}|{cfg['denom']}|{tote}"
        f"|k={cfg['kappa']:g}|c={cfg['c']:g}|d={cfg['d']:g}"
    )
    if cfg.get("cx"):
        label += f"|cx={cfg['cx']:g}"
        if cfg.get("relax") is not None:
            label += f"|relax={cfg['relax']:g}"
    if cfg.get("gate") is not None:
        label += f"|gate={cfg['gate']:g}"
    return label


def make(cfg: dict):
    if cfg["policy"] == "greedy":
        return make_policy("greedy")
    if cfg["policy"] == "cpr_old":
        return make_policy("cpr")
    if cfg["policy"] == "new_cpr":
        from policy.cpr.new_cpr_policy import NewCPRPolicy

        keys = ("kappa", "c", "c_x", "holder_rule", "holder_sticky", "relax_sigma", "relax_rho",
                "future_kits", "rho_lo", "rho_hi")
        return NewCPRPolicy(**{k: cfg[k] for k in keys if k in cfg})
    if cfg["policy"] == "atc_kit":
        from policy.atc.atc_kit_policy import ATCKitPolicy

        return ATCKitPolicy(kappa=cfg["kappa"])
    if cfg["policy"] in ("cpr_sd", "cpr_alpha"):
        # 기존 CPR: α만 바꾸고 나머지는 고정값 (cpr_sd는 거리 항만 남긴 대조군)
        from policy.cpr.cpr_top_1_policy import CPRTop1Policy

        a1, a2, a3 = (0.0, 0.0, 1.0) if cfg["policy"] == "cpr_sd" else (cfg["a1"], cfg["a2"], cfg["a3"])
        return CPRTop1Policy(alpha_1=a1, alpha_2=a2, alpha_3=a3, w_s1=0.3, w_s2=0.7,
                             g1=0.2, g2=0.3, lmb=0.006, p=2.0, margin_sec=1200,
                             epsilon=0.2, beta=0.1)
    return ATCCPRPolicy(
        kappa=cfg["kappa"], c=cfg["c"], d=cfg["d"], slack_mode=cfg["slack"],
        delta_mode=cfg["delta"], denom_mode=cfg["denom"], tote_mode=cfg["tote"],
        c_excess=cfg.get("cx", 0.0), gate=cfg.get("gate"), excess_relax=cfg.get("relax"),
    )


def run_chunk(size: str, seed: int, load: float, configs: list[dict]) -> list[dict]:
    data = instance(size, seed, load)
    summary = data["summary"]["load"]
    c_r = 10 + (summary["mean_empty_travel_m"] + 2 * summary["mean_tote_station_m"]) / 1.5
    rows = []
    for cfg in configs:
        started = time.time()
        m = run_metrics(build_simulator(data, make(cfg)))
        row = {"size": size, "seed": seed, "load": load, "label": config_label(cfg), **cfg}
        row.update(m)
        row["E"] = 10 * m["dispatch"] + m["distance"] / 1.5 + c_r * m["leftover_totes"]
        row["c_R"] = c_r
        row["wall_sec"] = time.time() - started
        rows.append(row)
    return rows


def build_configs(args) -> list[dict]:
    configs: list[dict] = []
    configs += [{"policy": name} for name in args.baselines]
    if args.no_atc:
        return configs
    seen = set()
    gates = [None if g < 0 else g for g in args.gate]
    relaxes = [None if r < 0 else r for r in args.relax]
    for slack, delta, denom, tote, kappa, c, d, cx, gate, relax in itertools.product(
        args.slack, args.delta, args.denom, args.tote, args.kappa, args.c, args.d,
        args.cx, gates, relaxes,
    ):
        if not cx and relax is not None:
            continue
        cfg = {"policy": "atc", "slack": slack, "delta": delta, "denom": denom,
               "tote": tote if c else "none", "kappa": kappa, "c": c, "d": d,
               "cx": cx, "gate": gate, "relax": relax}
        label = config_label(cfg)
        if label not in seen:
            seen.add(label)
            configs.append(cfg)
    return configs


def analyze(paths: list[str], top: int = 25) -> None:
    df = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    df["fail"] = df["tardy_kits"] > 0
    ref = df[df["label"] == "greedy"].set_index(["size", "seed", "load"])["E"]
    df["E_ratio"] = df.apply(lambda r: r["E"] / ref.get((r["size"], r["seed"], r["load"]), float("nan")), axis=1)
    g = df.groupby("label").agg(
        n=("seed", "count"),
        fail=("fail", "sum"),
        T_sum=("total_tardiness", "sum"),
        E_ratio=("E_ratio", "mean"),
        N=("dispatch", "mean"),
        D=("distance", "mean"),
        R=("leftover_totes", "mean"),
        margin=("min_margin", "median"),
        wall=("wall_sec", "mean"),
    )
    g = g.sort_values(["fail", "T_sum", "E_ratio"])
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 70)
    print(f"인스턴스 {df.groupby(['size', 'seed', 'load']).ngroups}개, 설정 {len(g)}개")
    print(g.head(top).round(3).to_string())
    print("\n기준 정책:")
    print(g.loc[[i for i in ("greedy", "cpr_old", "cpr_sd") if i in g.index]].round(3).to_string())


def parse_range(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",")]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ATC형 CPR 변형 비교 그리드")
    p.add_argument("--analyze", nargs="+", help="결과 CSV 요약만 출력")
    p.add_argument("--sizes", nargs="+", default=["medium"])
    p.add_argument("--seeds", default="201-204")
    p.add_argument("--loads", nargs="+", type=float, default=[0.8, 0.85])
    p.add_argument("--slack", nargs="+", default=["work"])
    p.add_argument("--delta", nargs="+", default=["hybrid"])
    p.add_argument("--denom", nargs="+", default=["avoidable"])
    p.add_argument("--tote", nargs="+", default=["carton"])
    p.add_argument("--kappa", nargs="+", type=float, default=[8.0])
    p.add_argument("--c", nargs="+", type=float, default=[1.0])
    p.add_argument("--d", nargs="+", type=float, default=[1.0])
    p.add_argument("--cx", nargs="+", type=float, default=[0.0], help="초과분 보관 토트 벌점 (0이면 끔)")
    p.add_argument("--gate", nargs="+", type=float, default=[-1.0], help="관문형 긴급도 임계값 (음수면 끔)")
    p.add_argument("--relax", nargs="+", type=float, default=[-1.0],
                   help="이 여유(σ_work) 이하인 키트는 보관 토트 벌점 면제 (음수면 끔)")
    p.add_argument("--baselines", nargs="*", default=[], choices=["greedy", "cpr_old", "cpr_sd"],
                   help="함께 돌릴 기준 정책")
    p.add_argument("--no-atc", action="store_true", help="ATC 설정 없이 기준 정책만")
    p.add_argument("--chunk", type=int, default=12, help="작업 하나에 묶을 설정 수")
    p.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 4))
    p.add_argument("--output", default="results/design_grid.csv")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.analyze:
        analyze(args.analyze)
        sys.exit(0)

    configs = build_configs(args)
    instances = [(s, seed, load) for s in args.sizes for seed in parse_range(args.seeds)
                 for load in args.loads]
    tasks = [
        (size, seed, load, configs[i:i + args.chunk])
        for size, seed, load in instances
        for i in range(0, len(configs), args.chunk)
    ]
    total_runs = len(configs) * len(instances)
    print(f"=== 설정 {len(configs)}개 × 인스턴스 {len(instances)}개 = {total_runs}회, "
          f"작업 {len(tasks)}개, worker {args.workers}개 ===", flush=True)

    rows: list[dict] = []
    started = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(run_chunk, *t) for t in tasks]
        for done, fut in enumerate(as_completed(futures), start=1):
            rows.extend(fut.result())
            if done % max(1, len(tasks) // 10) == 0 or done == len(tasks):
                print(f"[{done}/{len(tasks)}] {time.time() - started:.0f}s", flush=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"=== 저장: {args.output} ({time.time() - started:.0f}s) ===")
    analyze([args.output])
