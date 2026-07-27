from abc import ABC, abstractmethod

from simulation_engine.entities import AGV, DispatchCandidate
from simulation_engine.state import WorldStateSnapshot


class BasePolicy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        # 정책 명칭 반환
        pass

    @abstractmethod
    def select(
        self,
        now: float,
        candidates: list[DispatchCandidate],
        idle_agvs: list[AGV],
        state: WorldStateSnapshot,
    ) -> tuple[DispatchCandidate | None, AGV | None]:
        # 후보 중 하나 선택하여 반환
        pass
