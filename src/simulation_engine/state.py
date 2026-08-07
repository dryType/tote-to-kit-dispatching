from simulation_engine.entities import AGV, AGVStatus, KittingStation, Tote
from simulation_engine.orderManager import OrderManager


class WorldStateSnapshot:
    def __init__(
        self,
        now: float,
        agvs: dict[str, AGV],
        stations: dict[str, KittingStation],
        totes: dict[str, Tote],
        order_manager: OrderManager,
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
