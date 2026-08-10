import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from policy.base_policy import BasePolicy
from policy.cpr.simple_adaptive_cpr_top_1_policy import SimpleAdaptiveCPRTop1Policy
from policy.greedy.greedy_policy import GreedyPolicy
from simulation_engine.dataset_loader import load_entities_from_scenario
from simulation_engine.orderManager import OrderManager
from simulation_engine.scenario_runner_cpr_common import load_greedy_makespan
from simulation_engine.simulator import Simulator


class ScenarioRunner:
    def __init__(self, scenario_name: str, policy: BasePolicy):
        self.scenario_name = scenario_name
        self.policy = policy

    def run(self, sim_time_limit: float = 172800):
        totes, kits, stations, agvs = load_entities_from_scenario(self.scenario_name)
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

        return metrics


if __name__ == "__main__":
    layout_path = (
        Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
    )
    layout = json.loads(layout_path.read_text())
    max_x = layout["map_bounds"]["max_x"]
    max_y = layout["map_bounds"]["max_y"]

    phase1_alpha = {"alpha_1": 0.5, "alpha_2": 0.25, "alpha_3": 0.25}
    phase2_alpha = {"alpha_1": 0.6, "alpha_2": 0.20, "alpha_3": 0.2}
    phase3_alpha = {"alpha_1": 0.75, "alpha_2": 0.1, "alpha_3": 0.15}

    policy = SimpleAdaptiveCPRTop1Policy(
        phase1_alpha=phase1_alpha, phase2_alpha=phase2_alpha, phase3_alpha=phase3_alpha
    )
    print(__file__)

    result = None

    scenario_name = "custom"
    runner = ScenarioRunner(scenario_name, policy)
    metrics = runner.run()

    tardiness_index = metrics.calc_tardiness_index()
    init_frag_index = metrics.initial_frag_index
    frag_index = metrics.calc_fragmentation_index()
    distance_index = metrics.calc_distance_index(layout["agv_max_distance"])
    greedy_makespan = load_greedy_makespan()
    makespan_index = metrics.calc_makespan_index(greedy_makespan)
    objective_value = (
        0.55 * tardiness_index
        + 0.05 * makespan_index
        + 0.3 * frag_index
        + 0.1 * distance_index
    )

    result = {
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

    print(f"Tardiness Index: {tardiness_index:.4f}")
    print(
        f"Initial Fragmentation Index: {init_frag_index:.4f}, Final Fragmentation Index: {frag_index:.4f}"
    )
    print(f"Distance Index: {distance_index:.4f})")
    print(
        f"Total Objective Value: {0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index:.4f}"
    )

    print(result)
