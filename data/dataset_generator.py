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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

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

    for part_id, quantity in mixed_and_residual_stock:
        remaining = quantity
        while remaining > 0:
            part_info = parts_data[part_id]
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

            if current_volume > 0 and current_volume + content_volume > TOTE_VOLUME_CM3:
                flush_current_tote()
                continue

            if content_volume > TOTE_VOLUME_CM3:
                max_cartons_fit = max(
                    1, (TOTE_VOLUME_CM3 - current_volume) // part_info["v_carton"]
                )
                max_units_fit = max(1, max_cartons_fit * int(part_info["lot_size"]))
                units_to_place = min(remaining, max_units_fit)
                content = build_tote_content(part_id, units_to_place, part_info)
                content_volume = content["used_carton_volume_cm3"]
            else:
                units_to_place = remaining

            current_tote["contents"].append(content)
            current_volume += content_volume
            remaining -= units_to_place

            if current_volume >= TOTE_VOLUME_CM3:
                flush_current_tote()

    flush_current_tote()
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
            remaining_single = single_qty
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

        if mixed_qty > 0:
            mixed_pool.append((part_id, mixed_qty))

        if residual_qty > 0:
            mixed_pool.append((part_id, residual_qty))

    mixed_totes, _ = pack_mixed_totes(mixed_pool, parts_data, tote_index, layout_data)
    tote_entries.extend(mixed_totes)
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
                    "remaining_parts": dict(required_parts),
                    "status": "waiting",
                    "kit_dimensions_cm": {
                        "width": KIT_WIDTH_CM,
                        "depth": KIT_DEPTH_CM,
                        "layers": KIT_LAYERS,
                        "layer_height_cm": KIT_LAYER_HEIGHT_CM,
                    },
                    "kit_total_capacity_cm3": KIT_TOTAL_CAPACITY_CM3,
                    "remaining_volume_cm3": KIT_TOTAL_CAPACITY_CM3,
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
