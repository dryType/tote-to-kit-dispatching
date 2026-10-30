"""사전 계획 그대로 실행 비교군 (교란 실험용).

- RecordingPolicy: 다른 정책을 감싸서 결정적 실행에서 고른 (토트, 키트) 순서를 기록한다.
- PlanPolicy: 기록한 계획을 교란 환경에서 그대로 실행한다. AGV는 토트에 가장 가까운 쉬는 AGV.
  strict: 계획 순서를 지킨다. 맨 앞 항목을 지금 할 수 없으면 기다린다.
  repair: 앞쪽 window개 중 지금 할 수 있는 첫 항목을 먼저 실행한다 (간단한 수리).
  어느 쪽이든 더 이상 할 수 없는 항목(키트 완료, 토트에 필요한 부품이 없음)은 버린다.
  계획을 다 쓰고도 남은 일이 있으면 fallback 정책으로 넘어간다.
"""

from __future__ import annotations

from policy.base_policy import BasePolicy
from simulation_engine.entities import ToteStatus


class RecordingPolicy(BasePolicy):
    def __init__(self, inner: BasePolicy):
        self.inner = inner
        self.plan: list[tuple[str, str]] = []

    @property
    def name(self):
        return f"Recording({self.inner.name})"

    def select(self, now, candidates, idle_agvs, state, dispatched_count=0):
        cand, agv = self.inner.select(now, candidates, idle_agvs, state, dispatched_count)
        if cand is not None and agv is not None:
            self.plan.append((cand.tote.tote_id, cand.kit.kit_id))
        return cand, agv


class PlanPolicy(BasePolicy):
    def __init__(self, plan: list[tuple[str, str]], repair: bool = False, window: int = 30,
                 fallback: BasePolicy | None = None):
        self.plan = list(plan)
        self.repair = repair
        self.window = window
        self.fallback = fallback
        self.dropped = 0
        self.fallback_used = 0

    @property
    def name(self):
        return "Plan (repair)" if self.repair else "Plan (strict)"

    def _dead(self, item, index, state) -> bool:
        """더 이상 실행할 수 없는 항목인가."""
        tote_id, kit_id = item
        kit = next((k for k in state.order_manager.get_all_kits() if k.kit_id == kit_id), None)
        if kit is None or kit.is_completed():
            return True
        station = kit.assigned_station
        tote = state.totes.get(tote_id)
        if station is None or tote is None or tote.status == ToteStatus.BUSY:
            return False  # 아직 시작 전이거나 토트가 운반 중: 기다린다
        if station.assigned_kit is not kit or not station.can_accept_agv():
            return False
        return item not in index  # 할 수 있는 조건인데 후보가 아니면 토트에 필요한 부품이 없다

    def select(self, now, candidates, idle_agvs, state, dispatched_count=0):
        if not candidates or not idle_agvs:
            return None, None
        index = {(c.tote.tote_id, c.kit.kit_id): c for c in candidates}
        i = 0
        while i < len(self.plan) and (self.repair and i < self.window or i == 0):
            item = self.plan[i]
            if self._dead(item, index, state):
                self.plan.pop(i)
                self.dropped += 1
                continue
            if item in index:
                self.plan.pop(i)
                cand = index[item]
                agv = min(idle_agvs, key=lambda a: a.position.manhattan_distance_to(cand.tote.position))
                return cand, agv
            i += 1
        if not self.plan and self.fallback is not None:
            self.fallback_used += 1
            return self.fallback.select(now, candidates, idle_agvs, state, dispatched_count)
        return None, None
