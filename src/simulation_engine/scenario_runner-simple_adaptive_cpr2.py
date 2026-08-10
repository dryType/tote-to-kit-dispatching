from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from policy.cpr.simple_adaptive_cpr_top_1_policy import SimpleAdaptiveCPRTop1Policy
from simulation_engine.dataset_loader import load_entities_from_scenario
from simulation_engine.orderManager import OrderManager
from simulation_engine.scenario_runner_cpr_common import load_greedy_makespan
from simulation_engine.simulator import Simulator


def run_single_adaptive_simulation(args: tuple) -> dict:
    """단일 Adaptive CPR 시뮬레이션 수행 함수 (ProcessPoolExecutor용)"""
    (
        phase1_alpha,
        phase2_alpha,
        phase3_alpha,
        scenario_name,
        sim_time_limit,
        agv_max_distance,
        greedy_makespan,
    ) = args

    # 1. Policy 및 시뮬레이션 객체 생성
    policy = SimpleAdaptiveCPRTop1Policy(
        phase1_alpha=phase1_alpha,
        phase2_alpha=phase2_alpha,
        phase3_alpha=phase3_alpha,
    )

    totes, kits, stations, agvs = load_entities_from_scenario(scenario_name)
    order_manager = OrderManager(pending_kits=kits)

    simulator = Simulator(
        agvs=agvs,
        stations=stations,
        totes=totes,
        order_manager=order_manager,
        policy=policy,
        sim_time_limit=sim_time_limit,
    )

    # 2. 시뮬레이션 실행
    metrics = simulator.run()

    # 3. 지표 계산
    tardiness_index = metrics.calc_tardiness_index()
    init_frag_index = metrics.initial_frag_index
    frag_index = metrics.calc_fragmentation_index()
    distance_index = metrics.calc_distance_index(agv_max_distance)
    makespan_index = metrics.calc_makespan_index(greedy_makespan)

    # 목적함수 산출
    objective_value = (
        0.55 * tardiness_index
        + 0.05 * makespan_index
        + 0.3 * frag_index
        + 0.1 * distance_index
    )

    frag_reduction_rate = (
        round((init_frag_index - frag_index) / init_frag_index * 100, 2)
        if init_frag_index > 0
        else 0.0
    )

    return {
        # Phase별 가중치 정보 (CSV 확인용)
        "p1_a1": phase1_alpha["alpha_1"],
        "p1_a2": phase1_alpha["alpha_2"],
        "p1_a3": phase1_alpha["alpha_3"],
        "p2_a1": phase2_alpha["alpha_1"],
        "p2_a2": phase2_alpha["alpha_2"],
        "p2_a3": phase2_alpha["alpha_3"],
        "p3_a1": phase3_alpha["alpha_1"],
        "p3_a2": phase3_alpha["alpha_2"],
        "p3_a3": phase3_alpha["alpha_3"],
        # 평가 지표
        "tardiness_index": tardiness_index,
        "makespan_index": makespan_index,
        "initial_fragmentation_index": init_frag_index,
        "final_fragmentation_index": frag_index,
        "fragmentationReductionRate": frag_reduction_rate,
        "distance_index": distance_index,
        "objective_value": objective_value,
        "make_span": metrics.makespan,
        "tardiness count": metrics.calc_tardiness_count(),
        "dispatch count": metrics.dispatched_count,
        "total distance": metrics.total_agv_move_distance,
    }


