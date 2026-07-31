from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def compute_total_part_demand(
    bom_data: dict[str, Any], prod_plan_data: list[dict[str, Any]]
) -> dict[str, int]:
    products = bom_data.get("products", {})
    demand: dict[str, int] = {part_id: 0 for part_id in bom_data.get("parts", {})}

    for request in prod_plan_data:
        product_id = request["product"]
        quantity = int(request["qty"])
        required_parts = products[product_id]["required_parts"]
        for part_id, per_product_qty in required_parts.items():
            demand[part_id] = demand.get(part_id, 0) + int(per_product_qty) * quantity

    return demand


def assign_storage_location(index: int, layout_data: dict[str, Any]) -> dict[str, Any]:
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
    part_id: str, quantity: int, part_info: dict[str, Any]
) -> dict[str, Any]:
    lot_size = int(part_info["lot_size"])
    v_part = int(part_info["v_part"])
    v_carton = int(part_info["v_carton"])
    carton_count = 0 if quantity <= 0 else math.ceil(quantity / lot_size)
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


def build_single_tote(
    tote_index: int, parts_data: dict[str, Any], single_parts_quantity: dict[str, int]
) -> list[dict[str, Any]]:
    totes: list[dict[str, Any]] = []
    current_index = tote_index

    for part_id, quantity in single_parts_quantity.items():
        if quantity <= 0:
            raise ValueError(
                f"Quantity for part {part_id} must be positive for single tote generation."
            )

        lot_size = parts_data[part_id]["lot_size"]
        carton_volume = parts_data[part_id]["v_carton"]
        max_single_cartons_in_tote = TOTE_VOLUME_CM3 // carton_volume
        single_carton_count = quantity / lot_size
        single_tote_count = math.ceil(single_carton_count / max_single_cartons_in_tote)

        for i in range(single_tote_count):
            current_index += 1
            carton_count_to_pack = min(max_single_cartons_in_tote, single_carton_count)
            single_carton_count -= carton_count_to_pack
            used_volumne = carton_count_to_pack * carton_volume
            content = build_tote_content(
                part_id, carton_count_to_pack * lot_size, parts_data[part_id]
            )
            totes.append(
                {
                    "tote_id": f"TOTE_{current_index:04d}",
                    "tote_type": "single",
                    "contents": [content],
                    "used_volume_cm3": used_volumne,
                    "remaining_capacity_cm3": max(0, TOTE_VOLUME_CM3 - used_volumne),
                }
            )

    return totes


def build_mixed_tote(
    tote_index: int,
    parts_data: dict[str, Any],
    mixed_parts_quantity: dict[str, int],
    min_types: int = 2,
    max_types: int = 4,
) -> list[dict[str, Any]]:
    totes: list[dict[str, Any]] = []

    remain_parts_pool = {
        part_id: count for part_id, count in mixed_parts_quantity.items() if count > 0
    }

    while any(remain_parts_pool.values()):
        available_parts = [p for p, c in remain_parts_pool.items() if c > 0]
        if not available_parts:
            break

        sample_size = min(len(available_parts), random.randint(min_types, max_types))
        selected_parts = random.sample(available_parts, sample_size)
        selected_parts.sort(key=lambda p: parts_data[p]["v_carton"], reverse=True)

        packed_volume = 0
        packed_cartons = {}

        # 뽑힌 part들에 대해 1개 carton필수로 사용
        for part_id in selected_parts:
            carton_volume = parts_data[part_id]["v_carton"]
            lot_size = parts_data[part_id]["lot_size"]
            if packed_volume + carton_volume > TOTE_VOLUME_CM3:
                raise ValueError(
                    f"Cannot pack part {part_id} into mixed tote due to volume constraints."
                )

            packed_volume += carton_volume
            remain_parts_pool[part_id] -= lot_size
            packed_cartons[part_id] = packed_cartons.get(part_id, 0) + 1

        tote_full = False
        while not tote_full:
            tote_full = True
            for part_id in selected_parts:
                if remain_parts_pool[part_id] <= 0:
                    continue
                carton_volume = parts_data[part_id]["v_carton"]
                lot_size = parts_data[part_id]["lot_size"]

                if packed_volume + carton_volume > TOTE_VOLUME_CM3:
                    continue

                tote_full = False
                packed_volume += carton_volume
                remain_parts_pool[part_id] -= lot_size
                packed_cartons[part_id] = packed_cartons.get(part_id, 0) + 1

        contents = []
        for part_id, carton_count in packed_cartons.items():
            content = build_tote_content(
                part_id,
                carton_count * parts_data[part_id]["lot_size"],
                parts_data[part_id],
            )
            contents.append(content)

        tote_index += 1
        totes.append(
            {
                "tote_id": f"TOTE_{tote_index:04d}",
                "tote_type": "mixed",
                "contents": contents,
                "used_volume_cm3": packed_volume,
                "remaining_capacity_cm3": max(0, TOTE_VOLUME_CM3 - packed_volume),
            }
        )

    return totes


