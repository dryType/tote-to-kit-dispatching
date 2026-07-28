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

        total_tardiness_sq = 0.0
        for kit in order_manager.activated_kits:
            tardiness = max(0.0, kit.completed_time_sec - kit.deadline_time_sec)
            total_tardiness_sq += tardiness**2

        print(f"Total tardiness squared: {total_tardiness_sq:.2f}")

        metrics.print_kit_completion_summary()
        metrics.print_agv_utilization(agvs)
        metrics.print_summary()
        metrics.to_dataframe().to_csv(f"metrics_{self.scenario_name}.csv", index=False)
        metrics.export_to_html_report(
            kits=order_manager.activated_kits,
            totes=totes,
            filename=f"simulation_report_{self.scenario_name}.html",
        )

        return metrics


if __name__ == "__main__":
    policy = GreedyPolicy()
    print(__file__)

    scenario_name = "custom"
    runner = ScenarioRunner(scenario_name, policy)
    metrics = runner.run()
    total_tardiness = metrics.calc_total_tardiness()
    tardiness_count = metrics.calc_tardiness_count()
    # data/generated_datasets/scenario_"시나리오명"/greedy_result.json에 total_tardiness를 기록  경로를 못찾는듯
    with open(
        f"data/generated_datasets/scenario_{scenario_name}/greedy_result.json", "w"
    ) as f:
        json.dump(
            {"total_tardiness": total_tardiness, "tardiness_count": tardiness_count}, f
        )
    # metrics 결과 확인
