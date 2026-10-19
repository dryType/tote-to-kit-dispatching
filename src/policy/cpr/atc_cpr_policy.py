"""ATC형 곱 구조의 CPR 정책 (설계 초안, 변형 비교용).

점수(j, k) = U_k × V_jk × F_jk  (계산은 로그 공간에서)

- U_k  긴급도 = exp(-max(0, σ_k) / κ)
       σ_k = (납기 - 현재 - 남은 작업 추정) / τ̄     (slack_mode="work")
       σ_k = (납기 - 현재) / τ̄                       (slack_mode="deadline", 대조군)
- V_jk 효율 = Δ_jk / τ_jk^d
       Δ: 이 디스패치로 줄어드는 키트의 남은 디스패치 수
          "ceil"   Σ_m ⌈r_m/q̄_m⌉ - ⌈(r_m - x_m)/q̄_m⌉
          "cont"   Σ_m x_m / min(r_m, q̄_m)
          "hybrid" ceil + cont / 10
       τ: "avoidable" = 집기·내려놓기 + 이동 시간, "full" = 여기에 카톤 이송 시간 추가 (대조군)
- F_jk 토트 상태
       "usage"   (1 + u_jk)^c, u = 이번에 꺼내는 부피 / 토트에 남은 "오늘 필요한" 부품 부피 (필요량 이상은 제외)
       "partial" exp(-c × 새로 일부만 쓰이는 부품 재고 수)
                 손대지 않은 부품 재고를 일부만 꺼내 남기면 1개로 센다. 이미 열린 재고에서 꺼내거나
                 재고를 다 비우면 벌점이 없다. 부품마다 열린 재고를 하나로 유지해 초과분을 적은 토트에 모으려는 항
       "clear"   exp(c × (다 비우는 부품 재고 수 - 새로 일부만 쓰이는 부품 재고 수))
       "carton"  exp(-c × 이 디스패치로 늘어나는 자투리 카톤 수)  (-1, 0, +1 / 부품)
                 잔량 토트 수와 자투리 카톤 수의 상관이 0.95 이상이었던 점을 이용한다
       "oldsf"   exp(c × 기존 CPR의 S_F)  (w_s1=0.3, w_s2=0.7, 비교용)
       "sf_dead" 기존 S_F의 카톤 빈 공간 변화 성분만 (w_s1=1, w_s2=0)
       "sf_clear" 기존 S_F의 비우기 보너스 - 미래 벌점 성분만 (w_s1=0, w_s2=1)
       "remain"  exp(-c × Σ_m 꺼낸 뒤 남는 수량 / q̄_m)  (다 비우면 0)
                 효율이 같은 후보 중 필요량에 가장 잘 맞는 토트, 이미 열린 소량 토트를 먼저 쓰게 한다

r_m: 키트의 남은 수량, x_m: 이번에 꺼내는 수량, q̄_m: 부품 m의 토트당 평균 재고.

추가 항 (새 방식)
- 초과분 보관 토트 (c_excess > 0): exp(-c_excess × 보관 토트 위반 수)
       부품 m의 초과분 E_m = 총재고 - 예약 중 수량 - 남은 키트 전체 필요량 (실행 중 변하지 않음).
       결정 시점마다 부품별로 초과분을 맡길 보관 토트를 하나 고른다
       (① 초과분을 다 담을 수 있는 토트 ② 이미 다른 부품의 보관 토트로 지정된 토트 ③ 재고가 초과분에 가장 가까운 토트).
       보관 토트에서 초과분 아래로 꺼내면 위반 1. 잔량 토트 = 초과분이 든 토트이므로 초과분을 소수 토트에 모은다.
       excess_relax가 있으면, 남은 작업을 뺀 여유(σ_work)가 그 값 이하인 급한 키트에는 벌점을 주지 않는다.
- 관문형 긴급도 (gate가 None이 아니면): 여유 σ ≤ gate인 키트가 있으면 그 키트의 후보만 남기고,
       연속 긴급도 U는 쓰지 않는다 (납기 준수 우선 평가를 정책 안에 옮긴 형태).
"""

from __future__ import annotations

import math
from dataclasses import replace

from config.constants import AGVSpec
from policy.base_policy import BasePolicy
from policy.cpr.cpr_score import CPRScore
from simulation_engine.entities import AGV, DispatchCandidate, Kit, ToteStatus
from simulation_engine.load_estimator import (
    AGV_SLOTS_PER_STATION,
    DOCK_APPROACH_M,
    mean_distances,
    transfer_time,
)
from simulation_engine.state import WorldStateSnapshot

