import sys
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

if __name__ == "__main__":
    layout = load_layout()
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()

    alpha_1, alpha_2, alpha_3 = 0.65, 0.15, 0.20
    w_s1, w_s2 = 0.3, 0.7

    result = run_single_simulation(
        (alpha_1, alpha_2, alpha_3, w_s1, w_s2, agv_max_distance, greedy_makespan)
    )

    # DataFrame 생성 및 목적함수 우수(오름차순) 순 정렬
    df = pd.DataFrame(result, index=[0])
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index  # 정렬 후 순위 인덱스 부여

    # CSV 저장
    output_csv = "cpr_fixed_result.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n=== 모든 시뮬레이션 완료! 결과가 '{output_csv}'에 저장되었습니다. ===")
    print(result)
