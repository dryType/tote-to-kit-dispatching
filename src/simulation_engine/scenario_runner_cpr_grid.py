"""임의 시나리오에 대해 CPR α 그리드 탐색을 수행한다.

사용 예 (시나리오는 data/dataset_generator3.py로 먼저 생성):
    python data/dataset_generator3.py --preset medium --seed 42 --load 0.8
    python src/simulation_engine/scenario_runner_cpr_grid.py gen3_medium_s42_L080
    python src/simulation_engine/scenario_runner_cpr_grid.py gen3_small_s42_L080 --step 0.1 --workers 4
"""

import argparse
import contextlib
import io
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from simulation_engine.scenario_runner_cpr_common import (
    generate_alpha_grid,
    load_layout,
    run_greedy_baseline,
    run_single_simulation_all_params,
)

W_S1, W_S2 = 0.3, 0.7
MARGIN_SEC = 1200
G1, G2 = 0.2, 0.3
LMB, P = 0.006, 2.0
EPS, BETA = 0.2, 0.1


def run_quiet(args: tuple) -> dict:
    with contextlib.redirect_stdout(io.StringIO()):
        return run_single_simulation_all_params(*args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CPR α 그리드 탐색")
    parser.add_argument("scenario", help="시나리오 이름 (scenario_ 접두어 제외)")
    parser.add_argument("--step", type=float, default=0.05, help="α 격자 간격")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--output", help="결과 CSV 경로 (기본: results/alpha_search_results_<scenario>.csv)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    agv_max_distance = load_layout()["agv_max_distance"]
    greedy_makespan = run_greedy_baseline(args.scenario)

    alpha_combinations = generate_alpha_grid(step=args.step)
    task_args = [
        (
            args.scenario,
            a1,
            a2,
            a3,
            W_S1,
            W_S2,
            MARGIN_SEC,
            G1,
            G2,
            LMB,
            P,
            EPS,
            BETA,
            agv_max_distance,
            greedy_makespan,
        )
        for a1, a2, a3 in alpha_combinations
    ]
    total = len(task_args)
    print(f"=== {args.scenario}: {total}개 α 조합, worker {args.workers}개 ===")

    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_quiet, arg) for arg in task_args]
        for done, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            results.append(res)
            print(
                f"[{done}/{total}] α=({res['alpha_1']:.2f}, {res['alpha_2']:.2f}, {res['alpha_3']:.2f}) "
                f"obj={res['objective_value']:.4f} obj_v2={res['objective_v2']:.4f} "
                f"tardy={res['tardiness count']} left={res['opened_left_totes']} "
                f"revisit={res['revisit_ratio']:.3f}",
                flush=True,
            )

    df = pd.DataFrame(results)
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index

    output_csv = args.output or f"results/alpha_search_results_{args.scenario}.csv"
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\n=== 완료: '{output_csv}' 저장 ===")
