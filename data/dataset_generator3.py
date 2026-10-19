"""입고 규칙 기반 데이터셋 생성기.

BOM/생산계획을 파라미터로 생성하고, 토트는 다음 입고 규칙에 따라 만든다.

1. 부피가 큰 SKU: 토트에 카톤 1개만 들어가고 남는 공간은 다른 SKU로 채운다.
2. 일반 SKU: 꽉 찬 단일 SKU 토트를 만들고, 남은 자투리 카톤은 모아서 배치한다.

자투리 카톤 배치 순서: (a) 큰 SKU 토트의 남는 공간 → (b) 새 토트.
이전 키팅 후 남은 잔량 토트는 FIFO 때문에 추가 입고 없이 소량 토트 그대로 오늘 세트에 들어온다.
잔량 토트의 부품은 모두 오늘 필요한 부품이다 (필요 없는 부품은 없다고 가정).
의도적인 재고 여유율은 두지 않는다. 잔량은 카톤 단위 입고 올림과 잔량 토트 재고에서만 생긴다.

납기는 정책과 무관한 누적 부하(src/simulation_engine/load_estimator.py)의 최댓값이
목표값(target_load)이 되도록 정한다. 납기의 모양(라인별 순서, 수량 비례 간격)을 먼저 만들고,
모든 납기에 같은 배율을 곱한다. 작업량은 그대로이고 처리 능력은 시간에 비례하므로
배율을 s로 하면 모든 납기의 부하가 정확히 1/s배가 된다.

사용 예:
    python data/dataset_generator3.py --preset medium --seed 42 --load 0.8
    python data/dataset_generator3.py --preset small --seed 1 --name my_small
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from dataset_generator2 import (
    TOTE_VOLUME_CM3,
    assign_storage_location,
    build_kits,
    build_tote_content,
    load_json,
    save_json,
)

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config.constants import KittingStationSpec  # noqa: E402
from simulation_engine.load_estimator import KitDemand, estimate_load  # noqa: E402

MASTER_DIR = BASE_DIR / "master_data"
LAYOUT_PATH = MASTER_DIR / "layout.json"
AGV_CONFIG_DIR = MASTER_DIR / "agv_configs"
DEFAULT_AGV_TEMPLATE = AGV_CONFIG_DIR / "agv_custom.json"

GENERATOR_REVISION = 2  # 2: 누적 부하 기준 납기, 잔량 토트 보충 제거, 잔량 토트 부품은 오늘 필요한 부품만

LOT_SIZE_CHOICES = [5, 10, 12, 15, 20, 25, 30, 40, 50, 100]


@dataclass(frozen=True)
class GeneratorConfig:
    # SKU / BOM
    n_skus: int
    n_main_models: int
    n_sub_models: int
    main_parts_per_model: tuple[int, int]
    sub_parts_per_model: tuple[int, int]
    common_part_ratio: float  # 여러 모델이 공유하는 공용 부품 비율
    common_pick_prob: float  # 모델이 각 공용 부품을 포함할 확률
    bulky_sku_ratio: float  # 토트당 카톤 1개만 들어가는 SKU 비율
    qty_per_unit_median: float  # 제품 1대당 부품 수량 (로그정규 중앙값)
    qty_per_unit_sigma: float
    # 생산 계획
    n_main_lines: int
    n_sub_lines: int
    lots_per_line: int  # 라인당 하루 lot 수 (= 모델 교체 횟수 + 1)
    lot_qty: tuple[int, int]
    # 납기: 정책과 무관한 누적 부하의 최댓값. 실험에 쓸 값은 파일럿으로 정한다 (기본값은 임시)
    target_load: float
    # 이전 키팅 후 남은 잔량 토트
    remnant_tote_ratio: float  # 전체 토트 대비 잔량 토트 비율
    remnant_skus_per_tote: tuple[int, int]
    remnant_full_cartons: tuple[int, int]  # 잔량 토트의 SKU당 꽉 찬 카톤 수
    # 보관 위치 배정: "random" (자동창고 임의 보관) 또는 "sequential"
    storage_assignment: str = "random"


PRESETS: dict[str, GeneratorConfig] = {
    "small": GeneratorConfig(
        n_skus=30,
        n_main_models=3,
        n_sub_models=2,
        main_parts_per_model=(8, 12),
        sub_parts_per_model=(5, 8),
        common_part_ratio=0.2,
        common_pick_prob=0.5,
        bulky_sku_ratio=0.10,
        qty_per_unit_median=2.0,
        qty_per_unit_sigma=0.7,
        n_main_lines=2,
        n_sub_lines=2,
        lots_per_line=3,
        lot_qty=(60, 120),
        target_load=0.8,
        remnant_tote_ratio=0.0,
        remnant_skus_per_tote=(1, 3),
        remnant_full_cartons=(0, 2),
    ),
    "medium": GeneratorConfig(
        n_skus=80,
        n_main_models=7,
        n_sub_models=5,
        main_parts_per_model=(16, 24),
        sub_parts_per_model=(8, 14),
        common_part_ratio=0.3,
        common_pick_prob=0.5,
        bulky_sku_ratio=0.15,
        qty_per_unit_median=2.0,
        qty_per_unit_sigma=0.7,
        n_main_lines=3,
        n_sub_lines=3,
        lots_per_line=5,
        lot_qty=(40, 80),
        target_load=0.8,
        remnant_tote_ratio=0.05,
        remnant_skus_per_tote=(1, 3),
        remnant_full_cartons=(0, 2),
    ),
    "large": GeneratorConfig(
        n_skus=200,
        n_main_models=18,
        n_sub_models=12,
        main_parts_per_model=(28, 40),
        sub_parts_per_model=(12, 20),
        common_part_ratio=0.4,
        common_pick_prob=0.5,
        bulky_sku_ratio=0.20,
        qty_per_unit_median=2.0,
        qty_per_unit_sigma=0.7,
        n_main_lines=5,
        n_sub_lines=5,
        lots_per_line=7,
        lot_qty=(20, 40),
        target_load=0.8,
        remnant_tote_ratio=0.10,
        remnant_skus_per_tote=(1, 3),
        remnant_full_cartons=(0, 2),
    ),
}


# ---------------------------------------------------------------------------
# BOM
# ---------------------------------------------------------------------------


def build_parts(cfg: GeneratorConfig, rng: random.Random) -> dict[str, dict[str, Any]]:
    """SKU 기준정보. v_carton = lot_size * v_part 가 항상 성립하도록 만든다."""
    parts: dict[str, dict[str, Any]] = {}
    n_bulky = round(cfg.n_skus * cfg.bulky_sku_ratio)
    bulky_ids = set(rng.sample(range(cfg.n_skus), n_bulky))

    for i in range(cfg.n_skus):
        lot_size = rng.choice(LOT_SIZE_CHOICES)
        if i in bulky_ids:
            # 토트에 카톤 1개만 들어가고 15~45% 공간이 남는다
            target_carton = rng.uniform(0.55, 0.85) * TOTE_VOLUME_CM3
        else:
            # 토트당 카톤 4~20개 (로그 균등)
            target_carton = math.exp(
                rng.uniform(math.log(TOTE_VOLUME_CM3 / 20), math.log(TOTE_VOLUME_CM3 / 4))
            )
        v_part = max(1, int(target_carton // lot_size))
        parts[f"PART_{i + 1:03d}"] = {
            "lot_size": lot_size,
            "v_part": v_part,
            "v_carton": v_part * lot_size,
            "bulky": i in bulky_ids,
        }
    return parts


def _qty_per_unit(cfg: GeneratorConfig, part: dict[str, Any], rng: random.Random) -> int:
    if part["bulky"]:
        return 1  # 하우징처럼 부피가 큰 부품은 대당 1개
    qty = rng.lognormvariate(math.log(cfg.qty_per_unit_median), cfg.qty_per_unit_sigma)
    return max(1, min(20, round(qty)))


def build_products(
    cfg: GeneratorConfig, parts: dict[str, dict[str, Any]], rng: random.Random
) -> dict[str, dict[str, Any]]:
    """공용 부품 + 모델 전용 부품으로 BOM 구성. 모든 SKU가 최소 한 모델에 쓰이게 한다."""
    part_ids = list(parts)
    rng.shuffle(part_ids)
    n_common = round(len(part_ids) * cfg.common_part_ratio)
    common, specific = part_ids[:n_common], part_ids[n_common:]

    models = [("MAIN", i) for i in range(cfg.n_main_models)] + [
        ("SUB", i) for i in range(cfg.n_sub_models)
    ]
    rng.shuffle(specific)
    unused_specific = list(specific)

    products: dict[str, dict[str, Any]] = {}
    for line_type, index in models:
        lo, hi = (
            cfg.main_parts_per_model if line_type == "MAIN" else cfg.sub_parts_per_model
        )
        n_parts = rng.randint(lo, hi)
        chosen = [p for p in common if rng.random() < cfg.common_pick_prob]
        chosen = chosen[: max(1, n_parts // 2)]
        while len(chosen) < n_parts:
            # 아직 아무 모델에도 쓰이지 않은 전용 부품을 우선 배정
            pool = unused_specific or specific
            part_id = pool.pop(0) if pool is unused_specific else rng.choice(pool)
            if part_id not in chosen:
                chosen.append(part_id)

        products[f"{line_type}_{index + 1:02d}"] = {
            "line_type": line_type,
            "required_parts": {p: _qty_per_unit(cfg, parts[p], rng) for p in chosen},
        }

    # 남은 전용 부품은 무작위 모델에 추가
    for part_id in unused_specific:
        product = rng.choice(list(products.values()))
        product["required_parts"][part_id] = _qty_per_unit(cfg, parts[part_id], rng)

    return products


# ---------------------------------------------------------------------------
# 생산 계획
# ---------------------------------------------------------------------------


def _estimate_kitting_time(
    product: dict[str, Any], qty: int, parts: dict[str, dict[str, Any]]
) -> float:
    total = 0.0
    for part_id, per_unit in product["required_parts"].items():
        lot_size = parts[part_id]["lot_size"]
        need = per_unit * qty
        total += (need // lot_size) * KittingStationSpec.FULL_CARTON_TRANSFER_TIME_SEC
        if need % lot_size:
            total += KittingStationSpec.PARTIAL_CARTON_TRANSFER_TIME_SEC
    return total + KittingStationSpec.KIT_CHANGING_TIME_SEC


def build_prod_plan(
    cfg: GeneratorConfig,
    products: dict[str, dict[str, Any]],
    parts: dict[str, dict[str, Any]],
    n_stations: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """라인별 lot 순서를 만들고, 납기의 모양(기준 시각)을 정한다.

    기준 시각은 스테이션 카톤 이송 시간으로 잰 상대 척도다. 실제 납기는
    generate()에서 누적 부하가 목표값이 되도록 배율을 곱해 정한다.
    """
    by_type = {
        t: [pid for pid, p in products.items() if p["line_type"] == t]
        for t in ("MAIN", "SUB")
    }
    lines = [("MAIN", i) for i in range(cfg.n_main_lines)] + [
        ("SUB", i) for i in range(cfg.n_sub_lines)
    ]

    line_lots: list[tuple[str, str, list[tuple[str, int]]]] = []
    for line_no, (line_type, _) in enumerate(lines, start=1):
        lots: list[tuple[str, int]] = []
        prev = None
        for _ in range(cfg.lots_per_line):
            candidates = [m for m in by_type[line_type] if m != prev] or by_type[line_type]
            model = rng.choice(candidates)
            lots.append((model, rng.randint(*cfg.lot_qty)))
            prev = model
        line_lots.append((f"LINE_{line_no:02d}", line_type, lots))

    # 모든 라인의 첫 lot은 같은 시각, 이후 lot은 라인마다 수량에 비례한 간격
    total_work = sum(
        _estimate_kitting_time(products[m], q, parts)
        for _, _, lots in line_lots
        for m, q in lots
    )
    horizon = total_work / n_stations
    first_lot_work = sum(
        _estimate_kitting_time(products[lots[0][0]], lots[0][1], parts)
        for _, _, lots in line_lots
    )
    first_start = first_lot_work / n_stations

    plan: list[dict[str, Any]] = []
    for line_name, line_type, lots in line_lots:
        line_qty = sum(q for _, q in lots)
        takt = (horizon - first_start) / line_qty
        start = first_start
        for model, qty in lots:
            plan.append(
                {
                    "line": line_name,
                    "line_type": line_type,
                    "base_start": start,
                    "start_time_sec": int(round(start)),
                    "product": model,
                    "qty": qty,
                }
            )
            start += qty * takt
    plan.sort(key=lambda r: (r["base_start"], r["line"]))
    return plan


def compute_part_demand(
    products: dict[str, dict[str, Any]], plan: list[dict[str, Any]]
) -> dict[str, int]:
    demand: dict[str, int] = {}
    for row in plan:
        for part_id, per_unit in products[row["product"]]["required_parts"].items():
            demand[part_id] = demand.get(part_id, 0) + per_unit * row["qty"]
    return demand


# ---------------------------------------------------------------------------
# 토트 (입고 규칙)
# ---------------------------------------------------------------------------


class _ToteBuilder:
    """카톤 단위로 토트를 채운다. contents: part_id -> 수량."""

    def __init__(self, tote_type: str):
        self.tote_type = tote_type
        self.contents: dict[str, int] = {}
        self.used_volume = 0

    def free(self) -> int:
        return TOTE_VOLUME_CM3 - self.used_volume

    def add(self, part_id: str, qty: int, cartons: int, v_carton: int) -> None:
        self.contents[part_id] = self.contents.get(part_id, 0) + qty
        self.used_volume += cartons * v_carton


def build_remnant_totes(
    cfg: GeneratorConfig,
    parts: dict[str, dict[str, Any]],
    demand: dict[str, int],
    n_remnant: int,
    rng: random.Random,
) -> list[_ToteBuilder]:
    """이전 키팅 후 남은 잔량 토트. 부품은 모두 오늘 필요한 부품에서 고른다."""
    needed = [p for p, q in demand.items() if q > 0]
    totes: list[_ToteBuilder] = []
    for _ in range(n_remnant):
        builder = _ToteBuilder("remnant")
        n_skus = min(rng.randint(*cfg.remnant_skus_per_tote), len(needed))
        skus: list[str] = []
        while len(skus) < n_skus:
            p = rng.choice(needed)
            if p not in skus:
                skus.append(p)
        for part_id in skus:
            info = parts[part_id]
            lot, v_carton = info["lot_size"], info["v_carton"]
            if lot < 2:
                continue
            full = rng.randint(*cfg.remnant_full_cartons)
            # 꽉 찬 카톤 + 일부만 찬 카톤 1개. 공간이 부족하면 꽉 찬 카톤을 줄인다
            while full >= 0 and (full + 1) * v_carton > builder.free():
                full -= 1
            if full < 0:
                continue
            qty = full * lot + rng.randint(1, lot - 1)
            builder.add(part_id, qty, full + 1, v_carton)
        if builder.contents:
            totes.append(builder)
    return totes


def build_inbound_totes(
    parts: dict[str, dict[str, Any]],
    inbound: dict[str, int],
    rng: random.Random,
) -> list[_ToteBuilder]:
    """입고 수량(카톤 단위)을 단일 / 큰 SKU / 혼합 토트로 적재한다. 잔량 토트에는 넣지 않는다."""
    totes: list[_ToteBuilder] = []
    bulky_totes: list[_ToteBuilder] = []
    tail: list[tuple[str, int]] = []  # (part_id, 카톤 수)
    cartons_left = {p: q // parts[p]["lot_size"] for p, q in inbound.items() if q > 0}

    # 1) 큰 SKU: 토트당 카톤 1개
    for part_id in list(cartons_left):
        info = parts[part_id]
        if TOTE_VOLUME_CM3 // info["v_carton"] > 1:
            continue
        for _ in range(cartons_left.pop(part_id)):
            builder = _ToteBuilder("bulky")
            builder.add(part_id, info["lot_size"], 1, info["v_carton"])
            bulky_totes.append(builder)

    # 2) 큰 SKU 토트의 남는 공간을 다른 SKU 카톤으로 채움 (들어가는 SKU 중 하나를 골라 가능한 만큼)
    for builder in bulky_totes:
        fits = [
            p for p, n in cartons_left.items() if n and parts[p]["v_carton"] <= builder.free()
        ]
        if not fits:
            continue
        part_id = rng.choice(fits)
        lot, v_carton = parts[part_id]["lot_size"], parts[part_id]["v_carton"]
        n = min(cartons_left[part_id], builder.free() // v_carton)
        builder.add(part_id, n * lot, n, v_carton)
        cartons_left[part_id] -= n

    # 3) 일반 SKU: 꽉 찬 단일 토트 + 자투리 카톤
    for part_id, cartons in cartons_left.items():
        if not cartons:
            continue
        info = parts[part_id]
        lot, v_carton = info["lot_size"], info["v_carton"]
        per_tote = TOTE_VOLUME_CM3 // v_carton
        while cartons >= per_tote:
            builder = _ToteBuilder("single")
            builder.add(part_id, per_tote * lot, per_tote, v_carton)
            totes.append(builder)
            cartons -= per_tote
        if cartons:
            tail.append((part_id, cartons))

    # 자투리 카톤: 큰 카톤부터, SKU 단위로 한 토트에 넣는 것을 우선 시도
    tail.sort(key=lambda t: parts[t[0]]["v_carton"], reverse=True)
    mixed: list[_ToteBuilder] = []
    for part_id, cartons in tail:
        lot, v_carton = parts[part_id]["lot_size"], parts[part_id]["v_carton"]
        while cartons:
            targets = bulky_totes + mixed  # (a) → (b)
            group = next((t for t in targets if t.free() >= cartons * v_carton), None)
            if group is not None:
                group.add(part_id, cartons * lot, cartons, v_carton)
                cartons = 0
                continue
            single = next((t for t in targets if t.free() >= v_carton), None)
            if single is None:
                single = _ToteBuilder("mixed")
                mixed.append(single)
            fit = min(cartons, single.free() // v_carton)
            single.add(part_id, fit * lot, fit, v_carton)
            cartons -= fit

    return totes + bulky_totes + mixed


def _classify(builder: _ToteBuilder) -> str:
    if builder.tote_type == "remnant":
        return "remnant_mixed" if len(builder.contents) > 1 else "remnant"
    if builder.tote_type == "bulky":
        return "bulky_mixed" if len(builder.contents) > 1 else "bulky"
    return builder.tote_type


def finalize_totes(
    builders: list[_ToteBuilder],
    parts: dict[str, dict[str, Any]],
    layout: dict[str, Any],
    cfg: GeneratorConfig,
    rng: random.Random,
) -> list[dict[str, Any]]:
    order = list(range(len(builders)))
    if cfg.storage_assignment == "random":
        rng.shuffle(order)

    totes: list[dict[str, Any]] = []
    for slot, index in enumerate(order):
        builder = builders[index]
        contents = [
            build_tote_content(part_id, qty, parts[part_id])
            for part_id, qty in builder.contents.items()
        ]
        used = sum(c["used_carton_volume_cm3"] for c in contents)
        tote = {
            "tote_id": f"TOTE_{index + 1:05d}",
            "tote_type": _classify(builder),
            "contents": contents,
            "used_volume_cm3": used,
            "remaining_capacity_cm3": max(0, TOTE_VOLUME_CM3 - used),
        }
        tote.update(assign_storage_location(slot, layout))
        totes.append(tote)
    totes.sort(key=lambda t: t["tote_id"])
    return totes


# ---------------------------------------------------------------------------
# 납기 (누적 부하)
# ---------------------------------------------------------------------------


def estimate_instance_load(
    kits: list[dict[str, Any]],
    totes: list[dict[str, Any]],
    layout: dict[str, Any],
    parts: dict[str, dict[str, Any]],
    n_agvs: int,
) -> dict[str, Any]:
    """t=0 인스턴스 부하. 시뮬레이터처럼 납기가 빠른 키트 n_stations개는 처음부터 배정된 것으로 본다."""
    stations = layout["kitting_stations"]
    order = sorted(range(len(kits)), key=lambda i: kits[i]["deadline_time_sec"])
    started = set(order[: len(stations)])
    demands = [
        KitDemand(
            deadline=float(kit["deadline_time_sec"]),
            remaining_parts=dict(kit["required_parts"]),
            needs_setup=i not in started,
        )
        for i, kit in enumerate(kits)
    ]
    return estimate_load(
        kits=demands,
        tote_stocks=[{c["part_id"]: c["quantity"] for c in t["contents"]} for t in totes],
        tote_points=[(float(t["position_x"]), float(t["position_y"])) for t in totes],
        station_points=[(float(s["position_x"]), float(s["position_y"])) for s in stations],
        lot_sizes={p: info["lot_size"] for p, info in parts.items()},
        n_agvs=n_agvs,
    )


def apply_deadline_scale(
    plan: list[dict[str, Any]], kits: list[dict[str, Any]], scale: float
) -> None:
    for row in plan:
        row["start_time_sec"] = max(1, int(round(row["base_start"] * scale)))
    for kit in kits:
        kit["deadline_time_sec"] = plan[kit["source_plan_index"] - 1]["start_time_sec"]


# ---------------------------------------------------------------------------
# 생성 / 저장
# ---------------------------------------------------------------------------


def summarize(
    parts: dict[str, dict[str, Any]],
    products: dict[str, dict[str, Any]],
    plan: list[dict[str, Any]],
    kits: list[dict[str, Any]],
    totes: list[dict[str, Any]],
    demand: dict[str, int],
    load: dict[str, Any],
) -> dict[str, Any]:
    type_counts: dict[str, int] = {}
    stock: dict[str, int] = {}
    for tote in totes:
        type_counts[tote["tote_type"]] = type_counts.get(tote["tote_type"], 0) + 1
        for c in tote["contents"]:
            stock[c["part_id"]] = stock.get(c["part_id"], 0) + c["quantity"]

    leftover = {p: stock.get(p, 0) - demand.get(p, 0) for p in stock}
    shortage = {p: q for p, q in demand.items() if stock.get(p, 0) < q}
    leftover_volume = sum(max(0, q) * parts[p]["v_part"] for p, q in leftover.items())
    stock_volume = sum(q * parts[p]["v_part"] for p, q in stock.items())
    mixed = sum(1 for t in totes if len(t["contents"]) > 1)
    deadlines = [r["start_time_sec"] for r in plan]

    return {
        "n_skus": len(parts),
        "n_bulky_skus": sum(1 for p in parts.values() if p["bulky"]),
        "n_products": len(products),
        "n_lots": len(plan),
        "n_kits": len(kits),
        "n_totes": len(totes),
        "tote_type_counts": dict(sorted(type_counts.items())),
        "mixed_tote_ratio": round(mixed / len(totes), 4),
        "leftover_volume_ratio": round(leftover_volume / stock_volume, 4),
        "parts_with_leftover": sum(1 for q in leftover.values() if q > 0),
        "parts_without_leftover": sum(1 for q in leftover.values() if q == 0),
        "shortage_parts": shortage,
        "deadline_min_sec": min(deadlines),
        "deadline_max_sec": max(deadlines),
        "load": {
            "peak": round(load["peak"], 4),
            "bottleneck": load["bottleneck"],
            "peak_deadline_sec": load["peak_deadline"],
            "agv": round(load["agv"], 4),
            "slot": round(load["slot"], 4),
            "station": round(load["station"], 4),
            "n_dispatch_estimate": load["n_dispatch_estimate"],
            "mean_empty_travel_m": round(load["mean_empty_travel_m"], 2),
            "mean_tote_station_m": round(load["mean_tote_station_m"], 2),
        },
    }


def generate(cfg: GeneratorConfig, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    layout = load_json(LAYOUT_PATH)
    n_stations = len(layout.get("kitting_stations", [])) or 1
    n_agvs = len(load_json(DEFAULT_AGV_TEMPLATE))

    parts = build_parts(cfg, rng)
    products = build_products(cfg, parts, rng)
    plan = build_prod_plan(cfg, products, parts, n_stations, rng)
    demand = compute_part_demand(products, plan)

    # 잔량 토트 수는 입고 토트 수를 먼저 가늠한 뒤 비율로 정한다
    estimated = sum(
        math.ceil(math.ceil(q / parts[p]["lot_size"]) * parts[p]["v_carton"] / TOTE_VOLUME_CM3)
        for p, q in demand.items()
    )
    n_remnant = round(estimated * cfg.remnant_tote_ratio / (1 - cfg.remnant_tote_ratio))
    remnant = build_remnant_totes(cfg, parts, demand, n_remnant, rng)

    # FIFO: 잔량 토트(오래된 재고)를 먼저 쓰고, 부족분만 카톤 단위로 올려서 입고
    remnant_stock: dict[str, int] = {}
    for builder in remnant:
        for p, q in builder.contents.items():
            remnant_stock[p] = remnant_stock.get(p, 0) + q
    inbound = {}
    for part_id, need in demand.items():
        lot = parts[part_id]["lot_size"]
        inbound[part_id] = math.ceil(max(0, need - remnant_stock.get(part_id, 0)) / lot) * lot

    builders = remnant + build_inbound_totes(parts, inbound, rng)
    totes = finalize_totes(builders, parts, layout, cfg, rng)

    bom = {"products": products, "parts": parts}
    kits = build_kits(bom, layout, plan)
    for kit in kits:
        kit["line_type"] = plan[kit["source_plan_index"] - 1]["line_type"]

    # 기준 모양의 최대 누적 부하 L0 → 모든 납기에 L0 / 목표 부하를 곱한다
    base_load = estimate_instance_load(kits, totes, layout, parts, n_agvs)
    apply_deadline_scale(plan, kits, base_load["peak"] / cfg.target_load)
    load = estimate_instance_load(kits, totes, layout, parts, n_agvs)
    for row in plan:
        del row["base_start"]

    return {
        "bom": bom,
        "plan": plan,
        "totes": totes,
        "kits": kits,
        "summary": summarize(parts, products, plan, kits, totes, demand, load),
    }


def save(name: str, cfg: GeneratorConfig, seed: int, preset: str, data: dict) -> Path:
    out_dir = BASE_DIR / "generated_datasets" / f"scenario_{name}"
    meta = {
        "generator": "dataset_generator3",
        "revision": GENERATOR_REVISION,
        "preset": preset,
        "seed": seed,
        "config": asdict(cfg),
        "tote_volume_cm3": TOTE_VOLUME_CM3,
        "summary": data["summary"],
    }
    save_json(out_dir / "totes.json", {"meta": meta, "totes": data["totes"]})
    save_json(out_dir / "kits.json", {"meta": meta, "kits": data["kits"]})
    save_json(out_dir / "bom.json", data["bom"])
    save_json(out_dir / "prod_plan.json", data["plan"])

    # dataset_loader 는 master_data/agv_configs/agv_<name>.json 을 찾는다
    agv_path = AGV_CONFIG_DIR / f"agv_{name}.json"
    if not agv_path.exists():
        shutil.copyfile(DEFAULT_AGV_TEMPLATE, agv_path)
    return out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="입고 규칙 기반 데이터셋 생성기")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="medium")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--load", type=float, help="목표 최대 누적 부하 덮어쓰기")
    parser.add_argument("--name", help="시나리오 이름 (기본: gen3_<preset>_s<seed>_L<부하×100>)")
    parser.add_argument("--remnant-ratio", type=float, help="이전 잔량 토트 비율 덮어쓰기")
    parser.add_argument("--dry-run", action="store_true", help="저장하지 않고 요약만 출력")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = PRESETS[args.preset]
    if args.remnant_ratio is not None:
        cfg = replace(cfg, remnant_tote_ratio=args.remnant_ratio)
    if args.load is not None:
        cfg = replace(cfg, target_load=args.load)

    data = generate(cfg, args.seed)
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    if args.dry_run:
        return
    name = args.name or f"gen3_{args.preset}_s{args.seed}_L{round(cfg.target_load * 100):03d}"
    out_dir = save(name, cfg, args.seed, args.preset, data)
    print(f"Wrote {out_dir}")


if __name__ == "__main__":
    main()
