"""CPR2 기본형 + 급한 키트에 AGV를 더 붙이는 정책 (실험용).

결정마다 스테이션별 진행 중 키트의 여유 σ(남은 작업 제외, 디스패치 1회 시간 단위)를 계산해
스테이션 AGV 상한(기본 2)을 바꾼다. 도크는 그대로 1개라 3번째 AGV는 대기 위치에서 기다린다.

mode
- most_urgent  여유가 가장 작은 스테이션 하나만, 그 여유가 threshold 미만이면 상한 cap_hi
- all_below    여유가 threshold 미만인 모든 스테이션의 상한 cap_hi
- band         most_urgent와 같되, 여유가 lower 이하(이미 많이 늦어 구하기 어려운 키트)이면 올리지 않음
- no_starve    most_urgent와 같되, 진행 중 키트가 있는데 배정된 AGV가 0대인 다른 스테이션이 있으면 올리지 않음
"""

from __future__ import annotations

from config.constants import AGVSpec
from policy.cpr.new_cpr_policy import PICK_PUT_SEC, NewCPRPolicy


class CapAdaptiveCPRPolicy(NewCPRPolicy):
    def __init__(self, mode: str = "most_urgent", threshold: float = 0.0, cap_hi: int = 3,
                 lower: float = -5.0, **kwargs):
        super().__init__(**{"kappa": 32.0, "c": 0.5, "c_x": 0.0, **kwargs})
        self.mode = mode
        self.threshold = threshold
        self.lower = lower
        self.cap_hi = cap_hi
        self.cap_stats = {"calls": 0, "raised": 0}

    @property
    def name(self):
        return f"CPR2 + AGV cap ({self.mode}, {self.threshold:g})"

    def update_station_caps(self, state, now: float) -> None:
        empty_m, tote_station_m = self._layout(state)
        tau_bar = PICK_PUT_SEC + (empty_m + 2 * tote_station_m) / AGVSpec.SPEED_M_PER_S
        _, qbar, lot = self._stock_stats(state)
        sigma = {}
        for station in state.stations.values():
            station.agv_cap = 2
            kit = station.assigned_kit
            if kit is None or kit.is_completed():
                continue
            sigma[station.station_id] = self._sigma_work(
                kit.get_remaining_parts(), now, float(kit.deadline_time_sec), qbar, lot,
                empty_m, tote_station_m, tau_bar)
        self.cap_stats["calls"] += 1
        if not sigma:
            return
        if self.mode in ("most_urgent", "band", "no_starve"):
            sid = min(sigma, key=sigma.get)
            raised = [sid] if sigma[sid] < self.threshold else []
            if self.mode == "band" and raised and sigma[sid] <= self.lower:
                raised = []
            if self.mode == "no_starve" and raised and any(
                    state.stations[o].assigned_agv_count == 0 for o in sigma if o != sid):
                raised = []
        elif self.mode == "all_below":
            raised = [sid for sid, s in sigma.items() if s < self.threshold]
        else:
            raise ValueError(f"알 수 없는 상한 규칙: {self.mode}")
        for sid in raised:
            state.stations[sid].agv_cap = self.cap_hi
        self.cap_stats["raised"] += bool(raised)
