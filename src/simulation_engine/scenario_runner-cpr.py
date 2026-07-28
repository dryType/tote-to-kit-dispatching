import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from sklearn import metrics

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from policy.base_policy import BasePolicy
from policy.cpr.cpr_top_1_policy import CPRTop1Policy
from simulation_engine.dataset_loader import load_entities_from_scenario
from simulation_engine.orderManager import OrderManager
from simulation_engine.simulator import Simulator


class ScenarioRunner:
    def __init__(self, scenario_name: str, policy: BasePolicy):
        self.scenario_name = scenario_name
        self.policy = policy

    def run(self, sim_time_limit: float = 172800):
        totes, kits, stations, agvs = load_entities_from_scenario(self.scenario_name)
        layout_path = (
            Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
        )
        layout = json.loads(layout_path.read_text())
        self.max_x = layout["map_bounds"]["max_x"]
        self.max_y = layout["map_bounds"]["max_y"]

        order_manager = OrderManager(pending_kits=kits)

        simulator = Simulator(
            agvs=agvs,
            stations=stations,
            totes=totes,
            order_manager=order_manager,
            policy=self.policy,
            sim_time_limit=sim_time_limit,
        )

        metrics = simulator.run()

        # kit의 deaeline과 completion time을 비교하여 지표를 확인할 수 있음

        # metrics.print_kit_completion_summary()
        # metrics.print_agv_utilization(agvs)
        metrics.print_summary()

        tardiness_index = metrics.calc_tardiness_index(4844970.67)
        init_frag_index = metrics.initial_frag_index
        frag_index = metrics.calc_fragmentation_index()
        distance_index = metrics.calc_distance_index(self.max_x, self.max_y)

        print(f"Tardiness Index: {tardiness_index:.4f}")
        print(
            f"Initial Fragmentation Index: {init_frag_index:.4f}, Final Fragmentation Index: {frag_index:.4f}"
        )
        print(f"Distance Index: {distance_index:.4f})")
        print(
            f"Total Objective Value: {0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index:.4f}"
        )

        # metrics.to_dataframe().to_csv(f"metrics_{self.scenario_name}.csv", index=False)
        # metrics.export_to_html_report(
        #     kits=order_manager.activated_kits,
        #     totes=totes,
        #     filename=f"simulation_report_{self.scenario_name}.html",
        # )

        return metrics


def generate_alpha_grid(step: float = 0.1) -> list[tuple[float, float, float]]:
    """합이 1.0이 되는 alpha1, alpha2, alpha3 조합만 2중 루프로 생성"""
    grid = []
    steps = int(round(1.0 / step)) + 1
    for i in range(steps):
        a1 = round(i * step, 4)
        for j in range(steps - i):
            a2 = round(j * step, 4)
            a3 = max(0.0, round(1.0 - a1 - a2, 4))
            grid.append((a1, a2, a3))
    return grid


def run_single_simulation(args: tuple[float, float, float, float, float]) -> dict:
    alpha_1, alpha_2, alpha_3, max_x, max_y = args

    policy = CPRTop1Policy(alpha_1=alpha_1, alpha_2=alpha_2, alpha_3=alpha_3)
    runner = ScenarioRunner("custom", policy)
    metrics = runner.run()

    tardiness_index = metrics.calc_tardiness_index(4844970.67)
    init_frag_index = metrics.initial_frag_index
    frag_index = metrics.calc_fragmentation_index()
    distance_index = metrics.calc_distance_index(max_x, max_y)

    objective_value = 0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index

    return {
        "alpha_1": alpha_1,
        "alpha_2": alpha_2,
        "alpha_3": alpha_3,
        "tardiness_index": tardiness_index,
        "initial_fragmentation_index": init_frag_index,
        "final_fragmentation_index": frag_index,
        "distance_index": distance_index,
        "objective_value": objective_value,
        "make_span": metrics.makespan,
        "tardiness count": metrics.calc_tardiness_count(),
        "dispatch count": metrics.dispatched_count,
        "total distance": metrics.total_agv_move_distance,
    }


if __name__ == "__main__":
    layout_path = (
        Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
    )
    layout = json.loads(layout_path.read_text())
    max_x = layout["map_bounds"]["max_x"]
    max_y = layout["map_bounds"]["max_y"]

    alpha_combinations = generate_alpha_grid(step=0.05)
    total_tasks = len(alpha_combinations)

    num_cores = os.cpu_count() or 4
    print(
        f"=== CPU 코어 수: {num_cores}개 | 총 {total_tasks}개 알파 조합 병렬 시뮬레이션 시작 ==="
    )

    # 인자 패킹 (max_x, max_y 전달)
    task_args = [(a1, a2, a3, max_x, max_y) for a1, a2, a3 in alpha_combinations]

    results = []

    # 멀티프로세서 풀 가동
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        futures = [executor.submit(run_single_simulation, arg) for arg in task_args]

        completed_count = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            completed_count += 1
            print(
                f"[{completed_count}/{total_tasks}] Alpha: ({res['alpha_1']:.2f}, {res['alpha_2']:.2f}, {res['alpha_3']:.2f}) -> Obj Value: {res['objective_value']:.4f}"
            )

    # DataFrame 생성 및 목적함수 우수(오름차순) 순 정렬
    df = pd.DataFrame(results)
    df = df.sort_values(by="objective_value", ascending=True).reset_index(drop=True)
    df["index"] = df.index  # 정렬 후 순위 인덱스 부여

    # CSV 저장
    output_csv = "alpha_grid_search_results.csv"
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


# if __name__ == "__main__":
#     layout_path = (
#         Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
#     )
#     layout = json.loads(layout_path.read_text())
#     max_x = layout["map_bounds"]["max_x"]
#     max_y = layout["map_bounds"]["max_y"]

#     alpha_combinations = generate_alpha_grid(step=0.05)

#     results = []

#     for alpha_1, alpha_2, alpha_3 in alpha_combinations:
#         policy = CPRTop1Policy(alpha_1=alpha_1, alpha_2=alpha_2, alpha_3=alpha_3)
#         runner = ScenarioRunner("custom", policy)
#         metrics = runner.run()
#         tardiness_index = metrics.calc_tardiness_index(4844970.67)
#         init_frag_index = metrics.initial_frag_index
#         frag_index = metrics.calc_fragmentation_index()
#         distance_index = metrics.calc_distance_index(max_x, max_y)
#         objective_value = (
#             0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index
#         )
#         results.append(
#             {
#                 "index": len(results),
#                 "alpha_1": alpha_1,
#                 "alpha_2": alpha_2,
#                 "alpha_3": alpha_3,
#                 "tardiness_index": tardiness_index,
#                 "initial_fragmentation_index": init_frag_index,
#                 "final_fragmentation_index": frag_index,
#                 "distance_index": distance_index,
#                 "objective_value": objective_value,
#                 "make_span": metrics.makespan,
#                 "tardiness count": metrics.calc_tardiness_count(),
#                 "dispatch count": metrics.dispatched_count,
#                 "total distance": metrics.total_agv_move_distance,
#             }
#         )
#         print(
#             f"Index: {len(results)}, Alpha: ({alpha_1}, {alpha_2}, {alpha_3}), Objective Value: {objective_value:.4f}"
#         )

#     # DataFrame 생성 및 정렬 (목적함수 점수 좋은 순)
#     df = pd.DataFrame(results)
#     df = df.sort_values(by="objective_value", ascending=True)

#     # CSV 저장
#     df.to_csv("alpha_grid_search_results.csv", index=False, encoding="utf-8-sig")
