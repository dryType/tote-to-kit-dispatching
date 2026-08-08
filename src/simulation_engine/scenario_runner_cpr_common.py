from __future__ import annotations

import json
from pathlib import Path

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
        layout = json.loads(layout_path().read_text())

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

        metrics.print_kit_completion_summary()
        metrics.print_agv_utilization(agvs)
        metrics.print_summary()

        tardiness_index = metrics.calc_tardiness_index()
        init_frag_index = metrics.initial_frag_index
        frag_index = metrics.calc_fragmentation_index()
        distance_index = metrics.calc_distance_index(layout["agv_max_distance"])

        print(f"Tardiness Index: {tardiness_index:.4f}")
        print(
            f"Initial Fragmentation Index: {init_frag_index:.4f}, Final Fragmentation Index: {frag_index:.4f}"
        )
        print(f"Distance Index: {distance_index:.4f})")
        print(
            f"Total Objective Value: {0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index:.4f}"
        )

        return metrics


def generate_alpha_grid(step: float = 0.1) -> list[tuple[float, float, float]]:
    """합이 1.0이 되는 alpha1, alpha2, alpha3 조합만 2중 루프로 생성"""
    grid = []
    steps = round(1.0 / step) + 1
    for i in range(steps):
        a1 = round(i * step, 4)
        for j in range(steps - i):
            a2 = round(j * step, 4)
            a3 = max(0.0, round(1.0 - a1 - a2, 4))
            grid.append((a1, a2, a3))
    return grid


def run_single_simulation(
    args: tuple[float, float, float, float, float, float, float]
    | tuple[float, float, float, float, float, float, float, float]
    | tuple[float, float, float, float, float, float, float, float, float, float]
    | tuple[
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
        float,
    ],
) -> dict:

    if len(args) == 8:
        (
            alpha_1,
            alpha_2,
            alpha_3,
            w_s1,
            w_s2,
            margin_sec,
            agv_max_distance,
            greedy_makespan,
        ) = args
        g1 = 0.2
        g2 = 0.3
        lmb = 0.006
        p = 2.0
    elif len(args) == 7:
        alpha_1, alpha_2, alpha_3, w_s1, w_s2, agv_max_distance, greedy_makespan = args
        margin_sec = 1200.0
        g1 = 0.2
        g2 = 0.3
        lmb = 0.006
        p = 2.0
    elif len(args) == 10:
        (
            alpha_1,
            alpha_2,
            alpha_3,
            w_s1,
            w_s2,
            margin_sec,
            g1,
            g2,
            agv_max_distance,
            greedy_makespan,
        ) = args
        lmb = 0.006
        p = 2.0
    elif len(args) == 12:
        (
            alpha_1,
            alpha_2,
            alpha_3,
            w_s1,
            w_s2,
            margin_sec,
            g1,
            g2,
            lmb,
            p,
            agv_max_distance,
            greedy_makespan,
        ) = args
    policy = CPRTop1Policy(
        alpha_1=alpha_1,
        alpha_2=alpha_2,
        alpha_3=alpha_3,
        w_s1=w_s1,
        w_s2=w_s2,
        g1=g1,
        g2=g2,
        lmb=lmb,
        p=p,
        margin_sec=margin_sec,
    )
    runner = ScenarioRunner("custom", policy)
    metrics = runner.run()

    tardiness_index = metrics.calc_tardiness_index()
    init_frag_index = metrics.initial_frag_index
    frag_index = metrics.calc_fragmentation_index()
    distance_index = metrics.calc_distance_index(agv_max_distance)
    makespan_index = metrics.calc_makespan_index(greedy_makespan)

    objective_value = (
        0.55 * tardiness_index
        + 0.05 * makespan_index
        + 0.3 * frag_index
        + 0.1 * distance_index
    )

    return {
        "alpha_1": alpha_1,
        "alpha_2": alpha_2,
        "alpha_3": alpha_3,
        "w_s1": w_s1,
        "w_s2": w_s2,
        "gamma1": g1,
        "gamma2": g2,
        "margin_sec": margin_sec,
        "lambda": lmb,
        "p": p,
        "tardiness_index": tardiness_index,
        "makespan_index": makespan_index,
        "initial_fragmentation_index": init_frag_index,
        "final_fragmentation_index": frag_index,
        "fragmentationReductionRate": round(
            (init_frag_index - frag_index) / init_frag_index * 100, 2
        ),
        "distance_index": distance_index,
        "objective_value": objective_value,
        "make_span": metrics.makespan,
        "tardiness count": metrics.calc_tardiness_count(),
        "dispatch count": metrics.dispatched_count,
        "total distance": metrics.total_agv_move_distance,
    }


def layout_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"


def greedy_result_path() -> Path:
    return Path(__file__).resolve().parent / "greedy_result.json"


def load_layout() -> dict:
    return json.loads(layout_path().read_text())


def load_greedy_makespan() -> float:
    with greedy_result_path().open("r", encoding="utf-8") as fh:
        return json.load(fh)["makespan"]