def generate_adaptive_alpha_candidates() -> list[tuple[dict, dict, dict]]:
    """Adaptive CPR 탐색을 위한 Phase 1, 2, 3 조합 생성"""
    candidates = []

    # Phase 1 후보 (초반: 긴급도 방어선 0.35~0.50)
    p1_list = [
        {"alpha_1": 0.35, "alpha_2": 0.35, "alpha_3": 0.30},
        {"alpha_1": 0.40, "alpha_2": 0.30, "alpha_3": 0.30},
        {"alpha_1": 0.45, "alpha_2": 0.25, "alpha_3": 0.30},
        {"alpha_1": 0.50, "alpha_2": 0.25, "alpha_3": 0.25},
    ]

    # Phase 2 후보 (중반: 밸런스 0.55~0.65)
    p2_list = [
        {"alpha_1": 0.55, "alpha_2": 0.20, "alpha_3": 0.25},
        {"alpha_1": 0.60, "alpha_2": 0.20, "alpha_3": 0.20},
        {"alpha_1": 0.65, "alpha_2": 0.15, "alpha_3": 0.20},
    ]

    # Phase 3 후보 (후반: 긴급도 올인 0.70~0.85)
    p3_list = [
        {"alpha_1": 0.70, "alpha_2": 0.15, "alpha_3": 0.15},
        {"alpha_1": 0.75, "alpha_2": 0.10, "alpha_3": 0.15},
        {"alpha_1": 0.80, "alpha_2": 0.10, "alpha_3": 0.10},
        {"alpha_1": 0.85, "alpha_2": 0.05, "alpha_3": 0.10},
    ]

    for p1 in p1_list:
        for p2 in p2_list:
            for p3 in p3_list:
                candidates.append((p1, p2, p3))

    return candidates


if __name__ == "__main__":
    scenario_name = "custom"
    sim_time_limit = 172800

    # Layout 정보 로드
    layout_path = (
        Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
    )
    layout = json.loads(layout_path.read_text())
    agv_max_distance = layout["agv_max_distance"]
    greedy_makespan = load_greedy_makespan()

    # Alpha 후보 조합 생성 (총 4 * 3 * 4 = 48개 조합)
    alpha_combos = generate_adaptive_alpha_candidates()
    total_tasks = len(alpha_combos)

    num_cores = os.cpu_count() or 4
    print(
        f"=== CPU 코어 수: {num_cores}개 | 총 {total_tasks}개 Adaptive Alpha 조합 병렬 시뮬레이션 시작 ==="
    )

    task_args = [
        (
            p1,
            p2,
            p3,
            scenario_name,
            sim_time_limit,
            agv_max_distance,
            greedy_makespan,
        )
        for p1, p2, p3 in alpha_combos
    ]

    results = []
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [
            executor.submit(run_single_adaptive_simulation, arg) for arg in task_args
        ]

        for completed_count, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            results.append(res)
            print(
                f"[{completed_count}/{total_tasks}] "
                f"P1:({res['p1_a1']:.2f},{res['p1_a2']:.2f},{res['p1_a3']:.2f}) | "
                f"P2:({res['p2_a1']:.2f},{res['p2_a2']:.2f},{res['p2_a3']:.2f}) | "
                f"P3:({res['p3_a1']:.2f},{res['p3_a2']:.2f},{res['p3_a3']:.2f}) "
                f"-> Obj: {res['objective_value']:.4f} | Tardiness: {res['tardiness count']}건 | Makespan: {res['make_span']:.1f}s"
            )

    # DataFrame 생성 및 목적함수 우수(오름차순) 순 정렬
    df = pd.DataFrame(results)
    df = df.sort_values(
        by=["tardiness count", "objective_value"], ascending=[True, True]
    ).reset_index(drop=True)
    df["index"] = df.index

    # CSV 저장
    output_csv = "cpr_adaptive_alpha_grid_search_results.csv"
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")

    print(f"\n=== 모든 시뮬레이션 완료! 결과가 '{output_csv}'에 저장되었습니다. ===")
    print("\n--- Top 5 Best Adaptive Combinations ---")
    cols_to_show = [
        "p1_a1",
        "p2_a1",
        "p3_a1",
        "tardiness count",
        "make_span",
        "final_fragmentation_index",
        "fragmentationReductionRate",
        "objective_value",
    ]
    print(df.head(5)[cols_to_show])
