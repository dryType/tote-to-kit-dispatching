# config/constants.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ToteSpec:
    MAX_CAPACITY_CM3: int = 57600


@dataclass(frozen=True)
class KitSpec:
    TOTAL_CAPACITY_CM3: int = 1512000


@dataclass(frozen=True)
class KittingStationSpec:
    FULL_CARTON_TRANSFER_TIME_SEC: float = 10.0
    PARTIAL_CARTON_TRANSFER_TIME_SEC: float = 20.0
    KIT_CHANGING_TIME_SEC: float = 60.0


@dataclass(frozen=True)
class AGVSpec:
    SPEED_M_PER_S: float = 1.5
    TOTE_PICKUP_TIME_S: float = 5
    TOTE_PUTDOWN_TIME_S: float = 5
