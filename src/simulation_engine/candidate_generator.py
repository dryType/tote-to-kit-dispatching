from simulation_engine.entities import (
    DispatchCandidate,
    KittingStation,
    StationStatus,
    Tote,
    ToteStatus,
)


def generate_candidates(
    stations: list[KittingStation], totes: list[Tote]
) -> list[DispatchCandidate]:
    candidates = []
    # 후보를 만드는 동안 토트/키트 상태는 바뀌지 않으므로 재고와 남은 수량을 한 번만 계산한다
    available_stocks: list[tuple[Tote, dict[str, int]]] | None = None

    for station in stations:
        if station.status != StationStatus.KITTING:
            continue
        if not station.can_accept_agv():
            continue
        if not station.has_active_kit():
            continue

        kit = station.assigned_kit
        remaining_parts = kit.get_remaining_parts()
        if remaining_parts == {}:
            continue

        if available_stocks is None:
            available_stocks = [
                (tote, _stock_of(tote))
                for tote in totes
                if tote.status != ToteStatus.BUSY
            ]

        for tote, stock in available_stocks:
            matched_parts = _calculate_matched_parts(stock, remaining_parts)
            if matched_parts:
                candidate = DispatchCandidate(
                    tote=tote, station=station, kit=kit, matched_parts=matched_parts
                )
                candidates.append(candidate)

    return candidates


def _stock_of(tote: Tote) -> dict[str, int]:
    # Tote.get_component_quantity 와 같게, 같은 부품이 여러 번 있으면 첫 번째 수량을 쓴다
    stock: dict[str, int] = {}
    for component in tote.contents:
        stock.setdefault(component.part_id, component.quantity)
    return stock


def _calculate_matched_parts(
    stock: dict[str, int], remaining_parts: dict[str, int]
) -> dict[str, int]:
    matched_parts = {}

    for part_id, required_qty in remaining_parts.items():
        available_qty = stock.get(part_id, 0)
        if available_qty > 0:
            matched_qty = min(available_qty, required_qty)
            matched_parts[part_id] = matched_qty

    return matched_parts
