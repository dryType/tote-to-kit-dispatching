from abc import ABC, abstractmethod
from typing import List, Optional

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
        candidates: List[DispatchCandidate],
        idle_agvs: List[AGV],
        state: WorldStateSnapshot,
    ) -> tuple[Optional[DispatchCandidate], Optional[AGV]]:
        # 후보 중 하나 선택하여 반환
        pass
