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

# 1. 테스트할 margin_sec 범위 정의 (초 단위)
# 0초, 300초(5분), 600초(10분), 900초(15분), 1200초(20분 - 기존 디폴트),
# 1500초(25분), 1800초(30분), 2400초(40분), 3000초(50분), 3600초(60분)
MARGIN_SEC_CANDIDATES = [
    0.0,
    300.0,
    600.0,
    900.0,
    1200.0,
    1500.0,
    1800.0,
    2400.0,
    3000.0,
    3600.0,
]

# 2. 앞서 최적화 탐색으로 확보한 Alpha 및 W 가중치 고정값
DEFAULT_ALPHA = (0.45, 0.20, 0.35)
DEFAULT_W = (0.3, 0.7)


def run_margin_sec_search(
    margin_candidates: list[float] | None = None,
    alpha: tuple[float, float, float] = DEFAULT_ALPHA,
    w_s: tuple[float, float] = DEFAULT_W,
    max_workers: int | None = None,
    show_progress: bool = True,
) -> pd.DataFrame:
    margin_candidates = margin_candidates or MARGIN_SEC_CANDIDATES
    if not margin_candidates:
        return pd.DataFrame()

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
            margin_sec,
            agv_max_distance,
            greedy_makespan,
        )
        for margin_sec in margin_candidates
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
    df = run_margin_sec_search()

    output_csv = "cpr_margin_sec_search_results.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n=== margin_sec 탐색 완료! 결과가 '{output_csv}'에 저장되었습니다. ===")
    print("\n--- Margin Sec Search Results Summary ---")
    cols_to_show = [
        col
        for col in [
            "margin_sec",
            "tardiness count",
            "make_span",
            "final_fragmentation_index",
            "total distance",
            "objective_value",
        ]
        if col in df.columns
    ]
    print(df[cols_to_show])
