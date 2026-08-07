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
from simulation_engine.scenario_runner_cpr_configs import ALPHA_COMBINATIONS


def generate_w_grid(step: float = 0.1) -> list[tuple[float, float]]:
    grid = []
    steps = round(1.0 / step) + 1
    for i in range(steps):
        w_s1 = round(i * step, 4)
        w_s2 = round(1.0 - w_s1, 4)
        grid.append((w_s1, w_s2))
    return grid


def run_w_grid_search(
    alpha_combinations: list[tuple[float, float, float]] | None = None,
    step: float = 0.1,
    max_workers: int | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    alpha_combinations = alpha_combinations or ALPHA_COMBINATIONS
    w_combinations = generate_w_grid(step=step)
    if not alpha_combinations or not w_combinations:
        return pd.DataFrame()

    layout = load_layout()
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()

    task_args = [
        (alpha_1, alpha_2, alpha_3, w_s1, w_s2, agv_max_distance, greedy_makespan)
        for alpha_1, alpha_2, alpha_3 in alpha_combinations
        for w_s1, w_s2 in w_combinations
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
                print(
                    f"[{completed_count}/{total_tasks}] Alpha: ({res['alpha_1']:.2f}, {res['alpha_2']:.2f}, {res['alpha_3']:.2f}) | W: ({res['w_s1']:.1f}, {res['w_s2']:.1f}) -> Obj Value: {res['objective_value']:.4f}"
                )

    df = pd.DataFrame(results)
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index
    return df


if __name__ == "__main__":
    df = run_w_grid_search(step=0.1)

    output_csv = "cpr_wscore_search_results.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n=== 모든 시뮬레이션 완료! 결과가 '{output_csv}'에 저장되었습니다. ===")
    print("\n--- Top 5 Best Combinations ---")
    print(
        df.head(5)[
            [
                "alpha_1",
                "alpha_2",
                "alpha_3",
                "w_s1",
                "w_s2",
                "tardiness_index",
                "final_fragmentation_index",
                "distance_index",
                "objective_value",
            ]
        ]
    )
