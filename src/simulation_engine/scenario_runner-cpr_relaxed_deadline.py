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
    run_single_simulation_all_params,
)

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


if __name__ == "__main__":
    layout = load_layout()
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()
    w_s1 = 0.3
    w_s2 = 0.7
    margin_sec = 1200
    g1 = 0.2
    g2 = 0.3
    lmb = 0.006
    p = 2.0
    eps = 0.2
    beta = 0.1
    scenario_name = "relaxed_deadline"

    alpha_combinations = generate_alpha_grid(step=0.05)
    total_tasks = len(alpha_combinations)

    num_cores = 6
    print(
        f"=== CPU 코어 수: {num_cores}개 | 총 {total_tasks}개 알파 조합 병렬 시뮬레이션 시작 ==="
    )

    task_args = [
        (
            scenario_name,
            a1,
            a2,
            a3,
            w_s1,
            w_s2,
            margin_sec,
            g1,
            g2,
            lmb,
            p,
            eps,
            beta,
            agv_max_distance,
            greedy_makespan,
        )
        for a1, a2, a3 in alpha_combinations
    ]

    results = []

    # 멀티프로세서 풀 가동
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [
            executor.submit(run_single_simulation_all_params, *arg) for arg in task_args
        ]

        for completed_count, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            results.append(res)
            print(
                f"[{completed_count}/{total_tasks}] Alpha: ({res['alpha_1']:.2f}, {res['alpha_2']:.2f}, {res['alpha_3']:.2f}) | W: ({res['w_s1']:.1f}, {res['w_s2']:.1f}) -> Obj Value: {res['objective_value']:.4f}"
            )

    # DataFrame 생성 및 목적함수 우수(오름차순) 순 정렬
    df = pd.DataFrame(results)
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index  # 정렬 후 순위 인덱스 부여

    # CSV 저장
    output_csv = f"alpha_search_results_{scenario_name}.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n=== 모든 시뮬레이션 완료! 결과가 '{output_csv}'에 저장되었습니다. ===")
    print("\n--- Top 5 Best Combinations ---")
    print(
        df.head(5)[
            [
                "alpha_1",
                "alpha_2",
                "alpha_3",
                "tardiness_index",
                "final_fragmentation_index",
                "distance_index",
                "objective_value",
            ]
        ]
    )
