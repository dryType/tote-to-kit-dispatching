"""매 디스패치 결정마다 현재 상황을 보고 가중치를 다시 정하는 새 CPR (실험용).

결정 직전에 상태에서 신호를 계산하고, 규칙으로 κ, c, c_x, d를 정한 뒤 NewCPRPolicy로 점수를 매긴다.
규칙이 아무것도 바꾸지 않으면 기본값(κ32, c0.5, c_x 0, d 1 = ATC형 재튜닝)과 같다.

신호
- sigma_min  진행 중 키트의 최소 여유 (남은 작업 제외, 디스패치 1회 시간 단위)
- late       진행 중 키트 중 이미 납기를 넘긴 키트가 있는가
- starved    진행 중 키트가 있는데 배정된 AGV가 하나도 없는 스테이션 수 (AGV 부족 신호)
- remain     끝나지 않은 키트 비율

규칙 (rule: 파라미터)
- fit_by_slack (lo, hi)        σ_min < lo → c = 0, σ_min > hi → c = 1, 그 사이는 기본값
- dist_by_starve (d_hi, n)     starved ≥ n → d = d_hi
- urgent_mode (th)             late 또는 σ_min < th → κ = 2, c = 0
- holder_by_slack (th, cx)     σ_min > th → c_x = cx
- holder_endgame (frac, cx)    remain ≤ frac 이고 σ_min > 10 → c_x = cx
- combined (tight, loose, cx)  σ_min < tight → κ = 2, c = 0 / σ_min > loose → c = 1, c_x = cx / starved ≥ 1 → d = 1.5
- smooth (s_c, s_x, cx)        c = clip(σ_min / s_c, 0, 1), c_x = cx × clip((σ_min − s_x) / s_x, 0, 1)
"""

from __future__ import annotations

import math

from config.constants import AGVSpec
from policy.cpr.new_cpr_policy import PICK_PUT_SEC, NewCPRPolicy
from simulation_engine.state import WorldStateSnapshot

BASE = {"kappa": 32.0, "c": 0.5, "c_x": 0.0, "d": 1.0}


def _clip01(x: float) -> float:
    return min(1.0, max(0.0, x))


class AdaptiveCPRPolicy(NewCPRPolicy):
    def __init__(self, rule: str, params: tuple = ()):
        super().__init__(**BASE)
        self.rule = rule
        self.params = tuple(params)
        self.trace: dict[str, int] = {}  # 규칙이 기본값을 바꾼 결정 수 (분석용)

    @property
    def name(self):
        return f"Adaptive CPR ({self.rule})"

    def _signals(self, state: WorldStateSnapshot, now: float) -> dict[str, float]:
        empty_m, tote_station_m = self._layout(state)
        tau_bar = PICK_PUT_SEC + (empty_m + 2 * tote_station_m) / AGVSpec.SPEED_M_PER_S
        _, qbar, lot = self._stock_stats(state)
        sigma_min = math.inf
        late = False
        starved = 0
        for station in state.stations.values():
            kit = station.assigned_kit
            if kit is None or kit.is_completed():
                continue
            deadline = float(kit.deadline_time_sec)
            late = late or deadline < now
            sigma = self._sigma_work(kit.get_remaining_parts(), now, deadline, qbar, lot,
                                     empty_m, tote_station_m, tau_bar)
            sigma_min = min(sigma_min, sigma)
            if station.assigned_agv_count == 0:
                starved += 1
        kits = state.order_manager.get_all_kits()
        remain = sum(1 for k in kits if not k.is_completed()) / max(1, len(kits))
        return {"sigma_min": sigma_min, "late": late, "starved": starved, "remain": remain}

    def _weights(self, s: dict[str, float]) -> dict[str, float]:
        w = dict(BASE)
        p = self.params
        sig = s["sigma_min"]
        if self.rule == "fit_by_slack":
            lo, hi = p
            if sig < lo:
                w["c"] = 0.0
            elif sig > hi:
                w["c"] = 1.0
        elif self.rule == "dist_by_starve":
            d_hi, n = p
            if s["starved"] >= n:
                w["d"] = d_hi
        elif self.rule == "urgent_mode":
            (th,) = p
            if s["late"] or sig < th:
                w["kappa"], w["c"] = 2.0, 0.0
        elif self.rule == "holder_by_slack":
            th, cx = p
            if sig > th:
                w["c_x"] = cx
        elif self.rule == "holder_endgame":
            frac, cx = p
            if s["remain"] <= frac and sig > 10:
                w["c_x"] = cx
        elif self.rule == "combined":
            tight, loose, cx = p
            if s["late"] or sig < tight:
                w["kappa"], w["c"] = 2.0, 0.0
            elif sig > loose:
                w["c"], w["c_x"] = 1.0, cx
            if s["starved"] >= 1:
                w["d"] = 1.5
        elif self.rule == "smooth":
            s_c, s_x, cx = p
            if math.isfinite(sig):
                w["c"] = _clip01(sig / s_c)
                w["c_x"] = cx * _clip01((sig - s_x) / s_x)
        elif self.rule != "none":
            raise ValueError(f"알 수 없는 규칙: {self.rule}")
        return w

    def select(self, now, candidates, idle_agvs, state, dispatched_count=0):
        if candidates and idle_agvs and self.rule != "none":
            w = self._weights(self._signals(state, now))
            self.kappa, self.c, self.c_x, self.d = w["kappa"], w["c"], w["c_x"], w["d"]
            changed = ",".join(k for k in BASE if w[k] != BASE[k]) or "base"
            self.trace[changed] = self.trace.get(changed, 0) + 1
        return super().select(now, candidates, idle_agvs, state, dispatched_count)
