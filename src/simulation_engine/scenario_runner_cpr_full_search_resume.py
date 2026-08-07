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
    generate_alpha_grid,
    load_greedy_makespan,
    load_layout,
    run_single_simulation,
)

CHECKPOINT_CSV = Path(__file__).resolve().parent / "cpr_full_search_checkpoint.csv"
FINAL_CSV = Path(__file__).resolve().parent / "cpr_full_search_results.csv"


def generate_w_grid(step: float = 0.1) -> list[tuple[float, float]]:
    grid = []
    steps = round(1.0 / step) + 1
    for i in range(steps):
        w_s1 = round(i * step, 4)
        w_s2 = round(1.0 - w_s1, 4)
        grid.append((w_s1, w_s2))
    return grid


def build_task_args(
    alpha_combinations: list[tuple[float, float, float]],
    w_combinations: list[tuple[float, float]],
    agv_max_distance: float,
    greedy_makespan: float,
) -> list[tuple[float, float, float, float, float, float, float]]:
    return [
        (alpha_1, alpha_2, alpha_3, w_s1, w_s2, agv_max_distance, greedy_makespan)
        for alpha_1, alpha_2, alpha_3 in alpha_combinations
        for w_s1, w_s2 in w_combinations
    ]


def make_key(row: dict | pd.Series) -> tuple[float, float, float, float, float]:
    return (
        round(float(row["alpha_1"]), 4),
        round(float(row["alpha_2"]), 4),
        round(float(row["alpha_3"]), 4),
        round(float(row["w_s1"]), 4),
        round(float(row["w_s2"]), 4),
    )


def load_checkpoint() -> pd.DataFrame:
    if not CHECKPOINT_CSV.exists():
        return pd.DataFrame()

    df = pd.read_csv(CHECKPOINT_CSV)
    if df.empty:
        return df

    df = df.drop_duplicates(subset=["alpha_1", "alpha_2", "alpha_3", "w_s1", "w_s2"])
    return df


def append_checkpoint(result: dict) -> None:
    df = pd.DataFrame([result])
    write_header = not CHECKPOINT_CSV.exists()
    df.to_csv(
        CHECKPOINT_CSV,
        mode="a",
        header=write_header,
        index=False,
        encoding="utf-8-sig",
    )


def run_full_search(
    alpha_step: float = 0.05,
    w_step: float = 0.1,
    max_workers: int | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    layout = load_layout()
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()

    alpha_combinations = generate_alpha_grid(step=alpha_step)
    w_combinations = generate_w_grid(step=w_step)
    task_args = build_task_args(
        alpha_combinations=alpha_combinations,
        w_combinations=w_combinations,
        agv_max_distance=agv_max_distance,
        greedy_makespan=greedy_makespan,
    )

    checkpoint_df = load_checkpoint()
    done_keys = set()
    if not checkpoint_df.empty:
        for _, row in checkpoint_df.iterrows():
            done_keys.add(make_key(row))

    pending_task_args = []
    for arg in task_args:
        key = tuple(round(float(value), 4) for value in arg[:5])
        if key not in done_keys:
            pending_task_args.append(arg)

    total_tasks = len(task_args)
    pending_tasks = len(pending_task_args)
    completed_tasks = total_tasks - pending_tasks
    num_cores = max_workers or os.cpu_count() or 4

    if show_progress:
        print(
            f"=== full search start | total={total_tasks} | done={completed_tasks} | pending={pending_tasks} | cpu={num_cores} ==="
        )

    results: list[dict] = []
    if pending_task_args:
        with ProcessPoolExecutor(max_workers=num_cores) as executor:
            futures = [
                executor.submit(run_single_simulation, arg) for arg in pending_task_args
            ]

            for completed_count, future in enumerate(as_completed(futures), start=1):
                res = future.result()
                results.append(res)
                append_checkpoint(res)

                if show_progress:
                    global_completed = completed_tasks + completed_count
                    print(
                        f"[{global_completed}/{total_tasks}] Alpha: ({res['alpha_1']:.2f}, {res['alpha_2']:.2f}, {res['alpha_3']:.2f}) | W: ({res['w_s1']:.1f}, {res['w_s2']:.1f}) -> Obj Value: {res['objective_value']:.4f}"
                    )

    combined_df = pd.concat([checkpoint_df, pd.DataFrame(results)], ignore_index=True)
    if not combined_df.empty:
        combined_df = combined_df.drop_duplicates(
            subset=["alpha_1", "alpha_2", "alpha_3", "w_s1", "w_s2"], keep="first"
        )
        combined_df = combined_df.sort_values(
            by="objective_value", ascending=True
        ).reset_index(drop=True)
        combined_df["index"] = combined_df.index

    return combined_df


if __name__ == "__main__":
    df = run_full_search(alpha_step=0.05, w_step=0.1)

    if not df.empty:
        df.to_csv(FINAL_CSV, index=False, encoding="utf-8-sig")

        print(
            f"\n=== 모든 시뮬레이션 완료! 결과가 '{FINAL_CSV.name}'에 저장되었습니다. ==="
        )
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
    else:
        print("No results were generated.")
