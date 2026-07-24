from typing import List

import simpy

from policy.base_policy import BasePolicy
from simulation_engine.dispatcher import Dispatcher
from simulation_engine.entities import AGV, KittingStation, Tote
from simulation_engine.metrics import Metrics
from simulation_engine.orderManager import OrderManager
from simulation_engine.state import WorldStateSnapshot


class Simulator:
    def __init__(
        self,
        agvs: List[AGV],
        stations: List[KittingStation],
        totes: List[Tote],
        order_manager: OrderManager,
        policy: BasePolicy,
        sim_time_limit: float = 3600.0,
    ):
        self.agvs = agvs
        self.stations = stations
        self.totes = totes
        self.order_manager = order_manager
        self.policy = policy
        self.sim_time_limit = sim_time_limit

        self.env = simpy.Environment()
        self.metrics = Metrics()

        for station in self.stations:
            station.init_simulation(self.env, self.order_manager)

            initial_kit = self.order_manager.pop_next_kit()
            if initial_kit is not None:
                station.assign_kit(initial_kit)

        self.world_state = WorldStateSnapshot(
            now=0.0,
            agvs={agv.agv_id: agv for agv in self.agvs},
            stations={station.station_id: station for station in self.stations},
            totes={tote.tote_id: tote for tote in self.totes},
            order_manager=self.order_manager,
        )
        self.dispatcher = Dispatcher(
            self.env, self.world_state, self.policy, self.metrics
        )

    def run(self) -> Metrics:
        self.env.process(self.dispatcher.run())

        self.dispatcher.notify()

        self.env.run(until=self.sim_time_limit)
        return self.metrics
