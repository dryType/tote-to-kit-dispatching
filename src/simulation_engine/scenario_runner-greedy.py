import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from policy.base_policy import BasePolicy
from policy.greedy.greedy_policy import GreedyPolicy
from simulation_engine.dataset_loader import load_entities_from_scenario
from simulation_engine.orderManager import OrderManager
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
        # metrics.to_dataframe().to_csv(f"metrics_{self.scenario_name}.csv", index=False)
        # metrics.export_to_html_report(
        #     kits=order_manager.activated_kits,
        #     totes=totes,
        #     filename=f"simulation_report_{self.scenario_name}.html",
        # )

        return metrics


if __name__ == "__main__":
    layout_path = (
        Path(__file__).resolve().parents[2] / "data" / "master_data" / "layout.json"
    )
    layout = json.loads(layout_path.read_text())
    max_x = layout["map_bounds"]["max_x"]
    max_y = layout["map_bounds"]["max_y"]

    policy = GreedyPolicy()
    print(__file__)

    result = None

    scenario_name = "custom"
    runner = ScenarioRunner(scenario_name, policy)
    metrics = runner.run()

    tardiness_index = metrics.calc_tardiness_index()
    init_frag_index = metrics.initial_frag_index
    frag_index = metrics.calc_fragmentation_index()
    distance_index = metrics.calc_distance_index(max_x, max_y)
    objective_value = 0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index

    print(f"Tardiness Index: {tardiness_index:.4f}")
    print(
        f"Initial Fragmentation Index: {init_frag_index:.4f}, Final Fragmentation Index: {frag_index:.4f}"
    )
    print(f"Distance Index: {distance_index:.4f})")
    print(
        f"Total Objective Value: {0.6 * tardiness_index + 0.3 * frag_index + 0.1 * distance_index:.4f}"
    )

    result = {
        "tardiness_index": tardiness_index,
        "initial_fragmentation_index": init_frag_index,
        "final_fragmentation_index": frag_index,
        "distance_index": distance_index,
        "objective_value": objective_value,
    }

    print(result)
