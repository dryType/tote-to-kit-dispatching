# simulation_engine/candidate_generator.py

from typing import Dict, List

from simulation_engine.entities import (
    DispatchCandidate,
    Kit,
    KittingStation,
    StationStatus,
    Tote,
    ToteStatus,
)


def generate_candidates(
    stations: List[KittingStation], totes: List[Tote]
) -> List[DispatchCandidate]:
    candidates = []

    for station in stations:
        if station.status != StationStatus.KITTING:
            continue
        if not station.can_accept_agv():
            continue
        if not station.has_active_kit():
            continue

        kit = station.assigned_kit
        if kit.get_remaining_parts() == {}:
            continue

        for tote in totes:
            if tote.status == ToteStatus.BUSY:
                continue

            matched_parts = _calculate_matched_parts(tote, kit)
            if matched_parts:
                candidate = DispatchCandidate(
                    tote=tote, station=station, kit=kit, matched_parts=matched_parts
                )
                candidates.append(candidate)

    return candidates


def _calculate_matched_parts(tote: Tote, kit: Kit) -> Dict[str, int]:
    matched_parts = {}
    remaining_parts = kit.get_remaining_parts()

    for part_id, required_qty in remaining_parts.items():
        available_qty = tote.get_component_quantity(part_id)
        if available_qty > 0:
            matched_qty = min(available_qty, required_qty)
            matched_parts[part_id] = matched_qty

    return matched_parts
