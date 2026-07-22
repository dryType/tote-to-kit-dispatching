# config/constants.py
from dataclasses import dataclass


@dataclass(frozen=True)
class ToteSpec:
    MAX_CAPACITY_CM3: int = 57600


@dataclass(frozen=True)
class KitSpec:
    TOTAL_CAPACITY_CM3: int = 1512000


@dataclass(frozen=True)
class AGVSpec:
    SPEED_M_PER_S: float = 1.5
