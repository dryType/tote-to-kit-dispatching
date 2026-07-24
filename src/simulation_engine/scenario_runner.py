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

        #kit의 deaeline과 completion time을 비교하여 지표를 확인할 수 있음
        for kit in order_manager.activated_kits:
            print(
                f"Kit {kit.kit_id} completed at t={kit.completed_time_sec}, "
                f"deadline was t={kit.start_time_sec}."
            )
            
        return metrics


if __name__ == "__main__":
    policy = GreedyPolicy()

    runner = ScenarioRunner("custom", policy)
    metrics = runner.run()

    

    # 지표 확인
    # print(f"Completed Kits: {metrics.completed_kits_count}")
