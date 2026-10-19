"""정책과 무관한 인스턴스 부하 추정 (docs/1.목적함수.md '인스턴스 부하').

납기 d마다 "d까지 끝내야 하는 작업 시간 / d까지 쓸 수 있는 자원 시간"을 계산하고,
그중 최댓값을 부하로 본다. 자원은 세 가지다.

- agv     : AGV 전체 (대수 × 시간). 디스패치 1회 = 집기·내려놓기 + 이동 + 카톤 이송 대기
- slot    : 스테이션당 동시에 배정 가능한 AGV 수 (KittingStation.can_accept_agv = 2)
            디스패치 1회 = 배정부터 도킹 해제까지 (집기 + 토트·스테이션 편도 이동 + 카톤 이송)
- station : 스테이션 도킹 자리 (스테이션당 1개). 도킹 진입 + 카톤 이송 + 키트 준비(교체 + 첫 토트 도착)

키트별 디스패치 수는 부품별 추정 Σ_m ⌈필요량 / 토트당 평균 수량⌉ 이다.
하한이 아니므로 부하가 1을 넘어도 실현 불가능이 확정되지 않는다. 도킹 대기는 넣지 않는다.

같은 함수를 인스턴스 생성기(t=0)와 시뮬레이터(실시간 잔여 부하 ρ(t))가 함께 쓴다.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from config.constants import AGVSpec, KittingStationSpec

if TYPE_CHECKING:
    from simulation_engine.state import WorldStateSnapshot

DOCK_APPROACH_M = 2.0  # KittingStation.waiting_position 에서 도킹 위치까지
AGV_SLOTS_PER_STATION = 2  # KittingStation.can_accept_agv

Point = tuple[float, float]


@dataclass(frozen=True)
class ResourceSpec:
    n_agvs: int
    n_stations: int
    mean_empty_travel_m: float  # 내려놓은 위치에서 다음 토트까지
    mean_tote_station_m: float  # 토트 위치에서 스테이션까지 (편도)
    agv_slots_per_station: int = AGV_SLOTS_PER_STATION


@dataclass(frozen=True)
class KitWork:
    deadline: float
    n_dispatch: int
    transfer_sec: float
    agv_sec: float
    slot_sec: float
    station_sec: float


@dataclass(frozen=True)
class KitDemand:
    deadline: float
    remaining_parts: dict[str, int]
    needs_setup: bool  # 아직 스테이션에 배정되지 않은 키트는 교체 시간과 첫 토트 도착 시간이 든다


def _manhattan(a: Point, b: Point) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def mean_distances(
    tote_points: Iterable[Point], station_points: list[Point]
) -> tuple[float, float]:
    """(토트 간 평균 거리, 토트-스테이션 평균 거리). 토트 수로 가중한다."""
    counts = Counter(tote_points)
    total = sum(counts.values())
    if total == 0 or not station_points:
        return 0.0, 0.0
    empty = sum(
        na * nb * _manhattan(a, b) for a, na in counts.items() for b, nb in counts.items()
    ) / (total * total)
    to_station = sum(
        n * _manhattan(p, s) for p, n in counts.items() for s in station_points
    ) / (total * len(station_points))
    return empty, to_station


def mean_qty_per_tote(tote_stocks: Iterable[dict[str, int]]) -> dict[str, float]:
    """부품마다 (총 재고 / 그 부품이 들어 있는 토트 수)."""
    stock: dict[str, int] = {}
    holders: dict[str, int] = {}
    for contents in tote_stocks:
        for part_id, qty in contents.items():
            if qty <= 0:
                continue
            stock[part_id] = stock.get(part_id, 0) + qty
            holders[part_id] = holders.get(part_id, 0) + 1
    return {p: stock[p] / holders[p] for p in stock}


def transfer_time(qty: int, lot_size: int) -> float:
    full, partial = divmod(qty, lot_size)
    return (
        full * KittingStationSpec.FULL_CARTON_TRANSFER_TIME_SEC
        + (KittingStationSpec.PARTIAL_CARTON_TRANSFER_TIME_SEC if partial else 0.0)
    )


def estimate_kit_work(
    demand: KitDemand,
    qbar: dict[str, float],
    lot_sizes: dict[str, int],
    spec: ResourceSpec,
) -> KitWork:
    speed = AGVSpec.SPEED_M_PER_S
    n_dispatch = sum(
        math.ceil(qty / qbar[p]) for p, qty in demand.remaining_parts.items() if qbar.get(p)
    )
    transfer = sum(transfer_time(q, lot_sizes[p]) for p, q in demand.remaining_parts.items())

    agv_per_dispatch = (
        AGVSpec.TOTE_PICKUP_TIME_S
        + AGVSpec.TOTE_PUTDOWN_TIME_S
        + (spec.mean_empty_travel_m + 2 * spec.mean_tote_station_m) / speed
    )
    slot_per_dispatch = (
        AGVSpec.TOTE_PICKUP_TIME_S
        + (spec.mean_empty_travel_m + spec.mean_tote_station_m) / speed
    )
    setup = (
        KittingStationSpec.KIT_CHANGING_TIME_SEC + slot_per_dispatch
        if demand.needs_setup
        else 0.0
    )
    return KitWork(
        deadline=demand.deadline,
        n_dispatch=n_dispatch,
        transfer_sec=transfer,
        agv_sec=n_dispatch * agv_per_dispatch + transfer,
        slot_sec=n_dispatch * slot_per_dispatch + transfer,
        station_sec=n_dispatch * DOCK_APPROACH_M / speed + transfer + setup,
    )


def cumulative_load(works: list[KitWork], spec: ResourceSpec, now: float = 0.0) -> dict:
    """납기별 누적 부하의 최댓값. 이미 지난 납기의 작업은 이후 모든 납기에 더해진다."""
    capacity = {
        "agv": spec.n_agvs,
        "slot": spec.agv_slots_per_station * spec.n_stations,
        "station": spec.n_stations,
    }
    cum = {name: 0.0 for name in capacity}
    peak = {name: (0.0, None) for name in capacity}
    ordered = sorted(works, key=lambda w: w.deadline)

    for i, work in enumerate(ordered):
        cum["agv"] += work.agv_sec
        cum["slot"] += work.slot_sec
        cum["station"] += work.station_sec
        if i + 1 < len(ordered) and ordered[i + 1].deadline == work.deadline:
            continue
        horizon = work.deadline - now
        if horizon <= 0:
            continue
        for name, cap in capacity.items():
            value = cum[name] / (cap * horizon)
            if value > peak[name][0]:
                peak[name] = (value, work.deadline)

    if ordered and ordered[-1].deadline <= now and any(cum.values()):
        # 남은 납기가 모두 지났다: 남은 작업이 있으면 부하는 무한대
        return {"peak": math.inf, "peak_deadline": None, "bottleneck": None,
                **{name: math.inf for name in capacity}}

    bottleneck = max(peak, key=lambda name: peak[name][0])
    return {
        "peak": peak[bottleneck][0],
        "peak_deadline": peak[bottleneck][1],
        "bottleneck": bottleneck,
        **{name: peak[name][0] for name in capacity},
    }


def estimate_load(
    kits: list[KitDemand],
    tote_stocks: list[dict[str, int]],
    tote_points: list[Point],
    station_points: list[Point],
    lot_sizes: dict[str, int],
    n_agvs: int,
    now: float = 0.0,
) -> dict:
    """원자료로부터 부하를 계산한다. 재고가 있는 토트만 거리 평균에 넣는다."""
    stocked_points = [p for p, s in zip(tote_points, tote_stocks) if any(q > 0 for q in s.values())]
    empty_m, tote_station_m = mean_distances(stocked_points, station_points)
    spec = ResourceSpec(
        n_agvs=n_agvs,
        n_stations=len(station_points),
        mean_empty_travel_m=empty_m,
        mean_tote_station_m=tote_station_m,
    )
    qbar = mean_qty_per_tote(tote_stocks)
    works = [estimate_kit_work(k, qbar, lot_sizes, spec) for k in kits]
    result = cumulative_load(works, spec, now=now)
    result["n_dispatch_estimate"] = sum(w.n_dispatch for w in works)
    result["mean_empty_travel_m"] = empty_m
    result["mean_tote_station_m"] = tote_station_m
    return result


def remaining_load(state: WorldStateSnapshot, now: float) -> dict:
    """시뮬레이션 중 실시간 잔여 누적 부하 ρ(t).

    남은 키트(대기 + 진행 중)의 남은 부품과 현재 토트 재고로 다시 계산한다.
    이동 중인 토트에 예약된 부품(reserved)은 이미 처리된 것으로 본다.
    """
    kits: list[KitDemand] = []
    for kit in state.order_manager.get_all_kits():
        if kit.is_completed():
            continue
        remaining = kit.get_remaining_parts()
        if not remaining and kit.status != "waiting":
            continue
        kits.append(
            KitDemand(
                deadline=float(kit.deadline_time_sec),
                remaining_parts=remaining,
                needs_setup=kit.status == "waiting",
            )
        )

    totes = list(state.totes.values())
    lot_sizes = {
        c.part_id: c.lot_size for tote in totes for c in tote.initial_contents if c.lot_size
    }
    return estimate_load(
        kits=kits,
        tote_stocks=[tote.get_part_summary() for tote in totes],
        tote_points=[(tote.position.x, tote.position.y) for tote in totes],
        station_points=[(s.position.x, s.position.y) for s in state.stations.values()],
        lot_sizes=lot_sizes,
        n_agvs=len(state.agvs),
        now=now,
    )