PICK_PUT_SEC = AGVSpec.TOTE_PICKUP_TIME_S + AGVSpec.TOTE_PUTDOWN_TIME_S


class ATCCPRPolicy(BasePolicy):
    def __init__(
        self,
        kappa: float = 8.0,
        c: float = 1.0,
        d: float = 1.0,
        slack_mode: str = "work",
        delta_mode: str = "hybrid",
        denom_mode: str = "avoidable",
        tote_mode: str = "usage",
        c_excess: float = 0.0,
        gate: float | None = None,
        excess_relax: float | None = None,
    ):
        self.kappa = kappa
        self.c = c
        self.d = d
        self.slack_mode = slack_mode
        self.delta_mode = delta_mode
        self.denom_mode = denom_mode
        self.tote_mode = tote_mode
        self.c_excess = c_excess
        self.gate = gate
        self.excess_relax = excess_relax
        self._distances: tuple[float, float] | None = None
        self._initial_qty: dict[str, dict[str, int]] = {}
        sf_weights = {"oldsf": (0.3, 0.7), "sf_dead": (1.0, 0.0), "sf_clear": (0.0, 1.0)}
        self._old_sf = (
            CPRScore(w_s1=sf_weights[tote_mode][0], w_s2=sf_weights[tote_mode][1])
            if tote_mode in sf_weights
            else None
        )
        self._calls = 0

    @property
    def name(self):
        return "ATC CPR Policy"

    # ------------------------------------------------------------------
    # 결정 시점마다 한 번 계산하는 값
    # ------------------------------------------------------------------

    def _mean_distances(self, state: WorldStateSnapshot) -> tuple[float, float]:
        # 토트 위치는 바뀌지 않으므로 처음 한 번만 계산한다
        if self._distances is None:
            self._distances = mean_distances(
                [(t.position.x, t.position.y) for t in state.totes.values()],
                [(s.position.x, s.position.y) for s in state.stations.values()],
            )
        return self._distances

    @staticmethod
    def _stock_stats(state: WorldStateSnapshot):
        stock: dict[str, int] = {}
        holders: dict[str, int] = {}
        v_part: dict[str, int] = {}
        lot: dict[str, int] = {}
        for tote in state.totes.values():
            for comp in tote.contents:
                if comp.quantity <= 0:
                    continue
                stock[comp.part_id] = stock.get(comp.part_id, 0) + comp.quantity
                holders[comp.part_id] = holders.get(comp.part_id, 0) + 1
                v_part[comp.part_id] = comp.v_part or 0
                lot[comp.part_id] = comp.lot_size or 1
        qbar = {p: stock[p] / holders[p] for p in stock}
        return qbar, v_part, lot

    @staticmethod
    def _future_demand(state: WorldStateSnapshot) -> dict[str, int]:
        demand: dict[str, int] = {}
        for kit in state.order_manager.get_all_kits():
            if kit.is_completed():
                continue
            for part_id, qty in kit.get_remaining_parts().items():
                demand[part_id] = demand.get(part_id, 0) + qty
        return demand

    def _kit_sigma(
        self,
        kit: Kit,
        remaining: dict[str, int],
        now: float,
        qbar: dict[str, float],
        lot: dict[str, int],
        empty_m: float,
        tote_station_m: float,
        tau_bar: float,
        slack_mode: str | None = None,
    ) -> float:
        """여유 시간을 디스패치 1회 평균 시간으로 나눈 값."""
        slack = float(kit.deadline_time_sec) - now
        if (slack_mode or self.slack_mode) == "work":
            speed = AGVSpec.SPEED_M_PER_S
            n_hat = sum(math.ceil(q / qbar[p]) for p, q in remaining.items() if qbar.get(p))
            transfer = sum(transfer_time(q, lot.get(p, 1)) for p, q in remaining.items())
            slot = AGVSpec.TOTE_PICKUP_TIME_S + (empty_m + tote_station_m) / speed
            by_slots = (n_hat * slot + transfer) / AGV_SLOTS_PER_STATION
            by_dock = n_hat * DOCK_APPROACH_M / speed + transfer
            slack -= max(by_slots, by_dock)
        return slack / tau_bar

    def _excess_holders(self, state: WorldStateSnapshot) -> dict[str, tuple[str, int]]:
        """부품 → (초과분 보관 토트 id, 초과분). 초과분이 없는 부품은 빠진다."""
        total: dict[str, int] = {}
        options: dict[str, list[tuple[str, int]]] = {}
        for tote in state.totes.values():
            for comp in tote.contents:
                if comp.quantity <= 0:
                    continue
                total[comp.part_id] = total.get(comp.part_id, 0) + comp.quantity
                if tote.status != ToteStatus.BUSY:
                    options.setdefault(comp.part_id, []).append((tote.tote_id, comp.quantity))

        demand = self._future_demand(state)
        reserved: dict[str, int] = {}
        for kit in state.order_manager.get_all_kits():
            for part_id, qty in kit.reserved_parts.items():
                reserved[part_id] = reserved.get(part_id, 0) + qty

        excess = {}
        for part_id, qty in total.items():
            e = qty - reserved.get(part_id, 0) - demand.get(part_id, 0)
            if e > 0 and options.get(part_id):
                excess[part_id] = e

        holders: dict[str, tuple[str, int]] = {}
        hosting: dict[str, int] = {}
        for part_id in sorted(excess, key=lambda p: (-excess[p], p)):
            e = excess[part_id]
            tote_id, _ = min(
                options[part_id],
                key=lambda o: (o[1] < e, -hosting.get(o[0], 0), abs(o[1] - e), o[0]),
            )
            holders[part_id] = (tote_id, e)
            hosting[tote_id] = hosting.get(tote_id, 0) + 1
        return holders

    @staticmethod
    def _holder_violations(
        candidate: DispatchCandidate, holders: dict[str, tuple[str, int]]
    ) -> int:
        count = 0
        for part_id, x in candidate.matched_parts.items():
            holder = holders.get(part_id)
            if holder is None or holder[0] != candidate.tote.tote_id:
                continue
            if candidate.tote.get_component_quantity(part_id) - x < holder[1]:
                count += 1
        return count

    # ------------------------------------------------------------------
    # 후보별 점수
    # ------------------------------------------------------------------

    def _delta(self, matched: dict[str, int], remaining: dict[str, int], qbar: dict[str, float]):
        ceil_part = 0.0
        cont_part = 0.0
        for part_id, x in matched.items():
            r = remaining.get(part_id, 0)
            q = qbar.get(part_id)
            if r <= 0 or not q:
                continue
            ceil_part += math.ceil(r / q) - math.ceil((r - x) / q)
            cont_part += x / min(r, q)
        if self.delta_mode == "ceil":
            return ceil_part
        if self.delta_mode == "cont":
            return cont_part
        return ceil_part + cont_part / 10.0

    @staticmethod
    def _partial_carton_change(candidate: DispatchCandidate, lot: dict[str, int]) -> int:
        change = 0
        for part_id, x in candidate.matched_parts.items():
            qty = candidate.tote.get_component_quantity(part_id)
            size = lot.get(part_id, 1)
            before = 1 if qty % size else 0
            after = 1 if (qty - x) % size else 0
            change += after - before
        return change

    def _new_partial_count(self, candidate: DispatchCandidate) -> tuple[int, int]:
        """(다 비우는 부품 재고 수, 손대지 않은 재고를 일부만 남기는 부품 수)"""
        tote = candidate.tote
        if tote.tote_id not in self._initial_qty:
            initial: dict[str, int] = {}
            for comp in tote.initial_contents:
                initial.setdefault(comp.part_id, comp.quantity)
            self._initial_qty[tote.tote_id] = initial
        initial = self._initial_qty[tote.tote_id]

        emptied = 0
        new_partial = 0
        for part_id, x in candidate.matched_parts.items():
            qty = tote.get_component_quantity(part_id)
            if qty - x <= 0:
                emptied += 1
            elif qty == initial.get(part_id):
                new_partial += 1
        return emptied, new_partial

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

        speed = AGVSpec.SPEED_M_PER_S
        empty_m, tote_station_m = self._mean_distances(state)
        tau_bar = PICK_PUT_SEC + (empty_m + 2 * tote_station_m) / speed
        qbar, v_part, lot = self._stock_stats(state)
        demand = self._future_demand(state) if self.c and self.tote_mode == "usage" else {}
        self._calls += 1
        if self._old_sf is not None:
            # 기존 S_F의 미래 벌점은 결정 시점마다 갱신되는 키트 캐시를 쓴다
            self._old_sf.dispatch_count = self._calls
            self._old_sf._update_active_kits_cache(state.order_manager.get_all_kits())

        holders = self._excess_holders(state) if self.c_excess else {}

        # 키트별 남은 부품과 긴급도 (로그)
        kit_cache: dict[str, tuple[dict[str, int], float]] = {}
        sigmas: dict[str, float] = {}
        relaxed: set[str] = set()
        for candidate in candidates:
            kit = candidate.kit
            if kit.kit_id not in kit_cache:
                remaining = kit.get_remaining_parts()
                sigma = self._kit_sigma(
                    kit, remaining, now, qbar, lot, empty_m, tote_station_m, tau_bar
                )
                sigmas[kit.kit_id] = sigma
                log_u = 0.0 if self.gate is not None else -max(0.0, sigma) / self.kappa
                kit_cache[kit.kit_id] = (remaining, log_u)
                if self.c_excess and self.excess_relax is not None:
                    sigma_work = self._kit_sigma(
                        kit, remaining, now, qbar, lot, empty_m, tote_station_m, tau_bar, "work"
                    )
                    if sigma_work <= self.excess_relax:
                        relaxed.add(kit.kit_id)

        allowed: set[str] | None = None
        if self.gate is not None:
            critical = {kid for kid, s in sigmas.items() if s <= self.gate}
            if critical:
                allowed = critical

        best: tuple[float, DispatchCandidate, AGV] | None = None

        for candidate in candidates:
            kit = candidate.kit
            if allowed is not None and kit.kit_id not in allowed:
                continue
            remaining, log_u = kit_cache[kit.kit_id]

            delta = self._delta(candidate.matched_parts, remaining, qbar)
            if delta <= 0:
                log_score = -math.inf
                agv = idle_agvs[0]
            else:
                agv = min(
                    idle_agvs,
                    key=lambda a: a.position.manhattan_distance_to(candidate.tote.position),
                )
                travel = agv.position.manhattan_distance_to(
                    candidate.tote.position
                ) + 2 * candidate.tote.position.manhattan_distance_to(candidate.station.position)
                tau = PICK_PUT_SEC + travel / speed
                if self.denom_mode == "full":
                    tau += sum(
                        transfer_time(x, lot.get(p, 1)) for p, x in candidate.matched_parts.items()
                    )
                log_score = log_u + math.log(delta) - self.d * math.log(tau)

                if self.c and self.tote_mode == "usage":
                    needed_volume = sum(
                        min(comp.quantity, demand.get(comp.part_id, 0)) * (comp.v_part or 0)
                        for comp in candidate.tote.contents
                    )
                    taken_volume = sum(
                        x * v_part.get(p, 0) for p, x in candidate.matched_parts.items()
                    )
                    u = min(1.0, taken_volume / needed_volume) if needed_volume > 0 else 1.0
                    log_score += self.c * math.log1p(u)
                elif self.c and self.tote_mode == "partial":
                    log_score -= self.c * self._new_partial_count(candidate)[1]
                elif self.c and self.tote_mode == "clear":
                    emptied, new_partial = self._new_partial_count(candidate)
                    log_score += self.c * (emptied - new_partial)
                elif self.c and self.tote_mode == "carton":
                    log_score -= self.c * self._partial_carton_change(candidate, lot)
                elif self.c and self._old_sf is not None:
                    log_score += self.c * self._old_sf.calc_sf(candidate)
                elif self.c and self.tote_mode == "remain":
                    left = 0.0
                    for part_id, x in candidate.matched_parts.items():
                        rest = candidate.tote.get_component_quantity(part_id) - x
                        if rest > 0 and qbar.get(part_id):
                            left += rest / qbar[part_id]
                    log_score -= self.c * left

                if self.c_excess and kit.kit_id not in relaxed:
                    log_score -= self.c_excess * self._holder_violations(candidate, holders)

            if best is None or log_score > best[0]:
                best = (log_score, candidate, agv)

        log_score, candidate, agv = best
        if log_score == -math.inf:
            # 모든 후보의 Δ가 0이면 효율 비교가 무의미하므로 여유가 가장 적은 키트의 첫 후보를 고른다
            pool = [c for c in candidates if allowed is None or c.kit.kit_id in allowed]
            candidate = min(pool, key=lambda c: sigmas[c.kit.kit_id])
            agv = min(
                idle_agvs,
                key=lambda a: a.position.manhattan_distance_to(candidate.tote.position),
            )
        candidate = replace(candidate, score_info={"log_score": log_score})
        return candidate, agv
