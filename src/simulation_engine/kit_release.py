"""스테이션이 비었을 때 다음에 걸 키트를 고르는 규칙 (실험용).

기본(규칙 없음)은 납기 순(EDD)이다. 키트 처리 시간 p는 부하 추정과 같은 방식으로 계산한다:
p = max(AGV 슬롯 시간 / 스테이션당 AGV 수, 스테이션 시간)  (키트 교체 포함)

mode
- edd          납기 순 (기본과 같음, 확인용)
- edd_lpt      납기 순, 같은 납기 안에서는 처리 시간이 긴 키트 먼저
- edd_spt      납기 순, 같은 납기 안에서는 처리 시간이 짧은 키트 먼저
- slack        (납기 − 처리 시간)이 작은 키트 먼저
- atc          (1/p)·exp(−max(0, 납기 − p − 현재)/(κ·p̄)) 가 큰 키트 먼저
- compat_max   납기 순 앞쪽 window개 중 여유가 slack_min초보다 큰 키트들에서, 진행 중 키트와
               겹치는 부품 종류 비율이 가장 큰 키트. 맨 앞 키트의 여유가 slack_min 이하이면 납기 순
- compat_min   위와 같되 겹치는 비율이 가장 작은 키트
"""

from __future__ import annotations

import math
from typing import Any

from simulation_engine.load_estimator import (
    AGV_SLOTS_PER_STATION,
    KitDemand,
    ResourceSpec,
    estimate_kit_work,
    mean_distances,
    mean_qty_per_tote,
)


class KitReleaseRule:
    def __init__(self, mode: str, durations: dict[str, float], kappa: float = 2.0,
                 window: int = 3, slack_min: float = 1200.0):
        self.mode = mode
        self.durations = durations
        self.p_bar = sum(durations.values()) / max(1, len(durations))
        self.kappa = kappa
        self.window = window
        self.slack_min = slack_min

    def __call__(self, pending, activated, now: float):
        p = self.durations
        if self.mode == "edd":
            return min(pending, key=lambda k: k.deadline_time_sec)
        if self.mode == "edd_lpt":
            return min(pending, key=lambda k: (k.deadline_time_sec, -p[k.kit_id]))
        if self.mode == "edd_spt":
            return min(pending, key=lambda k: (k.deadline_time_sec, p[k.kit_id]))
        if self.mode == "slack":
            return min(pending, key=lambda k: k.deadline_time_sec - p[k.kit_id])
        if self.mode == "atc":
            def prio(k):
                pk = max(p[k.kit_id], 1.0)
                return math.exp(-max(0.0, k.deadline_time_sec - pk - now) / (self.kappa * self.p_bar)) / pk
            return max(pending, key=prio)
        if self.mode in ("compat_max", "compat_min"):
            edd = sorted(pending, key=lambda k: k.deadline_time_sec)
            head = edd[0]
            if head.deadline_time_sec - now - p[head.kit_id] <= self.slack_min:
                return head
            active_parts = set()
            for kit in activated:
                if not kit.is_completed():
                    active_parts.update(kit.get_remaining_parts())
            pool = [k for k in edd[: self.window]
                    if k.deadline_time_sec - now - p[k.kit_id] > self.slack_min]
            sign = 1 if self.mode == "compat_max" else -1

            def overlap(k):
                parts = set(k.required_parts)
                return len(parts & active_parts) / max(1, len(parts))
            # 같은 값이면 납기 순(앞쪽)을 고른다
            return max(pool, key=lambda k: (sign * overlap(k), -edd.index(k)))
        raise ValueError(f"알 수 없는 투입 규칙: {self.mode}")


def kit_durations(data: dict[str, Any]) -> dict[str, float]:
    """인스턴스 원자료로 키트별 처리 시간(초)을 추정한다."""
    layout = data["layout"]
    totes = data["totes"]
    stocks = [{c["part_id"]: c["quantity"] for c in t["contents"]} for t in totes]
    points = [(float(t["position_x"]), float(t["position_y"])) for t in totes]
    stations = [(float(s["position_x"]), float(s["position_y"])) for s in layout["kitting_stations"]]
    empty_m, tote_station_m = mean_distances(points, stations)
    spec = ResourceSpec(n_agvs=len(data.get("agvs") or []) or 9, n_stations=len(stations),
                        mean_empty_travel_m=empty_m, mean_tote_station_m=tote_station_m)
    qbar = mean_qty_per_tote(stocks)
    lots = {p: v["lot_size"] for p, v in data["bom"]["parts"].items()}
    out = {}
    for kit in data["kits"]:
        w = estimate_kit_work(KitDemand(float(kit["deadline_time_sec"]), dict(kit["required_parts"]), True),
                              qbar, lots, spec)
        out[kit["kit_id"]] = max(w.slot_sec / AGV_SLOTS_PER_STATION, w.station_sec)
    return out


def make_release_rule(data: dict[str, Any], mode: str, **params) -> KitReleaseRule:
    return KitReleaseRule(mode, kit_durations(data), **params)
