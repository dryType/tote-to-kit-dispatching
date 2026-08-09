from __future__ import annotations

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
    load_greedy_makespan,
    load_layout,
    run_single_simulation,
)

DEFAULT_ALPHA = (0.45, 0.20, 0.35)
DEFAULT_W = (0.3, 0.7)
DEFAULT_MARGIN_SEC = 1200.0
DEFAULT_GAMMA1 = 0.2
DEFAULT_GAMMA2 = 0.3
DEFAULT_LAMBDA = 0.006
DEFAULT_P = 2.0

# Group C 후보군
EPSILON_CANDIDATES = [0.0, 0.1, 0.2, 0.3, 0.4]
BETA_CANDIDATES = [0.0, 0.05, 0.1, 0.15, 0.2]


def run_epsilon_beta_search(
    alpha: tuple[float, float, float] = DEFAULT_ALPHA,
    w_s: tuple[float, float] = DEFAULT_W,
    max_workers: int | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:

    layout = load_layout()
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()

    alpha_1, alpha_2, alpha_3 = alpha
    w_s1, w_s2 = w_s

    task_args = [
        (
            alpha_1,
            alpha_2,
            alpha_3,
            w_s1,
            w_s2,
            DEFAULT_MARGIN_SEC,
            DEFAULT_GAMMA1,
            DEFAULT_GAMMA2,
            DEFAULT_LAMBDA,
            DEFAULT_P,
            eps,
            beta,
            agv_max_distance,
            greedy_makespan,
        )
        for eps in EPSILON_CANDIDATES
        for beta in BETA_CANDIDATES
    ]

    total_tasks = len(task_args)
    num_cores = max_workers or os.cpu_count() or 4

    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [executor.submit(run_single_simulation, arg) for arg in task_args]

        for completed_count, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            results.append(res)
            if show_progress:
                m_sec = res.get("margin_sec", 0.0)
                print(
                    f"[{completed_count}/{total_tasks}] Margin Sec: {m_sec:.1f}s ({m_sec / 60:.1f}min) "
                    f"-> Obj Value: {res['objective_value']:.4f} | "
                    f"Tardiness Count: {res.get('tardiness count', 0)} | "
                    f"Makespan: {res.get('make_span', 0.0):.1f}s"
                )

    df = pd.DataFrame(results)
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index
    return df


if __name__ == "__main__":
    df = run_epsilon_beta_search()

    output_csv = "cpr_epsilon_beta_search_results.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(
        f"\n=== epsilon and beta 탐색 완료! 결과가 '{output_csv}'에 저장되었습니다. ==="
    )
    print("\n--- Epsilon and Beta Search Results Summary ---")
    cols_to_show = [
        col
        for col in [
            "epsilon",
            "beta",
            "tardiness count",
            "make_span",
            "final_fragmentation_index",
            "total distance",
            "objective_value",
        ]
        if col in df.columns
    ]
    print(df[cols_to_show])
