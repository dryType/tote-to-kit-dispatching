from typing import Optional

import simpy

from config.constants import AGVSpec, KittingStationSpec
from simulation_engine import dispatcher
from simulation_engine.entities import (
    AGV,
    DispatchCandidate,
    KittingStation,
    Position,
)
from simulation_engine.metrics import Metrics


def _calc_agv_travel_time(p1: Position, p2: Position) -> float:
    dist = abs(p2.x - p1.x) + abs(p2.y - p1.y)  # Manhattan distance
    return dist / AGVSpec.SPEED_M_PER_S


def agv_transport_process(
    env: simpy.Environment,
    agv: AGV,
    candidate: DispatchCandidate,
    dispatcher: dispatcher.Dispatcher,
    metrics: Optional[Metrics],
):

    # agv가 작업 할당받아 storage_bin으로 이동 시작
    yield env.timeout(_calc_agv_travel_time(agv.position, candidate.tote.position))

    # agv storage_bin 도착
    agv.update_position(candidate.tote.position)

    # tote pickup 시작
    yield env.timeout(AGVSpec.TOTE_PICKUP_TIME_S)
    agv.load_tote(candidate.tote)

    # tote pickup 완료. kitting stationd으로 이동 시작
    agv.head_to_station()
    yield env.timeout(
        _calc_agv_travel_time(agv.position, candidate.station.waiting_position)
    )
    # waiting position 도착 docking position이 비어있는지 확인
    agv.start_waiting()
    dock_request = candidate.station.dock.request()
    yield dock_request

    # agv docking position으로 이동
    yield env.timeout(_calc_agv_travel_time(agv.position, candidate.station.position))

    # agv docking position 도착 & kitting 작업 대기
    agv.start_docking()
    yield from kitting_process(env, agv, candidate, dispatcher, metrics)

    # kitting 작업 완료. storage_bin으로 복귀
    candidate.station.decrement_agv_count()
    candidate.station.dock.release(dock_request)

    agv.return_to_storage()
    yield env.timeout(_calc_agv_travel_time(agv.position, agv.target_storage_position))
    yield env.timeout(AGVSpec.TOTE_PUTDOWN_TIME_S)

    agv.unload_tote()
    agv.update_position(agv.target_storage_position)
    agv.finish_task()

    dispatcher.notify()


def kitting_process(
    env: simpy.Environment,
    agv: AGV,
    candidate: DispatchCandidate,
    dispatcher: dispatcher.Dispatcher,
    metrics: Optional[Metrics],
):
    total_transfer_time = 0
    for part_id, qty in candidate.matched_parts.items():
        comp = next((c for c in candidate.tote.contents if c.part_id == part_id), None)
        lot_size = comp.lot_size if comp else 1
        full_carton_count = qty // lot_size
        partial_carton_count = 1 if qty % lot_size > 0 else 0
        total_transfer_time += (
            full_carton_count * KittingStationSpec.FULL_CARTON_TRANSFER_TIME_SEC
            + partial_carton_count * KittingStationSpec.PARTIAL_CARTON_TRANSFER_TIME_SEC
        )

    yield env.timeout(total_transfer_time)

    for part_id, qty in candidate.matched_parts.items():
        candidate.kit.confirm_reserved_parts(part_id, qty)
        candidate.tote.pick_part(part_id, qty)

    if candidate.kit.is_completed():
        candidate.station.complete_kit()
        candidate.kit.complete_kit(env.now)
        env.process(
            kit_replacement_process(env, candidate.station, dispatcher, metrics)
        )

    dispatcher.notify()


def kit_replacement_process(
    env: simpy.Environment,
    station: KittingStation,
    dispatcher: dispatcher.Dispatcher,
    metrics: Optional[Metrics],
):
    new_kit = station.order_manager.pop_next_kit()
    if new_kit is None:
        if station.order_manager.is_all_completed():
            print(f"All kits completed at t={env.now}.")
        return

    yield env.timeout(KittingStationSpec.KIT_CHANGING_TIME_SEC)
    station.assign_kit(new_kit)
    dispatcher.notify()
