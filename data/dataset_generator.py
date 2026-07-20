"""Generate tote and kit JSON files from the selected scenario inputs.

The generator reads the active files referenced by ``scenario_custom.py`` and
converts them into two simulation-facing JSON payloads:

- ``totes.json``: warehouse tote inventory, location, and packaging metadata
- ``kits.json``: kit requests derived from the production plan and BOM

Assumptions used by this generator:

- Each production-plan row represents one kit request.
- The BOM defines the per-product part demand for that request.
- ``PART_MARGIN`` is applied as a safety stock multiplier when building totes.
- Tote storage locations are assigned round-robin from ``layout.json``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

BASE_DIR = Path(__file__).resolve().parent
SCENARIO_MODULE_NAME = "scenario_custom"
SCENARIO_PATH = BASE_DIR / f"{SCENARIO_MODULE_NAME}.py"
TOTE_VOLUME_RATIO = 0.8
TOTE_WIDTH_CM = 60
TOTE_DEPTH_CM = 40
TOTE_HEIGHT_CM = 30
TOTE_VOLUME_CM3 = int(
    TOTE_WIDTH_CM * TOTE_DEPTH_CM * TOTE_HEIGHT_CM * TOTE_VOLUME_RATIO
)


@dataclass(frozen=True)
class ScenarioPaths:
    layout_path: Path
    agv_config_path: Path
    bom_path: Path
    prod_plan_path: Path
    part_margin: float
    tote_single_part_ratio: float
    tote_mixed_part_ratio: float
    tote_residual_ratio: float


def load_scenario_module() -> Any:
    """Load ``scenario_custom.py`` without relying on package imports."""

    scenario_path = str(SCENARIO_PATH.resolve())
    spec = importlib.util.spec_from_file_location(SCENARIO_MODULE_NAME, scenario_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load scenario module from {scenario_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, ensure_ascii=False, indent=2)


def build_paths(module: Any) -> ScenarioPaths:
    return ScenarioPaths(
        layout_path=Path(module.LAYOUT_PATH),
        agv_config_path=Path(module.AGV_CONFIG_PATH),
        bom_path=Path(module.BOM_PATH),
        prod_plan_path=Path(module.PROD_PLAN_PATH),
        part_margin=float(module.PART_MARGIN),
        tote_single_part_ratio=float(module.TOTE_SINGLE_PART_RATIO),
        tote_mixed_part_ratio=float(module.TOTE_MIXED_PART_RATIO),
        tote_residual_ratio=float(module.TOTE_RESIDUAL_RATIO),
    )


def validate_inputs(paths: ScenarioPaths) -> None:
    for label, path in (
        ("Layout", paths.layout_path),
        ("AGV config", paths.agv_config_path),
        ("BOM", paths.bom_path),
        ("Production plan", paths.prod_plan_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    ratio_sum = (
        paths.tote_single_part_ratio
        + paths.tote_mixed_part_ratio
        + paths.tote_residual_ratio
    )
    if not math.isclose(ratio_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("Tote ratios must sum to 1.0")


def ceil_to_lot(quantity: int, lot_size: int) -> int:
    if quantity <= 0:
        return 0
    return int(math.ceil(quantity / lot_size) * lot_size)


def compute_total_part_demand(
    bom_data: Dict[str, Any], prod_plan_data: List[Dict[str, Any]]
) -> Dict[str, int]:
    products = bom_data.get("products", {})
    demand: Dict[str, int] = {part_id: 0 for part_id in bom_data.get("parts", {})}

    for request in prod_plan_data:
        product_id = request["product"]
        quantity = int(request["qty"])
        required_parts = products[product_id]["required_parts"]
        for part_id, per_product_qty in required_parts.items():
            demand[part_id] = demand.get(part_id, 0) + int(per_product_qty) * quantity

    return demand


def split_stock_by_ratio(
    quantity: int, single_ratio: float, mixed_ratio: float, residual_ratio: float
) -> Tuple[int, int, int]:
    if quantity <= 0:
        return 0, 0, 0

    single_qty = int(math.floor(quantity * single_ratio))
    mixed_qty = int(math.floor(quantity * mixed_ratio))
    residual_qty = quantity - single_qty - mixed_qty

    if residual_qty < 0:
        mixed_qty = max(0, mixed_qty + residual_qty)
        residual_qty = quantity - single_qty - mixed_qty

    return single_qty, mixed_qty, residual_qty


def assign_storage_location(index: int, layout_data: Dict[str, Any]) -> Dict[str, Any]:
    locations = layout_data.get("storage_locations", [])
    if not locations:
        return {
            "location_id": None,
            "position_x": None,
            "position_y": None,
        }

    location = locations[index % len(locations)]
    return {
        "location_id": location.get("location_id"),
        "position_x": location.get("position_x"),
        "position_y": location.get("position_y"),
    }


def build_tote_content(
    part_id: str, quantity: int, part_info: Dict[str, Any]
) -> Dict[str, Any]:
    lot_size = int(part_info["lot_size"])
    v_part = int(part_info["v_part"])
    v_carton = int(part_info["v_carton"])
    carton_count = 0 if quantity <= 0 else int(math.ceil(quantity / lot_size))
    used_carton_volume = carton_count * v_carton
    dead_space_units = carton_count * lot_size - quantity
    dead_space_volume = dead_space_units * v_part

    return {
        "part_id": part_id,
        "quantity": quantity,
        "lot_size": lot_size,
        "carton_count": carton_count,
        "v_part": v_part,
        "v_carton": v_carton,
        "used_carton_volume_cm3": used_carton_volume,
        "dead_space_volume_cm3": dead_space_volume,
    }


def pack_mixed_totes(
    mixed_and_residual_stock: Iterable[Tuple[str, int]],
    parts_data: Dict[str, Any],
    starting_index: int,
    layout_data: Dict[str, Any],
    min_types: int = 1,
    max_types: int = 9999,
    seed: int | None = None,
) -> Tuple[List[Dict[str, Any]], int]:
    totes: List[Dict[str, Any]] = []
    tote_index = starting_index
    current_tote: Dict[str, Any] | None = None
    current_volume = 0

    def flush_current_tote() -> None:
        nonlocal current_tote, current_volume
        if current_tote is not None:
            current_tote["used_volume_cm3"] = current_volume
            current_tote["remaining_capacity_cm3"] = max(
                0, TOTE_VOLUME_CM3 - current_volume
            )
            totes.append(current_tote)
            current_tote = None
            current_volume = 0

    # make a mutable list and optionally shuffle for reproducibility
    items = list(mixed_and_residual_stock)
    if seed is not None:
        rnd = random.Random(seed)
        rnd.shuffle(items)

    i = 0
    while i < len(items):
        part_id, quantity = items[i]
        remaining = quantity
        part_info = parts_data[part_id]

        while remaining > 0:
            content = build_tote_content(part_id, remaining, part_info)
            content_volume = content["used_carton_volume_cm3"]

            if current_tote is None:
                location = assign_storage_location(tote_index - 1, layout_data)
                current_tote = {
                    "tote_id": f"TOTE_{tote_index:04d}",
                    "tote_type": "mixed",
                    **location,
                    "contents": [],
                }
                tote_index += 1

            # if adding this content would exceed capacity or type limit, try lookahead
            current_types = len(current_tote["contents"]) if current_tote else 0
            remaining_capacity = TOTE_VOLUME_CM3 - current_volume

            # split large content to fit
            if content_volume > remaining_capacity:
                max_cartons_fit = max(1, remaining_capacity // part_info["v_carton"])
                max_units_fit = max(1, max_cartons_fit * int(part_info["lot_size"]))
                units_to_place = min(remaining, max_units_fit)
                content = build_tote_content(part_id, units_to_place, part_info)
                content_volume = content["used_carton_volume_cm3"]
            else:
                units_to_place = remaining

            # Heuristic: if adding all these cartons would leave too little room
            # for other parts and we still need to reach min_types, try to
            # reduce units_to_place so we reserve space for the smallest
            # required number of other cartons (full-carton units only).
            if seed is not None and min_types > 1:
                # collect v_carton values of future items (excluding current part)
                future_cartons = []
                for j in range(i + 1, len(items)):
                    pid, pq = items[j]
                    if pid == part_id or pq <= 0:
                        continue
                    future_cartons.append(parts_data[pid]["v_carton"])

                # if we don't have enough future distinct parts, consider all remaining
                if future_cartons:
                    future_cartons.sort()
                    current_types_count = (
                        len(current_tote["contents"]) if current_tote else 0
                    )
                    need_more = max(0, min_types - (current_types_count + 1))
                    # reserve space for 'need_more' smallest cartons
                    reserve_space = (
                        sum(future_cartons[:need_more]) if need_more > 0 else 0
                    )

                    # while the content would leave less than reserve_space, try to reduce cartons
                    if reserve_space > 0:
                        # compute how many cartons currently planned
                        planned_cartons = max(1, content["carton_count"])
                        carton_vol = part_info["v_carton"]
                        # reduce planned_cartons until enough room or down to 1
                        while planned_cartons > 1 and (
                            current_volume + planned_cartons * carton_vol
                            > TOTE_VOLUME_CM3 - reserve_space
                        ):
                            planned_cartons -= 1

                        if planned_cartons < content["carton_count"]:
                            # recompute units_to_place as full cartons
                            units_to_place = max(
                                int(part_info["lot_size"]),
                                planned_cartons * int(part_info["lot_size"]),
                            )
                            units_to_place = min(units_to_place, remaining)
                            content = build_tote_content(
                                part_id, units_to_place, part_info
                            )
                            content_volume = content["used_carton_volume_cm3"]

            # if adding would exceed capacity or exceed max_types, see if we can add a different
            # part to satisfy min_types requirement (lookahead)
            if (current_volume + content_volume > TOTE_VOLUME_CM3) or (
                current_types >= max_types
            ):
                # attempt to find another future item that fits into remaining capacity
                found_index = None
                if seed is not None:
                    rnd2 = random.Random(seed + 1)
                else:
                    rnd2 = random.Random()
                for j in range(i + 1, len(items)):
                    pid_j, qty_j = items[j]
                    if pid_j == part_id:
                        continue
                    info_j = parts_data[pid_j]
                    cont_j = build_tote_content(pid_j, qty_j, info_j)
                    if (
                        cont_j["used_carton_volume_cm3"] <= remaining_capacity
                        and current_types < max_types
                    ):
                        found_index = j
                        break

                if found_index is not None:
                    # take from found item instead
                    pid_j, qty_j = items[found_index]
                    info_j = parts_data[pid_j]
                    take_content = build_tote_content(pid_j, qty_j, info_j)
                    take_volume = take_content["used_carton_volume_cm3"]
                    current_tote["contents"].append(take_content)
                    current_volume += take_volume
                    # remove that item
                    items.pop(found_index)
                    continue

                # otherwise flush current tote and start a new one
                flush_current_tote()
                continue

            # normal add
            current_tote["contents"].append(content)
            current_volume += content_volume
            remaining -= units_to_place

            # reduce the current item remaining (we will update items[i] later)
            if remaining > 0:
                # partial placed, update items[i] to remaining
                items[i] = (part_id, remaining)
            else:
                # item fully consumed, will advance i
                i += 1

            if (
                current_volume >= TOTE_VOLUME_CM3
                or len(current_tote["contents"]) >= max_types
            ):
                flush_current_tote()

    # flush any last tote
    flush_current_tote()

    # Post-process: try to merge mixed totes that contain only 1 part type
    # into other mixed totes when possible to satisfy minimum-type requirement.
    if max_types >= 2:
        for i in range(len(totes)):
            t_i = totes[i]
            if t_i is None or t_i.get("tote_type") != "mixed":
                continue
            if len(t_i.get("contents", [])) > 1:
                continue
            s_vol = t_i.get("used_volume_cm3", 0)
            merged = False
            for j in range(len(totes)):
                if i == j:
                    continue
                t_j = totes[j]
                if t_j is None or t_j.get("tote_type") != "mixed":
                    continue
                if len(t_j.get("contents", [])) >= max_types:
                    continue
                rem = t_j.get("remaining_capacity_cm3", 0)
                if rem >= s_vol:
                    # merge i into j
                    t_j["contents"].extend(t_i["contents"])
                    t_j["used_volume_cm3"] = t_j.get("used_volume_cm3", 0) + s_vol
                    t_j["remaining_capacity_cm3"] = max(
                        0, t_j.get("remaining_capacity_cm3", 0) - s_vol
                    )
                    totes[i] = None
                    merged = True
                    break
            # if not merged, leave as is

        # remove None entries
        totes = [t for t in totes if t is not None]

    return totes, tote_index


def pack_mixed_grouped(
    mixed_pool: Iterable[Tuple[str, int]],
    parts_data: Dict[str, Any],
    starting_index: int,
    layout_data: Dict[str, Any],
    min_types: int = 2,
    max_types: int = 4,
    seed: int | None = 42,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Group parts into seeded groups of 2-4 distinct parts and pack full-carton units
    in a round-robin fashion into mixed totes. Ensures mixed totes contain >= min_types
    distinct parts when physically possible (full-carton constraint preserved).
    """
    totes: List[Dict[str, Any]] = []
    tote_index = starting_index
    rnd = random.Random(seed) if seed is not None else random.Random()

    # compute cartons per part (full cartons only)
    cartons_per_part: Dict[str, int] = {}
    lot_sizes: Dict[str, int] = {}
    for part_id, qty in mixed_pool:
        lot = int(parts_data[part_id]["lot_size"])
        cartons = max(0, qty // lot)
        if cartons > 0:
            cartons_per_part[part_id] = cartons_per_part.get(part_id, 0) + cartons
            lot_sizes[part_id] = lot

    if not cartons_per_part:
        return totes, tote_index

    # build groups by repeatedly taking up to `max_types` distinct parts (1 carton each)
    groups: List[List[str]] = []
    # work on a mutable dict
    remaining = dict(cartons_per_part)

    part_ids = list(remaining.keys())
    while sum(remaining.values()) > 0:
        rnd.shuffle(part_ids)
        group: List[str] = []
        for pid in part_ids:
            if remaining.get(pid, 0) <= 0:
                continue
            if pid in group:
                continue
            group.append(pid)
            remaining[pid] -= 1
            if len(group) >= max_types:
                break

        # if only one distinct part selected and there are other parts overall,
        # try to force another distinct part (scan unsampled parts)
        if len(group) < min_types:
            # find another part with remaining cartons (not in group)
            added = False
            for pid in part_ids:
                if pid in group or remaining.get(pid, 0) <= 0:
                    continue
                group.append(pid)
                remaining[pid] -= 1
                added = True
                break
            if not added and len(group) < min_types:
                # attempt to merge this single into previous group if possible
                if groups:
                    for prev in groups:
                        if len(prev) < max_types and group[0] not in prev:
                            prev.append(group[0])
                            group = []
                            break
        if group:
            groups.append(group)

    # Now pack each group into one or more totes using round-robin single-carton placements
    for group in groups:
        # reconstruct cartons counts for this group from cartons_per_part and total used
        group_cartons = {pid: cartons_per_part.get(pid, 0) for pid in group}
        # but some cartons were already reserved during grouping (we decremented), so recompute by
        # counting total cartons across groups for pid to get used; safer to rebuild from original
        # We'll instead calculate available cartons by summing occurrences across groups
        # Build occurrences
        occ: Dict[str, int] = {pid: 0 for pid in group}
        for g in groups:
            for pid in g:
                if pid in occ:
                    occ[pid] += 1
        # remaining_cartons for group will be occ[pid] plus any extra cartons beyond the occurrences
        # To avoid complexity, we'll reconstruct from the original mixed_pool totals
        original_cartons: Dict[str, int] = {}
        for pid, qty in mixed_pool:
            lot = int(parts_data[pid]["lot_size"])
            original_cartons[pid] = original_cartons.get(pid, 0) + (qty // lot)

        # determine how many cartons this group should handle: distribute proportionally
        group_cartons = {pid: 0 for pid in group}
        # assign at least one carton per appearance in groups
        for pid in group:
            group_cartons[pid] = 0

        # We'll derive available cartons for packing from original_cartons and track a global placed counter

    # Simpler packing: perform round-robin across all parts but only allow placing into a tote
    # if the tote will include at least min_types distinct parts. We'll iterate creating a new tote
    # and attempt to place one carton from up to max_types distinct parts.
    # Rebuild global cartons dict
    global_cartons = dict(cartons_per_part)
    part_list = list(global_cartons.keys())
    rnd.shuffle(part_list)

    while sum(global_cartons.values()) > 0:
        # start a new mixed tote
        location = assign_storage_location(tote_index - 1, layout_data)
        current_contents: List[Dict[str, Any]] = []
        current_volume = 0
        placed_types: Set[str] = set()

        # Try to seed the tote with up to min_types distinct parts first
        seed_candidates = [p for p in part_list if global_cartons.get(p, 0) > 0]
        # sort by remaining cartons descending so big parts are spread
        seed_candidates.sort(key=lambda x: global_cartons.get(x, 0), reverse=True)
        seeds = seed_candidates[: min(len(seed_candidates), max_types)]

        # ensure at least min_types seeds (pick more from shuffled list if needed)
        if len(seeds) < min_types:
            extra = [
                p for p in part_list if p not in seeds and global_cartons.get(p, 0) > 0
            ]
            for p in extra:
                seeds.append(p)
                if len(seeds) >= min_types:
                    break

        # place one carton from each seed (if fits)
        for pid in seeds:
            if global_cartons.get(pid, 0) <= 0:
                continue
            lot = int(parts_data[pid]["lot_size"])
            units = lot
            content = build_tote_content(pid, units, parts_data[pid])
            vol = content["used_carton_volume_cm3"]
            if current_volume + vol <= TOTE_VOLUME_CM3:
                current_contents.append(content)
                current_volume += vol
                placed_types.add(pid)
                global_cartons[pid] -= 1

        # round-robin fill: iterate parts and attempt to add one carton at a time
        made_progress = True
        while made_progress:
            made_progress = False
            for pid in part_list:
                if global_cartons.get(pid, 0) <= 0:
                    continue
                if pid in placed_types and len(placed_types) >= max_types:
                    continue
                lot = int(parts_data[pid]["lot_size"])
                units = lot
                content = build_tote_content(pid, units, parts_data[pid])
                vol = content["used_carton_volume_cm3"]
                if current_volume + vol <= TOTE_VOLUME_CM3:
                    # if adding would create a single-type tote (no other types), ensure we have at least min_types
                    if len(placed_types) == 0 and min_types > 1:
                        # skip until we have at least two distinct types seeded
                        continue
                    current_contents.append(content)
                    current_volume += vol
                    if pid not in placed_types:
                        placed_types.add(pid)
                    global_cartons[pid] -= 1
                    made_progress = True

        # If resulting tote has fewer than min_types distinct parts, try to move one carton from other parts
        if len(placed_types) < min_types:
            # attempt to pull a carton from other parts if possible
            for pid in part_list:
                if pid in placed_types or global_cartons.get(pid, 0) <= 0:
                    continue
                lot = int(parts_data[pid]["lot_size"])
                units = lot
                content = build_tote_content(pid, units, parts_data[pid])
                vol = content["used_carton_volume_cm3"]
                if current_volume + vol <= TOTE_VOLUME_CM3:
                    current_contents.append(content)
                    current_volume += vol
                    placed_types.add(pid)
                    global_cartons[pid] -= 1
                    break

        # if still fewer than min_types, move this tote's contents back to global_cartons and mark as cannot satisfy
        if len(placed_types) < min_types:
            # rollback: move cartons back
            for c in current_contents:
                pid = c["part_id"]
                cartons_back = c["carton_count"]
                global_cartons[pid] = global_cartons.get(pid, 0) + cartons_back
            # place as residual instead (cannot form a valid mixed tote)
            # create a residual tote using full-carton contents
            # Collect up to max_types distinct from current_contents to write as residual
            residual_contents = []
            for pid in [p for p in part_list if global_cartons.get(p, 0) > 0]:
                if len(residual_contents) >= max_types:
                    break
                lot = int(parts_data[pid]["lot_size"])
                if global_cartons[pid] <= 0:
                    continue
                units = lot
                content = build_tote_content(pid, units, parts_data[pid])
                residual_contents.append(content)
                global_cartons[pid] -= 1

            if residual_contents:
                totes.append(
                    {
                        "tote_id": f"TOTE_{tote_index:04d}",
                        "tote_type": "residual",
                        **location,
                        "contents": residual_contents,
                        "used_volume_cm3": sum(
                            c["used_carton_volume_cm3"] for c in residual_contents
                        ),
                        "remaining_capacity_cm3": max(
                            0,
                            TOTE_VOLUME_CM3
                            - sum(
                                c["used_carton_volume_cm3"] for c in residual_contents
                            ),
                        ),
                    }
                )
                tote_index += 1
            # continue to next tote
            continue

        # flush current mixed tote
        totes.append(
            {
                "tote_id": f"TOTE_{tote_index:04d}",
                "tote_type": "mixed",
                **location,
                "contents": current_contents,
                "used_volume_cm3": current_volume,
                "remaining_capacity_cm3": max(0, TOTE_VOLUME_CM3 - current_volume),
            }
        )
        tote_index += 1

    return totes, tote_index


def build_totes(
    bom_data: Dict[str, Any],
    layout_data: Dict[str, Any],
    scenario: ScenarioPaths,
    prod_plan_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    parts_data = bom_data["parts"]
    total_demand = compute_total_part_demand(bom_data, prod_plan_data)

    tote_entries: List[Dict[str, Any]] = []
    tote_index = 1
    mixed_pool: List[Tuple[str, int]] = []
    residual_pool: List[Tuple[str, int]] = []

    for part_id in sorted(parts_data):
        part_info = parts_data[part_id]
        planned_quantity = ceil_to_lot(
            int(total_demand.get(part_id, 0) * (1.0 + scenario.part_margin)),
            int(part_info["lot_size"]),
        )
        single_qty, mixed_qty, residual_qty = split_stock_by_ratio(
            planned_quantity,
            scenario.tote_single_part_ratio,
            scenario.tote_mixed_part_ratio,
            scenario.tote_residual_ratio,
        )

        if single_qty > 0:
            # Split single-type stock into one or more single-part totes so each
            # resulting tote does not exceed TOTE_VOLUME_CM3. This mirrors the
            # packing logic used for mixed totes but keeps totes single-part.
            # Only use full-carton units for single-part totes so they have no dead space.
            lot_size = int(part_info["lot_size"])
            full_single_units = (single_qty // lot_size) * lot_size
            remainder_single = single_qty - full_single_units
            remaining_single = full_single_units
            v_carton = int(part_info["v_carton"])
            lot_size = int(part_info["lot_size"])
            # how many cartons can fit in an empty tote (at least 1)
            cartons_per_tote = max(1, TOTE_VOLUME_CM3 // v_carton)
            units_per_tote = max(1, cartons_per_tote * lot_size)

            while remaining_single > 0:
                place_units = min(remaining_single, units_per_tote)
                content = build_tote_content(part_id, int(place_units), part_info)
                location = assign_storage_location(tote_index - 1, layout_data)
                tote_entries.append(
                    {
                        "tote_id": f"TOTE_{tote_index:04d}",
                        "tote_type": "single",
                        **location,
                        "contents": [content],
                        "used_volume_cm3": content["used_carton_volume_cm3"],
                        "remaining_capacity_cm3": max(
                            0, TOTE_VOLUME_CM3 - content["used_carton_volume_cm3"]
                        ),
                    }
                )
                tote_index += 1
                remaining_single -= place_units

            # any leftover single units that were not full cartons become residual
            if remainder_single > 0:
                residual_pool.append((part_id, remainder_single))

        # For mixed stock, only put full-carton units into mixed_pool so cartons
        # themselves have no dead space. Any remainder moves to residual_pool.
        if mixed_qty > 0:
            lot_size = int(part_info["lot_size"])
            full_mixed_units = (mixed_qty // lot_size) * lot_size
            remainder_mixed = mixed_qty - full_mixed_units
            if full_mixed_units > 0:
                mixed_pool.append((part_id, full_mixed_units))
            if remainder_mixed > 0:
                residual_pool.append((part_id, remainder_mixed))

        # residual_qty may contain full cartons; move full cartons into mixed pool
        # and keep at most one partial carton in residual_pool per part.
        if residual_qty > 0:
            lot_size = int(part_info["lot_size"])
            full_from_residual = (residual_qty // lot_size) * lot_size
            partial = residual_qty - full_from_residual
            if full_from_residual > 0:
                mixed_pool.append((part_id, full_from_residual))
            if partial > 0:
                residual_pool.append((part_id, partial))

    # pack mixed (full-carton) totes
    mixed_totes, tote_index = pack_mixed_grouped(
        mixed_pool,
        parts_data,
        tote_index,
        layout_data,
        min_types=2,
        max_types=4,
        seed=42,
    )
    tote_entries.extend(mixed_totes)

    # pack residuals as dedicated residual-type totes grouping 1-4 part types each
    if residual_pool:
        rnd = random.Random(42)
        # shuffle for reproducibility
        rnd.shuffle(residual_pool)
        idx = 0
        while idx < len(residual_pool):
            group_size = min(len(residual_pool) - idx, rnd.randint(1, 4))
            group = residual_pool[idx : idx + group_size]
            idx += group_size

            # create a residual tote and try to add all group contents; if overflow,
            # split into multiple residual totes as needed
            location = assign_storage_location(tote_index - 1, layout_data)
            current_contents: List[Dict[str, Any]] = []
            current_volume = 0
            for part_id, qty in group:
                part_info = parts_data[part_id]
                content = build_tote_content(part_id, int(qty), part_info)
                content_volume = content["used_carton_volume_cm3"]
                if (
                    current_volume + content_volume > TOTE_VOLUME_CM3
                    and current_contents
                ):
                    # flush current residual tote
                    tote_entries.append(
                        {
                            "tote_id": f"TOTE_{tote_index:04d}",
                            "tote_type": "residual",
                            **location,
                            "contents": current_contents,
                            "used_volume_cm3": current_volume,
                            "remaining_capacity_cm3": max(
                                0, TOTE_VOLUME_CM3 - current_volume
                            ),
                        }
                    )
                    tote_index += 1
                    location = assign_storage_location(tote_index - 1, layout_data)
                    current_contents = []
                    current_volume = 0

                # if single content itself larger than tote, split similarly to mixed logic
                if content_volume > TOTE_VOLUME_CM3:
                    max_cartons_fit = max(1, TOTE_VOLUME_CM3 // part_info["v_carton"])
                    max_units_fit = max(1, max_cartons_fit * int(part_info["lot_size"]))
                    units_to_place = min(int(qty), max_units_fit)
                    content = build_tote_content(part_id, units_to_place, part_info)
                    content_volume = content["used_carton_volume_cm3"]

                current_contents.append(content)
                current_volume += content_volume

            if current_contents:
                tote_entries.append(
                    {
                        "tote_id": f"TOTE_{tote_index:04d}",
                        "tote_type": "residual",
                        **location,
                        "contents": current_contents,
                        "used_volume_cm3": current_volume,
                        "remaining_capacity_cm3": max(
                            0, TOTE_VOLUME_CM3 - current_volume
                        ),
                    }
                )
                tote_index += 1
    return tote_entries


def infer_station_for_line(
    line_name: str, layout_data: Dict[str, Any]
) -> Dict[str, Any]:
    stations = layout_data.get("kitting_stations", [])
    if not stations:
        return {
            "station_id": None,
            "position_x": None,
            "position_y": None,
        }

    line_digits = "".join(character for character in line_name if character.isdigit())
    index = max(0, int(line_digits) - 1) if line_digits else 0
    station = stations[index % len(stations)]
    return {
        "station_id": station.get("station_id"),
        "position_x": station.get("position_x"),
        "position_y": station.get("position_y"),
    }


def build_kits(
    bom_data: Dict[str, Any],
    layout_data: Dict[str, Any],
    prod_plan_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    kits: List[Dict[str, Any]] = []
    products = bom_data["products"]

    # Kit physical defaults (provided): width x depth in cm, layered stacking info
    KIT_WIDTH_CM = 120
    KIT_DEPTH_CM = 120
    KIT_LAYERS = 3
    KIT_LAYER_HEIGHT_CM = 35
    KIT_LAYER_CAPACITY_CM3 = 504_000
    KIT_TOTAL_CAPACITY_CM3 = KIT_LAYER_CAPACITY_CM3 * KIT_LAYERS

    for plan_index, request in enumerate(prod_plan_data, start=1):
        product_id = request["product"]
        total_product_units = int(request["qty"])
        line_name = request.get("line", f"LINE_{plan_index:02d}")
        station = infer_station_for_line(line_name, layout_data)

        # compute per-product parts and per-product volume (using v_part)
        per_product_parts: Dict[str, int] = {}
        per_product_volume = 0
        for part_id, per_unit_qty in products[product_id]["required_parts"].items():
            per_unit_qty_int = int(per_unit_qty)
            if per_unit_qty_int <= 0:
                continue
            per_product_parts[part_id] = per_unit_qty_int
            v_part = int(bom_data["parts"][part_id]["v_part"])
            per_product_volume += per_unit_qty_int * v_part

        total_volume = per_product_volume * total_product_units

        # determine number of kits needed so each kit's total volume <= kit capacity
        n_kits = max(1, math.ceil(total_volume / KIT_TOTAL_CAPACITY_CM3))

        base_units = total_product_units // n_kits
        remainder = total_product_units - base_units * n_kits

        for sub in range(n_kits):
            units_for_kit = base_units + (1 if sub < remainder else 0)
            required_parts = {
                pid: qty * units_for_kit for pid, qty in per_product_parts.items()
            }

            # compute required volume for this kit (sum of part quantities * v_part)
            required_volume = 0
            for pid, qty in required_parts.items():
                v_part = int(bom_data["parts"][pid]["v_part"])
                required_volume += int(qty) * v_part

            kits.append(
                {
                    "kit_id": f"KIT_{plan_index:04d}_{sub + 1:02d}",
                    "source_plan_index": plan_index,
                    "line": line_name,
                    "start_time_sec": int(request["start_time_sec"]),
                    "product": product_id,
                    "qty": units_for_kit,
                    "station_id": station["station_id"],
                    "station_position_x": station["position_x"],
                    "station_position_y": station["position_y"],
                    "required_parts": required_parts,
                    "status": "waiting",
                    "kit_dimensions_cm": {
                        "width": KIT_WIDTH_CM,
                        "depth": KIT_DEPTH_CM,
                        "layers": KIT_LAYERS,
                        "layer_height_cm": KIT_LAYER_HEIGHT_CM,
                    },
                    "kit_total_capacity_cm3": KIT_TOTAL_CAPACITY_CM3,
                    "required_volume_cm3": required_volume,
                }
            )

    return kits


def generate_dataset(output_dir: Path) -> Dict[str, Path]:
    scenario_module = load_scenario_module()
    scenario = build_paths(scenario_module)
    validate_inputs(scenario)

    layout_data = load_json(scenario.layout_path)
    bom_data = load_json(scenario.bom_path)
    prod_plan_data = load_json(scenario.prod_plan_path)

    totes = build_totes(bom_data, layout_data, scenario, prod_plan_data)
    kits = build_kits(bom_data, layout_data, prod_plan_data)

    output_dir.mkdir(parents=True, exist_ok=True)
    totes_path = output_dir / "totes.json"
    kits_path = output_dir / "kits.json"
    scenario_path = str(SCENARIO_PATH.resolve())

    save_json(
        totes_path,
        {
            "meta": {
                "source_scenario": scenario_path,
                "layout_path": str(scenario.layout_path),
                "bom_path": str(scenario.bom_path),
                "prod_plan_path": str(scenario.prod_plan_path),
                "part_margin": scenario.part_margin,
                "tote_single_part_ratio": scenario.tote_single_part_ratio,
                "tote_mixed_part_ratio": scenario.tote_mixed_part_ratio,
                "tote_residual_ratio": scenario.tote_residual_ratio,
                "tote_volume_cm3": TOTE_VOLUME_CM3,
            },
            "totes": totes,
        },
    )
    save_json(
        kits_path,
        {
            "meta": {
                "source_scenario": scenario_path,
                "layout_path": str(scenario.layout_path),
                "bom_path": str(scenario.bom_path),
                "prod_plan_path": str(scenario.prod_plan_path),
            },
            "kits": kits,
        },
    )

    return {"totes": totes_path, "kits": kits_path}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate tote and kit JSON files for simulation."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR / "generated_datasets" / SCENARIO_MODULE_NAME,
        help="Directory where totes.json and kits.json will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for arg_name, arg_value in vars(args).items():
        print(f"{arg_name}: {arg_value}")
    paths = generate_dataset(args.output_dir)
    print(f"Wrote {paths['totes']}")
    print(f"Wrote {paths['kits']}")


if __name__ == "__main__":
    main()
