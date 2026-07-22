from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.constants import KitSpec, ToteSpec


@dataclass
class Component:
    part_id: str
    quantity: int
    lot_size: Optional[int] = None
    carton_count: Optional[int] = None
    v_part: Optional[int] = None
    v_carton: Optional[int] = None
    used_carton_volume_cm3: Optional[int] = None
    dead_space_volume_cm3: Optional[int] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Component":
        return cls(
            part_id=d.get("part_id", ""),
            quantity=int(d.get("quantity", 0)),
            lot_size=d.get("lot_size"),
            carton_count=d.get("carton_count"),
            v_part=d.get("v_part"),
            v_carton=d.get("v_carton"),
            used_carton_volume_cm3=d.get("used_carton_volume_cm3"),
            dead_space_volume_cm3=d.get("dead_space_volume_cm3"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "part_id": self.part_id,
            "quantity": self.quantity,
            "lot_size": self.lot_size,
            "carton_count": self.carton_count,
            "v_part": self.v_part,
            "v_carton": self.v_carton,
            "used_carton_volume_cm3": self.used_carton_volume_cm3,
            "dead_space_volume_cm3": self.dead_space_volume_cm3,
        }

    def deduct_quantity(self, qty_to_deduct: int) -> int:
        if qty_to_deduct > self.quantity:
            raise ValueError(
                f"Pick quantity {qty_to_deduct} exceeds available quantity {self.quantity} for part {self.part_id}."
            )

        self.quantity -= qty_to_deduct

        self.carton_count = math.ceil(self.quantity / self.lot_size)
        self.used_carton_volume_cm3 = self.carton_count * self.v_carton
        remaining_parts_in_last_carton = self.quantity % self.lot_size
        self.dead_space_volume_cm3 = (
            0
            if remaining_parts_in_last_carton == 0
            else self.v_carton - (remaining_parts_in_last_carton * self.v_part)
        )

        return qty_to_deduct


@dataclass
class Tote:
    tote_id: str
    tote_type: str
    location_id: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    contents: List[Component] = field(default_factory=list)
    used_volume_cm3: int = 0
    remaining_capacity_cm3: int = 0
    max_capacity_cm3: int = ToteSpec.MAX_CAPACITY_CM3

    def __post_init__(self) -> None:
        self.update_used_volume_cm3()

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Tote":
        contents = [Component.from_dict(c) for c in d.get("contents", [])]
        return cls(
            tote_id=d.get("tote_id", ""),
            tote_type=d.get("tote_type", "single"),
            location_id=d.get("location_id"),
            position_x=d.get("position_x"),
            position_y=d.get("position_y"),
            contents=contents,
            used_volume_cm3=int(d.get("used_volume_cm3", 0)),
            remaining_capacity_cm3=int(d.get("remaining_capacity_cm3", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tote_id": self.tote_id,
            "tote_type": self.tote_type,
            "location_id": self.location_id,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "contents": [c.to_dict() for c in self.contents],
            "used_volume_cm3": self.used_volume_cm3,
            "remaining_capacity_cm3": self.remaining_capacity_cm3,
        }

    def update_used_volume_cm3(self) -> None:
        new_used_volume = sum(
            comp.used_carton_volume_cm3 or 0 for comp in self.contents
        )
        self.used_volume_cm3 = new_used_volume
        self.remaining_capacity_cm3 = self.max_capacity_cm3 - new_used_volume

    def pick_part(self, part_id: str, qty_to_pick: int) -> int:
        component_to_pick = next(
            (c for c in self.contents if c.part_id == part_id), None
        )
        if not component_to_pick:
            raise ValueError(f"Part {part_id} not found in tote {self.tote_id}.")

        picked_qty = component_to_pick.deduct_quantity(qty_to_pick)

        if component_to_pick.quantity == 0:
            self.contents.remove(component_to_pick)

        self.update_used_volume_cm3()
        return picked_qty

    def get_component_quantity(self, part_id: str) -> int:
        component = next((c for c in self.contents if c.part_id == part_id), None)
        return component.quantity if component else 0

    def has_part(self, part_id: str) -> bool:
        return self.get_component_quantity(part_id) > 0

    def is_empty(self) -> bool:
        return len(self.contents) == 0

    def get_part_summary(self) -> Dict[str, int]:
        return {c.part_id: c.quantity for c in self.contents}


class KitStatus:
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class Kit:
    kit_id: str
    source_plan_index: Optional[int] = None
    line: Optional[str] = None
    start_time_sec: Optional[int] = None
    product: Optional[str] = None
    qty: Optional[int] = None
    station_id: Optional[str] = None
    station_position_x: Optional[float] = None
    station_position_y: Optional[float] = None
    required_parts: Dict[str, int] = field(default_factory=dict)
    status: str = KitStatus.WAITING  # waiting, in_progress, completed
    kit_dimensions_cm: Dict[str, Any] = field(default_factory=dict)
    kit_total_capacity_cm3: int = KitSpec.TOTAL_CAPACITY_CM3
    required_volume_cm3: Optional[int] = None
    filled_parts: Dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Kit":
        req_parts = d.get("required_parts", {})
        filled_parts = d.get("filled_parts") or {p: 0 for p in req_parts.keys()}
        return cls(
            kit_id=d.get("kit_id", ""),
            source_plan_index=d.get("source_plan_index"),
            line=d.get("line"),
            start_time_sec=d.get("start_time_sec"),
            product=d.get("product"),
            qty=d.get("qty"),
            station_id=d.get("station_id"),
            station_position_x=d.get("station_position_x"),
            station_position_y=d.get("station_position_y"),
            required_parts=d.get("required_parts", {}),
            status=d.get("status", "waiting"),
            kit_dimensions_cm=d.get("kit_dimensions_cm", {}),
            kit_total_capacity_cm3=d.get(
                "kit_total_capacity_cm3", KitSpec.TOTAL_CAPACITY_CM3
            ),
            required_volume_cm3=d.get("required_volume_cm3"),
            filled_parts=filled_parts,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kit_id": self.kit_id,
            "source_plan_index": self.source_plan_index,
            "line": self.line,
            "start_time_sec": self.start_time_sec,
            "product": self.product,
            "qty": self.qty,
            "station_id": self.station_id,
            "station_position_x": self.station_position_x,
            "station_position_y": self.station_position_y,
            "required_parts": self.required_parts,
            "status": self.status,
            "kit_dimensions_cm": self.kit_dimensions_cm,
            "kit_total_capacity_cm3": self.kit_total_capacity_cm3,
            "required_volume_cm3": self.required_volume_cm3,
            "filled_parts": self.filled_parts,
        }

    def add_parts(self, part_id: str, quantity: int) -> None:
        self.filled_parts[part_id] = self.filled_parts.get(part_id, 0) + quantity
        if self.is_completed():
            self.status = "completed"

    def is_completed(self) -> bool:
        for part_id, req_qty in self.required_parts.items():
            if self.filled_parts.get(part_id, 0) < req_qty:
                return False
        return True

    def get_remaining_parts(self) -> Dict[str, int]:
        remaining_parts = {}
        for part_id, req_qty in self.required_parts.items():
            filled_qty = self.filled_parts.get(part_id, 0)
            remaining_qty = req_qty - filled_qty
            if remaining_qty > 0:
                remaining_parts[part_id] = remaining_qty
        return remaining_parts


class StationStatus:
    IDLE = "idle"
    KITTING = "kitting"
    KIT_CHANGING = "kit_changing"


@dataclass
class KittingStation:
    station_id: str
    position_x: float
    position_y: float
    assigned_agv_count: int = 0
    status: str = StationStatus.IDLE
    assigned_kit: Optional[Kit] = None
    completed_kits: List[Kit] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "KittingStation":
        return cls(
            station_id=d.get("station_id", ""),
            position_x=float(d.get("position_x", 0.0)),
            position_y=float(d.get("position_y", 0.0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "station_id": self.station_id,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "assigned_agv_count": self.assigned_agv_count,
            "status": self.status,
            "assigned_kit_id": self.assigned_kit.kit_id if self.assigned_kit else None,
            "completed_kits_count": len(self.completed_kits),
        }

    def assign_kit(self, kit: Kit) -> None:
        if self.assigned_kit is not None:
            raise ValueError(
                f"Station {self.station_id} already has an assigned kit {self.assigned_kit.kit_id}."
            )
        self.assigned_kit = kit
        self.status = StationStatus.KITTING

    def complete_kit(self) -> Optional[Kit]:
        completed = self.assigned_kit
        if not completed:
            return None

        self.assigned_kit = None
        self.status = StationStatus.KIT_CHANGING
        self.completed_kits.append(completed)

        return completed

    def increment_agv_count(self) -> None:
        if self.assigned_agv_count >= 2:
            raise ValueError(
                f"Station {self.station_id} cannot have more than 2 AGVs assigned."
            )
        self.assigned_agv_count += 1

    def decrement_agv_count(self) -> None:
        if self.assigned_agv_count <= 0:
            raise ValueError(
                f"Station {self.station_id} cannot have negative AGV count."
            )
        self.assigned_agv_count -= 1

    def can_accept_agv(self) -> bool:
        return self.assigned_agv_count < 2

    def has_active_kit(self) -> bool:
        return self.assigned_kit is not None


class AGVStatus:
    IDLE = "idle"
    MOVING_TO_STORAGE = "moving_to_storage"
    MOVING_TO_STATION = "moving_to_station"
    WAITING = "waiting"
    DOCKING = "docking"
    RETURNING_TO_STORAGE = "returning_to_storage"


# [1. idle]
#   └─ (작업 할당) ──> [2. moving_to_storage]
#                          └─ (토트 적재 완료) ──> [3. moving_to_station]
#                                                        │
#                                      ┌─────────────────┴─────────────────┐
#                             (스테이션 점유 중)                   (스테이션 비어있음)
#                                      ▼                                   ▼
#                              [5. waiting] ──(앞 AGV 완료)──> [4. docking / working]
#                                                                          │
# [7. idle] <──(대기 상태 복귀)── [6. returning_to_storage] <──(피킹/작업 완료)──┘


@dataclass
class AGV:
    agv_id: str
    position_x: float = 0.0
    position_y: float = 0.0
    status: str = AGVStatus.IDLE

    carried_tote: Optional[Tote] = None
    target_storage_id: Optional[str] = None
    target_station_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AGV":
        return cls(
            agv_id=d.get("agv_id") or d.get("id", ""),
            position_x=float(
                d.get("initial_position_x", d.get("position_x", 0.0)) or 0.0
            ),
            position_y=float(
                d.get("initial_position_y", d.get("position_y", 0.0)) or 0.0
            ),
            status=d.get("status", AGVStatus.IDLE),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agv_id": self.agv_id,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "status": self.status,
            "carried_tote_id": self.carried_tote.tote_id if self.carried_tote else None,
            "target_storage_id": self.target_storage_id,
            "target_station_id": self.target_station_id,
        }

    def assign_task(self, storage_id: str, station_id: str) -> None:
        self.target_storage_id = storage_id
        self.target_station_id = station_id
        self.status = AGVStatus.MOVING_TO_STORAGE

    def head_to_station(self) -> None:
        self.status = AGVStatus.MOVING_TO_STATION

    def wait_in_queue(self) -> None:
        self.status = AGVStatus.WAITING

    def start_docking(self) -> None:
        self.status = AGVStatus.DOCKING

    def return_to_storage(self) -> None:
        self.status = AGVStatus.RETURNING_TO_STORAGE

    def complete_task(self) -> None:
        self.status = AGVStatus.IDLE
        self.target_storage_id = None
        self.target_station_id = None

    def update_position(self, x: float, y: float) -> None:
        self.position_x = x
        self.position_y = y

    def load_tote(self, tote: Tote) -> None:
        if self.carried_tote is not None:
            raise ValueError(
                f"AGV {self.agv_id} is already carrying tote {self.carried_tote.tote_id}."
            )
        self.carried_tote = tote

    def unload_tote(self) -> Tote:
        if self.carried_tote is None:
            raise ValueError(f"AGV {self.agv_id} is not carrying any tote.")
        tote = self.carried_tote
        self.carried_tote = None
        return tote

    def is_idle(self) -> bool:
        return self.status == AGVStatus.IDLE


@dataclass(frozen=True)
class DispatchCandidate:
    tote: Tote
    station: KittingStation
    kit: Kit
    matched_parts: Dict[str, int]