def build_residual_tote(
    tote_index: int,
    parts_data: dict[str, Any],
    residual_parts_quantity: dict[str, int],
    max_types: int = 4,
) -> list[dict[str, Any]]:
    totes: list[dict[str, Any]] = []
    current_index = tote_index

    remain_parts_pool = {
        part_id: count
        for part_id, count in residual_parts_quantity.items()
        if count > 0
    }

    while any(remain_parts_pool.values()):
        available_parts = [p for p, c in remain_parts_pool.items() if c > 0]
        if not available_parts:
            break

        sample_part_count = min(len(available_parts), random.randint(1, 4))
        selected_parts = random.sample(available_parts, sample_part_count)

        packed_volume = 0
        packed_cartons = {}

        contents = []
        for part_id in selected_parts:
            carton_volume = parts_data[part_id]["v_carton"]
            lot_size = int(parts_data[part_id]["lot_size"])
            if packed_volume + carton_volume > TOTE_VOLUME_CM3:
                raise ValueError(
                    f"Cannot pack part {part_id} into residual tote due to volume constraints."
                )

            sample_packed_part_count = random.randint(
                1,
                min(int(remain_parts_pool[part_id]), lot_size - 1),
            )
            packed_volume += carton_volume
            remain_parts_pool[part_id] -= sample_packed_part_count
            packed_cartons[part_id] = packed_cartons.get(part_id, 0) + 1

            content = build_tote_content(
                part_id,
                sample_packed_part_count,
                parts_data[part_id],
            )
            contents.append(content)

        current_index += 1
        totes.append(
            {
                "tote_id": f"TOTE_{current_index:04d}",
                "tote_type": "residual",
                "contents": contents,
                "used_volume_cm3": packed_volume,
                "remaining_capacity_cm3": max(0, TOTE_VOLUME_CM3 - packed_volume),
            }
        )

    return totes


def build_totes(
    bom_data: dict[str, Any],
    layout_data: dict[str, Any],
    scenario: ScenarioPaths,
    prod_plan_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    single_ratio = scenario.tote_single_part_ratio
    mixed_ratio = scenario.tote_mixed_part_ratio
    residual_ratio = scenario.tote_residual_ratio
    part_margin = scenario.part_margin
    parts_data = bom_data["parts"]
    total_parts_quantity = compute_total_part_demand(bom_data, prod_plan_data)
    totes: list[dict[str, Any]] = []
    random.seed(42)

    # margin 적용
    for part_id, demand_qty in total_parts_quantity.items():
        total_parts_quantity[part_id] = int(demand_qty * (1 + part_margin))

    # type별 수량 계산
    single_parts_quantity: dict[str, int] = {}
    mixed_parts_quantity: dict[str, int] = {}
    residual_parts_quantity: dict[str, int] = {}
    for part_id, total_qty in total_parts_quantity.items():
        lot_size = parts_data[part_id]["lot_size"]

        single_carton_count = (total_qty * single_ratio) // lot_size
        mixed_carton_count = (total_qty * mixed_ratio) // lot_size
        single_parts_quantity[part_id] = single_carton_count * lot_size
        mixed_parts_quantity[part_id] = mixed_carton_count * lot_size
        residual_parts_quantity[part_id] = (
            total_qty - single_parts_quantity[part_id] - mixed_parts_quantity[part_id]
        )

    single_totes = build_single_tote(0, parts_data, single_parts_quantity)
    totes.extend(single_totes)
    mixed_totes = build_mixed_tote(len(totes), parts_data, mixed_parts_quantity)
    totes.extend(mixed_totes)
    residual_totes = build_residual_tote(
        len(totes), parts_data, residual_parts_quantity
    )
    totes.extend(residual_totes)
    for tote in totes:
        tote["storage_location"] = assign_storage_location(
            int(tote["tote_id"].split("_")[1]), layout_data
        )
    return totes


def infer_station_for_line(
    line_name: str, layout_data: dict[str, Any]
) -> dict[str, Any]:
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
    bom_data: dict[str, Any],
    layout_data: dict[str, Any],
    prod_plan_data: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    kits: list[dict[str, Any]] = []
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
        per_product_parts: dict[str, int] = {}
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
                    "deadline_time_sec": int(request["start_time_sec"]),
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


def generate_dataset(output_dir: Path) -> dict[str, Path]:
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
    args, _ = parser.parse_known_args()
    return args


def main() -> None:
    args = parse_args()
    print(args)
    for arg_name, arg_value in vars(args).items():
        print(f"{arg_name}: {arg_value}")
    paths = generate_dataset(args.output_dir)
    print(f"Wrote {paths['totes']}")
    print(f"Wrote {paths['kits']}")


if __name__ == "__main__":
    main()
