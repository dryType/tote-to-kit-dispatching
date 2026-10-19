"""문헌 ATC 규칙(Vepsalainen & Morton, 1987)을 키트 단위로 적용한 비교군.

- 키트 선택: 우선순위 = (1 / P_k) × exp(-max(0, d_k - P_k - t) / (κ × P̄))
    P_k: 키트의 남은 작업 시간 추정 (부품별 추정 디스패치 수, 스테이션당 AGV 2대, 도킹 1자리 기준)
    P̄  : 후보 키트들의 P_k 평균
- 토트 선택: Greedy와 같은 최대 충족 (이번 이송 후 진척률 + 완료 보너스)
- AGV: 토트에 가장 가까운 AGV

Greedy(납기 우선 + 최대 충족)에서 키트 선택만 ATC로 바꾼 형태다.
"""

from __future__ import annotations

import math

from config.constants import AGVSpec
from policy.base_policy import BasePolicy
from policy.greedy.greedy_policy import GreedyPolicy
from simulation_engine.entities import AGV, DispatchCandidate
from simulation_engine.load_estimator import (
    AGV_SLOTS_PER_STATION,
    DOCK_APPROACH_M,
    mean_distances,
    transfer_time,
)
from simulation_engine.state import WorldStateSnapshot


class ATCKitPolicy(BasePolicy):
    def __init__(self, kappa: float = 2.0):
        self.kappa = kappa
        self._distances: tuple[float, float] | None = None
        self._greedy = GreedyPolicy()

    @property
    def name(self):
        return "ATC Kit Policy"

    def _remaining_work(self, remaining, state: WorldStateSnapshot, qbar, lot) -> float:
        if self._distances is None:
            self._distances = mean_distances(
                [(t.position.x, t.position.y) for t in state.totes.values()],
                [(s.position.x, s.position.y) for s in state.stations.values()],
            )
        empty_m, tote_station_m = self._distances
        speed = AGVSpec.SPEED_M_PER_S
        n_hat = sum(math.ceil(q / qbar[p]) for p, q in remaining.items() if qbar.get(p))
        transfer = sum(transfer_time(q, lot.get(p, 1)) for p, q in remaining.items())
        slot = AGVSpec.TOTE_PICKUP_TIME_S + (empty_m + tote_station_m) / speed
        return max((n_hat * slot + transfer) / AGV_SLOTS_PER_STATION,
                   n_hat * DOCK_APPROACH_M / speed + transfer)

    def select(
        self,
        now: float,
        candidates: list[DispatchCandidate],
        idle_agvs: list[AGV],
        state: WorldStateSnapshot,
        dispatched_count: int = 0,
    ) -> tuple[DispatchCandidate | None, AGV | None]:
        if not candidates or not idle_agvs:
            return None, None

        stock: dict[str, int] = {}
        holders: dict[str, int] = {}
        lot: dict[str, int] = {}
        for tote in state.totes.values():
            for comp in tote.contents:
                if comp.quantity > 0:
                    stock[comp.part_id] = stock.get(comp.part_id, 0) + comp.quantity
                    holders[comp.part_id] = holders.get(comp.part_id, 0) + 1
                    lot[comp.part_id] = comp.lot_size or 1
        qbar = {p: stock[p] / holders[p] for p in stock}

        kits = {}
        for c in candidates:
            if c.kit.kit_id not in kits:
                kits[c.kit.kit_id] = (c.kit, self._remaining_work(c.kit.get_remaining_parts(), state, qbar, lot))
        p_bar = max(1.0, sum(p for _, p in kits.values()) / len(kits))

        def priority(item):
            kit, p = item
            slack = float(kit.deadline_time_sec) - p - now
            return (1.0 / max(p, 1.0)) * math.exp(-max(0.0, slack) / (self.kappa * p_bar))

        best_kit = max(kits.values(), key=priority)[0]
        pool = [c for c in candidates if c.kit is best_kit]
        best = max(pool, key=self._greedy._calc_progress_score)
        agv = min(idle_agvs, key=lambda a: a.position.manhattan_distance_to(best.tote.position))
        return best, agv
