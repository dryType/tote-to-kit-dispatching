"""새 CPR 정책 (ATC형 곱 구조 + 미래 궁합 + 초과분 보관 토트).

점수(j, k) = U_k × V_jk × F_jk × H_jk   (계산은 로그 공간에서)

- U_k  긴급도      exp(-max(0, σ_k) / κ),  σ_k = (납기 - 현재) / τ̄
                   τ̄ = 디스패치 1회 평균 AGV 시간 (집기·내려놓기 + 빈 이동 + 토트-스테이션 왕복)
- V_jk 효율        Σ_m x_m / min(r_m, q̄_m)  ÷  [집기·내려놓기 + (AGV→토트 + 2 × 토트→스테이션) / 속도]
                   x_m: 이번에 꺼내는 수량, r_m: 키트의 남은 수량, q̄_m: 부품 m의 토트당 평균 재고
- F_jk 미래 궁합   exp(c × max(0, 비우기 보너스 - 미래 벌점))   (기존 CPR S_F의 w_s2 부분)
                   비우기 보너스 = (0.5 × 다 비우는 부품 수 + 남은 필요량과 같은 부품 수) / 토트의 부품 수
                   미래 벌점    = max(0, 다른 키트가 비울 수 있는 부품 비율의 최댓값 - 이번에 비우는 부품 비율)
- H_jk 초과분 보관 exp(-c_x × 보관 토트 위반 수)
                   초과분 E_m = 총재고 - 예약 수량 - 남은 키트 전체 필요량 (실행 중 변하지 않음)
                   부품마다 보관 토트를 하나 지정하고, 보관 토트에서 E_m 아래로 꺼내면 위반 1

옵션 (업데이트 비교용)
- holder_rule  "fit": 초과분을 담을 수 있는 토트 → 이미 다른 부품의 보관 토트 → 재고가 E_m에 가장 가까운 토트
               "far": 위와 같되, 재고 근접도 대신 스테이션에서 먼 토트를 우선 (가까운 토트를 쓰게 두려는 의도)
- holder_sticky  이전 결정의 보관 토트가 아직 E_m 이상을 갖고 있으면 그대로 유지
- relax_sigma  남은 작업을 뺀 여유(디스패치 단위)가 이 값 이하인 키트는 보관 토트 벌점 면제
- relax_rho    실시간 잔여 누적 부하 ρ(t)가 이 값을 넘으면 보관 토트 벌점을 끔
- rho_lo, rho_hi  보관 토트 벌점을 ρ(t)에 따라 연속으로 줄인다:
               c_x × clip((rho_hi - ρ) / (rho_hi - rho_lo), 0, 1)  (ρ ≤ rho_lo이면 c_x 전부, ρ ≥ rho_hi이면 0)
- future_kits  미래 벌점을 계산할 때 볼 대기 키트 수 (None이면 남은 키트 전부, 진행 중 키트는 항상 포함)
- fit_sigma    남은 작업을 뺀 여유(디스패치 단위)가 이 값 이하인 키트는 미래 궁합 항을 쓰지 않음
- d            효율 분모(AGV 시간)의 지수. 1보다 크면 가까운 토트를 더 선호한다
- urgency_mode 키트 긴급도 u_k(0~1)가 그 키트의 토트 선택 기준을 바꾼다 (기존 CPR 긴급도 곡선 차용)
               "time": 여유 = 납기 − 현재,  "work": 여유 = 납기 − 현재 − 남은 작업 예상 시간
               x = urgency_margin − 여유 (초),  u = (1 − exp(−λ·x))^p (x > 0), 0 (x ≤ 0)
               log 점수 = … − (1 − α·u)·d·log(AGV 시간) + (1 − u)·c·F − (1 − u)·c_x·위반
               급할수록 미래 궁합·잔량 항이 꺼지고 거리 비중이 α만큼 줄어 진행(해결량) 중심이 된다
"""

from __future__ import annotations

import math
from dataclasses import replace

from config.constants import AGVSpec
from policy.base_policy import BasePolicy
from simulation_engine.entities import AGV, DispatchCandidate, KitStatus, ToteStatus
from simulation_engine.load_estimator import (
    AGV_SLOTS_PER_STATION,
    DOCK_APPROACH_M,
    mean_distances,
    remaining_load,
    transfer_time,
)
from simulation_engine.state import WorldStateSnapshot

