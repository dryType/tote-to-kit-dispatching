from typing import Dict

from simulation_engine.entities import AGV, AGVStatus, KittingStation, Tote


class WorldStateSnapshot:
    def __init__(
        self,
        now: float,
        agvs: Dict[str, AGV],
        stations: Dict[str, KittingStation],
        totes: Dict[str, Tote],
        order_manager,
    ):
        self.now = now
        self.agvs = agvs
        self.stations = stations
        self.totes = totes
        self.order_manager = order_manager

    def get_idle_agvs(self):
        idle_agvs = []
        for agv_id, agv in self.agvs.items():
            if agv.status == AGVStatus.IDLE:
                idle_agvs.append(agv)
        return idle_agvs