PICK_PUT_SEC = AGVSpec.TOTE_PICKUP_TIME_S + AGVSpec.TOTE_PUTDOWN_TIME_S


class NewCPRPolicy(BasePolicy):
    def __init__(
        self,
        kappa: float = 32.0,
        c: float = 1.0,
        c_x: float = 0.0,
        holder_rule: str = "fit",
        holder_sticky: bool = False,
        relax_sigma: float | None = None,
        relax_rho: float | None = None,
        future_kits: int | None = None,
        rho_lo: float | None = None,
        rho_hi: float | None = None,
        fit_sigma: float | None = None,
        d: float = 1.0,
        urgency_mode: str | None = None,
        urgency_margin: float = 1200.0,
        alpha: float = 0.0,
        urgency_lambda: float = 0.006,
        urgency_p: float = 2.0,
    ):
        self.kappa = kappa
        self.c = c
        self.c_x = c_x
        self.holder_rule = holder_rule
        self.holder_sticky = holder_sticky
        self.relax_sigma = relax_sigma
        self.relax_rho = relax_rho
        self.future_kits = future_kits
        self.rho_lo = rho_lo
        self.rho_hi = rho_hi
        self.fit_sigma = fit_sigma
        self.d = d
        self.urgency_mode = urgency_mode
        self.urgency_margin = urgency_margin
        self.alpha = alpha
        self.urgency_lambda = urgency_lambda
        self.urgency_p = urgency_p
        # 진단용: 결정 수, 긴급 모드(u > 0.5) 키트가 있었던 결정 수, u를 무시했을 때와 선택이 달라진 결정 수
        self.stats = {"decisions": 0, "urgent": 0, "changed": 0}
        self._distances: tuple[float, float] | None = None
        self._station_distance: dict[str, float] = {}
        self._holders: dict[str, str] = {}

    @property
    def name(self):
        return "New CPR Policy"

    # ------------------------------------------------------------------
    # 결정 시점마다 한 번 계산하는 값
    # ------------------------------------------------------------------

    def _layout(self, state: WorldStateSnapshot) -> tuple[float, float]:
        # 토트·스테이션 위치는 바뀌지 않으므로 처음 한 번만 계산한다
        if self._distances is None:
            stations = [s.position for s in state.stations.values()]
            self._distances = mean_distances(
                [(t.position.x, t.position.y) for t in state.totes.values()],
                [(p.x, p.y) for p in stations],
            )
            self._station_distance = {
                t.tote_id: sum(t.position.manhattan_distance_to(p) for p in stations) / len(stations)
                for t in state.totes.values()
            }
        return self._distances

    @staticmethod
    def _stock_stats(state: WorldStateSnapshot):
        stock: dict[str, int] = {}
        holders: dict[str, int] = {}
        lot: dict[str, int] = {}
        for tote in state.totes.values():
            for comp in tote.contents:
                if comp.quantity <= 0:
                    continue
                stock[comp.part_id] = stock.get(comp.part_id, 0) + comp.quantity
                holders[comp.part_id] = holders.get(comp.part_id, 0) + 1
                lot[comp.part_id] = comp.lot_size or 1
        return stock, {p: stock[p] / holders[p] for p in stock}, lot

    def _future_kit_remaining(self, state: WorldStateSnapshot) -> list[dict[str, int]]:
        """미래 벌점에 쓸 키트들의 남은 부품 (진행 중 키트 + 납기 순 대기 키트)."""
        om = state.order_manager
        active = [k for k in om.activated_kits if not k.is_completed()]
        pending = list(om.pending_kits)
        if self.future_kits is not None:
            pending = sorted(pending, key=lambda k: k.deadline_time_sec)[: self.future_kits]
        return [k.get_remaining_parts() for k in pending + active]

    def _excess(self, state: WorldStateSnapshot, stock: dict[str, int]) -> dict[str, int]:
        demand: dict[str, int] = {}
        reserved: dict[str, int] = {}
        for kit in state.order_manager.get_all_kits():
            if kit.is_completed():
                continue
            for part_id, qty in kit.get_remaining_parts().items():
                demand[part_id] = demand.get(part_id, 0) + qty
            for part_id, qty in kit.reserved_parts.items():
                reserved[part_id] = reserved.get(part_id, 0) + qty
        excess = {}
        for part_id, qty in stock.items():
            e = qty - reserved.get(part_id, 0) - demand.get(part_id, 0)
            if e > 0:
                excess[part_id] = e
        return excess

    def _assign_holders(self, state: WorldStateSnapshot, excess: dict[str, int]) -> dict[str, tuple[str, int]]:
        options: dict[str, list[tuple[str, int]]] = {}
        current: dict[str, dict[str, int]] = {}
        for tote in state.totes.values():
            summary = tote.get_part_summary()
            current[tote.tote_id] = summary
            if tote.status == ToteStatus.BUSY:
                continue
            for part_id, qty in summary.items():
                if part_id in excess and qty > 0:
                    options.setdefault(part_id, []).append((tote.tote_id, qty))

        holders: dict[str, tuple[str, int]] = {}
        hosting: dict[str, int] = {}
        for part_id in sorted(excess, key=lambda p: (-excess[p], p)):
            e = excess[part_id]
            previous = self._holders.get(part_id)
            if self.holder_sticky and previous and current.get(previous, {}).get(part_id, 0) >= e:
                tote_id = previous
            elif options.get(part_id):
                if self.holder_rule == "far":
                    key = lambda o: (o[1] < e, -hosting.get(o[0], 0),
                                     -self._station_distance.get(o[0], 0.0), abs(o[1] - e), o[0])
                else:
                    key = lambda o: (o[1] < e, -hosting.get(o[0], 0), abs(o[1] - e), o[0])
                tote_id = min(options[part_id], key=key)[0]
            else:
                continue
            holders[part_id] = (tote_id, e)
            hosting[tote_id] = hosting.get(tote_id, 0) + 1
        self._holders = {p: h[0] for p, h in holders.items()}
        return holders

    def _sigma_work(self, remaining, now, deadline, qbar, lot, empty_m, tote_station_m, tau_bar):
        speed = AGVSpec.SPEED_M_PER_S
        n_hat = sum(math.ceil(q / qbar[p]) for p, q in remaining.items() if qbar.get(p))
        transfer = sum(transfer_time(q, lot.get(p, 1)) for p, q in remaining.items())
        slot = AGVSpec.TOTE_PICKUP_TIME_S + (empty_m + tote_station_m) / speed
        work = max((n_hat * slot + transfer) / AGV_SLOTS_PER_STATION,
                   n_hat * DOCK_APPROACH_M / speed + transfer)
        return (deadline - now - work) / tau_bar

    # ------------------------------------------------------------------
    # 후보별 점수
    # ------------------------------------------------------------------

    @staticmethod
    def _future_fit(candidate: DispatchCandidate, remaining: dict[str, int],
                    future: list[dict[str, int]], cache: dict[str, float]) -> float:
        tote = candidate.tote
        n = len(tote.contents)
        if n == 0 or not candidate.matched_parts:
            return 0.0
        emptied = 0
        perfect = 0
        for comp in tote.contents:
            x = candidate.matched_parts.get(comp.part_id, 0)
            if x <= 0:
                continue
            if comp.quantity - x <= 0:
                emptied += 1
                if comp.quantity == remaining[comp.part_id]:
                    perfect += 1
        bonus = (0.5 * emptied + perfect) / n

        if tote.tote_id not in cache:
            best = 0
            for kit_remaining in future:
                count = sum(1 for comp in tote.contents
                            if kit_remaining.get(comp.part_id, 0) >= comp.quantity)
                if count > best:
                    best = count
                    if best == n:
                        break
            cache[tote.tote_id] = best / n
        penalty = max(0.0, cache[tote.tote_id] - emptied / n)
        return max(0.0, bonus - penalty)

    @staticmethod
    def _violations(candidate: DispatchCandidate, holders: dict[str, tuple[str, int]]) -> int:
        count = 0
        for part_id, x in candidate.matched_parts.items():
            holder = holders.get(part_id)
            if holder is None or holder[0] != candidate.tote.tote_id:
                continue
            if candidate.tote.get_component_quantity(part_id) - x < holder[1]:
                count += 1
        return count

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
        empty_m, tote_station_m = self._layout(state)
        tau_bar = PICK_PUT_SEC + (empty_m + 2 * tote_station_m) / speed
        stock, qbar, lot = self._stock_stats(state)
        future = self._future_kit_remaining(state) if self.c else []

        holders: dict[str, tuple[str, int]] = {}
        c_x = self.c_x
        if c_x and (self.relax_rho is not None or self.rho_hi is not None):
            rho = remaining_load(state, now)["peak"]
            if self.relax_rho is not None and rho > self.relax_rho:
                c_x = 0.0
            if c_x and self.rho_lo is not None and self.rho_hi is not None:
                scale = (self.rho_hi - rho) / (self.rho_hi - self.rho_lo)
                c_x *= min(1.0, max(0.0, scale))
        excess_on = bool(c_x)
        if excess_on:
            holders = self._assign_holders(state, self._excess(state, stock))

        kits: dict[str, tuple[dict[str, int], float, bool, bool, float]] = {}
        for candidate in candidates:
            kit = candidate.kit
            if kit.kit_id in kits:
                continue
            remaining = kit.get_remaining_parts()
            deadline = float(kit.deadline_time_sec)
            log_u = -max(0.0, (deadline - now) / tau_bar) / self.kappa
            relaxed = False
            fit_on = bool(self.c)
            need_relax = excess_on and self.relax_sigma is not None
            sigma = None
            if need_relax or (fit_on and self.fit_sigma is not None) or self.urgency_mode == "work":
                sigma = self._sigma_work(remaining, now, deadline, qbar, lot,
                                         empty_m, tote_station_m, tau_bar)
                relaxed = need_relax and sigma <= self.relax_sigma
                if self.fit_sigma is not None:
                    fit_on = fit_on and sigma > self.fit_sigma
            urg = 0.0
            if self.urgency_mode is not None:
                slack_sec = deadline - now if self.urgency_mode == "time" else sigma * tau_bar
                x = self.urgency_margin - slack_sec
                if x > 0:
                    urg = (1.0 - math.exp(-self.urgency_lambda * x)) ** self.urgency_p
            kits[kit.kit_id] = (remaining, log_u, relaxed, fit_on, urg)

        fit_cache: dict[str, float] = {}
        best: tuple[float, DispatchCandidate, AGV] | None = None
        plain_best: tuple[float, DispatchCandidate] | None = None  # u를 무시한 점수의 최선 (진단용)
        for candidate in candidates:
            remaining, log_u, relaxed, fit_on, urg = kits[candidate.kit.kit_id]
            delta = 0.0
            for part_id, x in candidate.matched_parts.items():
                r = remaining.get(part_id, 0)
                q = qbar.get(part_id)
                if r > 0 and q:
                    delta += x / min(r, q)
            if delta <= 0:
                continue

            agv = min(idle_agvs, key=lambda a: a.position.manhattan_distance_to(candidate.tote.position))
            travel = agv.position.manhattan_distance_to(candidate.tote.position) + \
                2 * candidate.tote.position.manhattan_distance_to(candidate.station.position)
            log_time = math.log(PICK_PUT_SEC + travel / speed)
            fit_term = self.c * self._future_fit(candidate, remaining, future, fit_cache) if fit_on else 0.0
            hold_term = c_x * self._violations(candidate, holders) if holders and not relaxed else 0.0
            log_score = (log_u + math.log(delta) - (1.0 - self.alpha * urg) * self.d * log_time
                         + (1.0 - urg) * (fit_term - hold_term))

            if best is None or log_score > best[0]:
                best = (log_score, candidate, agv)
            if self.urgency_mode is not None:
                plain = log_u + math.log(delta) - self.d * log_time + fit_term - hold_term
                if plain_best is None or plain > plain_best[0]:
                    plain_best = (plain, candidate)

        if best is None:
            return None, None
        if self.urgency_mode is not None:
            self.stats["decisions"] += 1
            self.stats["urgent"] += any(v[4] > 0.5 for v in kits.values())
            self.stats["changed"] += plain_best[1] is not best[1]
        log_score, candidate, agv = best
        return replace(candidate, score_info={"log_score": log_score}), agv
