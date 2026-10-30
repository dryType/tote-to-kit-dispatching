"""정보시각화 텀프로젝트용 시뮬레이션 로그 추출.

시뮬레이터 코드는 고치지 않는다. 대신 아래 세 가지를 붙인다.

- CandidateLogPolicy   기존 정책을 감싸서, 결정마다 후보 전체의 "정책 무관 특징"을 csv.gz로 흘려 쓴다.
                       (정책별 점수가 아니라 거리·기여도·토트 단편화 변화량 같은 공통 기준이라
                        Greedy / CPR / NewCPR / ATC-CPR 를 같은 축에서 비교할 수 있다)
- attach_task_end_log  AGV.finish_task 를 감싸서 작업 종료(토트 반납 완료) 시각을 남긴다.
- attach_dock_wait_log AGV.start_waiting 과 station.dock.request 를 감싸서 대기 시작 / 도크 허락 시각을 남긴다.
- export_tables        실행이 끝난 Simulator 에서 시각화용 테이블을 뽑는다.

출력 (out_dir/)
    meta.json              실행 요약 + 단편화 지수 검증값 + 컬럼 정의 + 검증 결과
    totes.csv              토트 1개 = 1행 (위치, 초기/최종 상태, 방문 수)
    tote_sku.csv           토트 × 부품 (초기/최종 수량, 카톤, 데드스페이스)
    kits.csv               키트 1개 = 1행 (스테이션, 납기, 시작/완료, 지연)
    kit_sku.csv            키트 × 부품 (필요 수량, lot_size, 필요 카톤 수)
    stations.csv           스테이션 1개 = 1행
    dispatches.csv         디스패치 1건 = 1행 (AGV 왕복 시각, 도킹 대기, 정책 점수, 선택 후보 특징)
    decisions.csv          결정 1회 = 1행 (후보 수, 선택 후보의 특징별 순위)
    inventory_events.csv   토트×부품 재고 변화 1건 = 1행 (+ 그 시점 전체 단편화 지수)
    candidates.csv.gz      결정 × 후보 (정책 무관 특징, 선택 여부)

사용 예 (레포 루트에서):
    python src/simulation_engine/vis_export.py --size medium --seed 42 --load 0.8 \
        --policies greedy cpr new_cpr --out vis_data
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from pathlib import Path
from typing import Any

# 스크립트로 바로 실행해도 import 되도록 (load_validation.py 와 같은 방식)
REPO_DIR = Path(__file__).resolve().parents[2]
for _p in (REPO_DIR / "src", REPO_DIR / "data"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from policy.base_policy import BasePolicy  # noqa: E402

# Metrics.calc_fragmentation_index 와 같은 가중치
WF1, WF2 = 0.3, 0.7

BASE_DISPATCH_KEYS = {"type", "time", "agv_id", "tote_id", "station_id", "kit_id", "matched_parts"}

CANDIDATE_COLUMNS = [
    "decision_id", "time", "station_id", "kit_id", "tote_id", "chosen",
    "matched_qty", "matched_sku", "contribution", "completes_kit",
    "kit_progress", "kit_slack_sec", "distance_m",
    "n_sku_before", "n_sku_after", "sku_emptied", "tote_emptied",
    "partial_before", "partial_after", "dead_before", "dead_after",
    "used_ratio_before", "used_ratio_after", "frag_before", "frag_after", "d_frag",
]

# 결정 요약에서 선택 후보의 순위를 매길 특징 (True = 작을수록 1등)
RANK_FEATURES = {
    "distance_m": True,
    "d_frag": True,
    "contribution": False,
    "kit_slack_sec": True,
}


# ----------------------------------------------------------------------
# 카톤 / 토트 단편화 계산 (Component.deduct_quantity, Tote 메서드와 같은 식)
# ----------------------------------------------------------------------

def _num(v, default=0):
    return default if v is None else v


def carton_state(qty: int, lot: int, v_part: float, v_carton: float) -> tuple[int, int, float]:
    """(카톤 수, 마지막 카톤이 덜 찼는지 0/1, 데드스페이스 cm3)."""
    if qty <= 0:
        return 0, 0, 0.0
    lot = max(1, int(_num(lot, 1)))
    cartons = math.ceil(qty / lot)
    rem = qty % lot
    dead = 0.0 if rem == 0 else _num(v_carton) - rem * _num(v_part)
    return cartons, int(rem != 0), dead


def tote_profile(comps: list[tuple[int, int, float, float]], capacity: float) -> dict[str, float]:
    """comps: (수량, lot, v_part, v_carton) 목록. 수량 0인 부품은 없는 것으로 본다."""
    used = dead = 0.0
    partial = n = 0
    for qty, lot, vp, vc in comps:
        if qty <= 0:
            continue
        c, p, d = carton_state(qty, lot, vp, vc)
        used += c * _num(vc)
        dead += d
        partial += p
        n += 1
    if n == 0:
        return {"n_sku": 0, "used_ratio": 0.0, "dead_ratio": 0.0, "dead": 0.0, "partial": 0, "frag": 0.0}
    used_ratio = used / capacity
    dead_ratio = dead / capacity
    return {
        "n_sku": n,
        "used_ratio": used_ratio,
        "dead_ratio": dead_ratio,
        "dead": dead,
        "partial": partial,
        "frag": WF1 * (1 - used_ratio) + WF2 * dead_ratio,
    }


def fill_state(used_ratio: float, n_sku: int) -> str:
    """Metrics.calc_tote_state_counts 기준 (카톤 점유 부피 / 토트 용량)."""
    if n_sku == 0:
        return "Empty"
    if used_ratio >= 0.8:
        return "Full"
    if used_ratio >= 0.3:
        return "Partial"
    return "Residual"


def _comps_of(tote) -> list[tuple[int, int, float, float]]:
    return [(c.quantity, c.lot_size, c.v_part, c.v_carton) for c in tote.contents]


def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


# ----------------------------------------------------------------------
# 후보 로깅 래퍼
# ----------------------------------------------------------------------

class CandidateLogPolicy(BasePolicy):
    """정책을 감싸서 결정마다 후보 특징을 남긴다. 선택 결과는 감싼 정책 그대로다."""

    def __init__(self, inner: BasePolicy, candidates_path: str | Path | None = None):
        self.inner = inner
        self.decision_id = 0
        self.decisions: list[dict[str, Any]] = []
        self.chosen_features: dict[int, dict[str, Any]] = {}  # dispatch_seq -> 선택 후보 특징
        self.n_candidate_rows = 0
        self._fh = None
        self._writer = None
        if candidates_path is not None:
            Path(candidates_path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = gzip.open(candidates_path, "wt", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(CANDIDATE_COLUMNS)

    def __getattr__(self, item):
        # update_station_caps 같은 선택적 훅은 감싼 정책으로 넘긴다
        if item == "inner":
            raise AttributeError(item)
        return getattr(self.inner, item)

    @property
    def name(self) -> str:
        return self.inner.name

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def select(self, now, candidates, idle_agvs, state, dispatched_count: int = 0):
        chosen, agv = self.inner.select(now, candidates, idle_agvs, state, dispatched_count)
        did = self.decision_id
        self.decision_id += 1
        chosen_key = (chosen.station.station_id, chosen.tote.tote_id) if chosen is not None else None

        rows = self._features(now, candidates, idle_agvs, did, chosen_key)

        summary: dict[str, Any] = {
            "decision_id": did,
            "time": _r(now, 3),
            "dispatch_seq": dispatched_count if chosen is not None else None,
            "n_candidates": len(rows),
            "n_stations_open": len({r["station_id"] for r in rows}),
            "n_kits_open": len({r["kit_id"] for r in rows}),
            "n_idle_agvs": len(idle_agvs),
        }
        chosen_row = next((r for r in rows if r["chosen"]), None)
        if chosen_row is not None:
            n = len(rows)
            for feat, ascending in RANK_FEATURES.items():
                v = chosen_row[feat]
                better = sum(1 for r in rows if (r[feat] < v if ascending else r[feat] > v))
                summary[f"rank_{feat}"] = better + 1
                summary[f"pct_{feat}"] = _r(better / (n - 1)) if n > 1 else 0.0
            self.chosen_features[dispatched_count] = chosen_row
        self.decisions.append(summary)

        if self._writer is not None:
            for r in rows:
                self._writer.writerow([r[c] for c in CANDIDATE_COLUMNS])
        self.n_candidate_rows += len(rows)
        return chosen, agv

    @staticmethod
    def _features(now, candidates, idle_agvs, did, chosen_key) -> list[dict[str, Any]]:
        idle_pos = [a.position for a in idle_agvs if a.position is not None]
        kit_cache: dict[str, tuple[dict[str, int], int, float, float]] = {}
        tote_cache: dict[str, dict[str, float]] = {}
        rows = []
        for c in candidates:
            kit, tote, station = c.kit, c.tote, c.station
            if kit.kit_id not in kit_cache:
                remaining = kit.get_remaining_parts()
                kit_cache[kit.kit_id] = (
                    remaining,
                    sum(remaining.values()),
                    kit.get_reserved_progress_ratio(),
                    float(_num(kit.deadline_time_sec)) - now,
                )
            remaining, remaining_total, progress, slack = kit_cache[kit.kit_id]

            if tote.tote_id not in tote_cache:
                tote_cache[tote.tote_id] = tote_profile(_comps_of(tote), tote.max_capacity_cm3)
            before = tote_cache[tote.tote_id]

            # 꺼낸 뒤 토트 상태 (pick_part 처럼 같은 부품은 첫 항목에서만 뺀다)
            left = dict(c.matched_parts)
            after_comps = []
            emptied = 0
            for comp in tote.contents:
                x = left.pop(comp.part_id, 0)
                q = comp.quantity - x
                if x > 0 and q <= 0:
                    emptied += 1
                after_comps.append((q, comp.lot_size, comp.v_part, comp.v_carton))
            after = tote_profile(after_comps, tote.max_capacity_cm3)

            matched_qty = sum(c.matched_parts.values())
            if idle_pos and tote.position is not None and station.position is not None:
                empty_leg = min(p.manhattan_distance_to(tote.position) for p in idle_pos)
                distance = empty_leg + 2 * tote.position.manhattan_distance_to(station.position)
            else:
                distance = None

            rows.append({
                "decision_id": did,
                "time": _r(now, 3),
                "station_id": station.station_id,
                "kit_id": kit.kit_id,
                "tote_id": tote.tote_id,
                "chosen": int((station.station_id, tote.tote_id) == chosen_key),
                "matched_qty": matched_qty,
                "matched_sku": len(c.matched_parts),
                "contribution": _r(matched_qty / remaining_total) if remaining_total else 0.0,
                "completes_kit": int(matched_qty >= remaining_total > 0),
                "kit_progress": _r(progress),
                "kit_slack_sec": _r(slack, 2),
                "distance_m": _r(distance, 2),
                "n_sku_before": before["n_sku"],
                "n_sku_after": after["n_sku"],
                "sku_emptied": emptied,
                "tote_emptied": int(after["n_sku"] == 0),
                "partial_before": before["partial"],
                "partial_after": after["partial"],
                "dead_before": _r(before["dead"], 1),
                "dead_after": _r(after["dead"], 1),
                "used_ratio_before": _r(before["used_ratio"]),
                "used_ratio_after": _r(after["used_ratio"]),
                "frag_before": _r(before["frag"], 5),
                "frag_after": _r(after["frag"], 5),
                "d_frag": _r(after["frag"] - before["frag"], 5),
            })
        return rows


# ----------------------------------------------------------------------
# AGV 작업 종료 시각
# ----------------------------------------------------------------------

def attach_task_end_log(sim) -> list[dict[str, Any]]:
    """AGV.finish_task 를 감싸서 (agv, 종료 시각, 작업 시작 시각)을 남긴다."""
    log: list[dict[str, Any]] = []
    for agv in sim.agvs:
        original = agv.finish_task

        def wrapped(now, _agv=agv, _orig=original):
            log.append({
                "agv_id": _agv.agv_id,
                "task_end": now,
                "task_start": _agv.last_start_time,
                "station_id": _agv.target_station.station_id if _agv.target_station else None,
            })
            return _orig(now)

        agv.finish_task = wrapped
    return log


# ----------------------------------------------------------------------
# 도킹 대기 시각
# ----------------------------------------------------------------------

def attach_dock_wait_log(sim) -> list[dict[str, Any]]:
    """AGV.start_waiting 과 station.dock.request 를 감싸서 (agv, 대기 시작, 도크 허락 시각)을 남긴다.

    agv_transport_process 에서 start_waiting() 바로 다음 줄이 dock.request() 이고 그 사이에 yield 가 없다.
    그래서 스테이션별로 "방금 대기를 시작한 AGV" 하나만 들고 있다가 그 요청에 붙이면 된다.
    허락 시각은 요청 이벤트의 콜백이 처리되는 순간의 env.now 다 (바로 허락되면 대기 시작과 같은 시각).
    """
    log: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}  # station_id -> 방금 대기를 시작한 기록

    for agv in sim.agvs:
        original = agv.start_waiting

        def wrapped(_agv=agv, _orig=original):
            rec = {
                "agv_id": _agv.agv_id,
                "station_id": _agv.target_station.station_id,
                "wait_start": sim.env.now,
                "dock_grant": None,
            }
            log.append(rec)
            pending[rec["station_id"]] = rec
            return _orig()

        agv.start_waiting = wrapped

    for station in sim.stations:
        original_request = station.dock.request

        def request(_sid=station.station_id, _orig=original_request):
            event = _orig()
            rec = pending.pop(_sid, None)
            if rec is not None:
                event.callbacks.append(lambda _e, _rec=rec: _rec.__setitem__("dock_grant", sim.env.now))
            return event

        station.dock.request = request
    return log


# ----------------------------------------------------------------------
# 테이블 추출
# ----------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if columns is None:
        columns = []
        for r in rows:
            for k in r:
                if k not in columns:
                    columns.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _build_trips(events, task_end_log, dock_wait_log=None) -> list[dict[str, Any]]:
    """AGV는 한 번에 작업 하나만 하므로, AGV별 k번째 dispatch / 대기 / 도킹 / 이송 완료 / 반납이 같은 왕복이다."""
    per_agv: dict[str, dict[str, list]] = {}

    def bucket(agv_id):
        return per_agv.setdefault(
            agv_id, {"dispatch": [], "wait": [], "kitting_started": [], "kitting_completed": [], "end": []}
        )

    seq = 0
    for e in events:
        if e["type"] == "dispatch":
            e = dict(e, dispatch_seq=seq)
            seq += 1
            bucket(e["agv_id"])["dispatch"].append(e)
        elif e["type"] in ("kitting_started", "kitting_completed"):
            bucket(e["agv_id"])[e["type"]].append(e)
    for t in task_end_log:
        bucket(t["agv_id"])["end"].append(t)
    for w in dock_wait_log or []:
        bucket(w["agv_id"])["wait"].append(w)

    trips = []
    for agv_id, b in per_agv.items():
        for k, d in enumerate(b["dispatch"]):
            wt = b["wait"][k] if k < len(b["wait"]) else None
            ks = b["kitting_started"][k] if k < len(b["kitting_started"]) else None
            kc = b["kitting_completed"][k] if k < len(b["kitting_completed"]) else None
            en = b["end"][k] if k < len(b["end"]) else None
            trips.append({
                "dispatch": d,
                "wait_start": wt["wait_start"] if wt else None,
                "dock_grant": wt["dock_grant"] if wt else None,
                "kitting_start": ks["time"] if ks else None,
                "kitting_end": kc["time"] if kc else None,
                "transferred_parts": kc["transferred_parts"] if kc else None,
                "kit_completed_here": kc["completed"] if kc else None,
                "task_end": en["task_end"] if en else None,
            })
    trips.sort(key=lambda t: t["dispatch"]["dispatch_seq"])
    return trips


def export_tables(sim, metrics, out_dir: str | Path, label: str, task_end_log=None,
                  policy: CandidateLogPolicy | None = None, extra_meta: dict | None = None,
                  dock_wait_log=None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if policy is not None:
        policy.close()

    events = metrics.event_logs
    trips = _build_trips(events, task_end_log or [], dock_wait_log)
    totes = list(sim.totes)
    tote_by_id = {t.tote_id: t for t in totes}
    n_totes = len(totes)

    # --- 초기 재고에서 출발해 이송 완료 이벤트로 재고를 다시 굴린다 ---------------------
    state: dict[str, dict[str, list]] = {}  # tote_id -> part_id -> [qty, lot, v_part, v_carton]
    tote_sku_rows: dict[tuple[str, str], dict[str, Any]] = {}
    tote_frag: dict[str, float] = {}
    for t in totes:
        parts: dict[str, list] = {}
        for c in t.initial_contents:
            if c.part_id in parts:  # 중복 부품은 첫 항목만 (pick_part 와 같게)
                continue
            parts[c.part_id] = [c.quantity, c.lot_size, c.v_part, c.v_carton]
            cartons, partial, dead = carton_state(c.quantity, c.lot_size, c.v_part, c.v_carton)
            tote_sku_rows[(t.tote_id, c.part_id)] = {
                "tote_id": t.tote_id, "part_id": c.part_id,
                "lot_size": c.lot_size, "v_part": c.v_part, "v_carton": c.v_carton,
                "qty_init": c.quantity, "cartons_init": cartons, "partial_init": partial, "dead_init": _r(dead, 1),
                "n_picks": 0, "qty_picked": 0,
            }
        state[t.tote_id] = parts
        tote_frag[t.tote_id] = tote_profile(list(map(tuple, parts.values())), t.max_capacity_cm3)["frag"]

    frag_sum = sum(tote_frag.values())
    frag_index_init = frag_sum / n_totes if n_totes else 0.0

    inventory_rows = []
    for trip in sorted((t for t in trips if t["kitting_end"] is not None), key=lambda t: t["kitting_end"]):
        d = trip["dispatch"]
        tid = d["tote_id"]
        tote = tote_by_id[tid]
        for part_id, qty in trip["transferred_parts"].items():
            rec = state[tid][part_id]
            before = carton_state(*rec)
            rec[0] -= qty
            after = carton_state(*rec)
            row = tote_sku_rows[(tid, part_id)]
            row["n_picks"] += 1
            row["qty_picked"] += qty
            inventory_rows.append({
                "time": _r(trip["kitting_end"], 3),
                "dispatch_seq": d["dispatch_seq"],
                "tote_id": tid, "part_id": part_id,
                "kit_id": d["kit_id"], "station_id": d["station_id"],
                "qty_picked": qty, "qty_before": rec[0] + qty, "qty_after": rec[0],
                "cartons_before": before[0], "cartons_after": after[0],
                "partial_before": before[1], "partial_after": after[1],
                "dead_before": _r(before[2], 1), "dead_after": _r(after[2], 1),
            })
        new_frag = tote_profile(list(map(tuple, state[tid].values())), tote.max_capacity_cm3)["frag"]
        frag_sum += new_frag - tote_frag[tid]
        tote_frag[tid] = new_frag
        # 같은 이송의 마지막 행에 이송 직후 토트/전체 단편화를 붙인다
        inventory_rows[-1]["tote_frag_after"] = _r(new_frag, 5)
        inventory_rows[-1]["frag_index_after"] = _r(frag_sum / n_totes, 6)

    frag_index_final = frag_sum / n_totes if n_totes else 0.0

    # --- totes / tote_sku -------------------------------------------------------------
    tote_rows = []
    for t in totes:
        init = tote_profile([(c.quantity, c.lot_size, c.v_part, c.v_carton) for c in t.initial_contents],
                            t.max_capacity_cm3)
        final = tote_profile(list(map(tuple, state[t.tote_id].values())), t.max_capacity_cm3)
        hist = t.assigned_history
        if not hist:
            life = "untouched"
        elif final["n_sku"] == 0:
            life = "emptied"
        else:
            life = "opened_left"
        tote_rows.append({
            "tote_id": t.tote_id,
            "x": t.position.x if t.position else None,
            "y": t.position.y if t.position else None,
            "n_sku_init": init["n_sku"], "used_ratio_init": _r(init["used_ratio"]),
            "dead_ratio_init": _r(init["dead_ratio"]), "partial_init": init["partial"],
            "frag_init": _r(init["frag"], 5), "fill_state_init": fill_state(init["used_ratio"], init["n_sku"]),
            "n_visits": len(hist), "n_kits_served": len({h[0] for h in hist}),
            "first_visit": _r(hist[0][2], 3) if hist else None,
            "last_visit": _r(hist[-1][2], 3) if hist else None,
            "n_sku_final": final["n_sku"], "used_ratio_final": _r(final["used_ratio"]),
            "dead_ratio_final": _r(final["dead_ratio"]), "partial_final": final["partial"],
            "frag_final": _r(final["frag"], 5), "fill_state_final": fill_state(final["used_ratio"], final["n_sku"]),
            "lifecycle": life,
        })
    for (tid, pid), row in tote_sku_rows.items():
        rec = state[tid][pid]
        cartons, partial, dead = carton_state(*rec)
        row.update({"qty_final": rec[0], "cartons_final": cartons, "partial_final": partial, "dead_final": _r(dead, 1)})

    # --- kits -------------------------------------------------------------------------
    om = sim.order_manager
    release_order = {k.kit_id: i for i, k in enumerate(om.activated_kits)}
    kit_rows = []
    for k in om.get_all_kits():
        hist = k.tote_reservation_history
        done = k.completed_time_sec is not None
        lateness = (k.completed_time_sec - k.deadline_time_sec) if done else None
        kit_rows.append({
            "kit_id": k.kit_id, "product": k.product, "line": k.line, "qty": k.qty,
            "station_id": k.assigned_station.station_id if k.assigned_station else None,
            "release_order": release_order.get(k.kit_id),
            "deadline": k.deadline_time_sec,
            "start": _r(k.started_time_sec, 3), "completion": _r(k.completed_time_sec, 3),
            "lead_time": _r(k.completed_time_sec - k.started_time_sec, 3) if done else None,
            "lateness": _r(lateness, 3), "tardiness": _r(max(0.0, lateness), 3) if done else None,
            "completed": int(done),
            "n_sku_required": len(k.required_parts), "qty_required": sum(k.required_parts.values()),
            "required_volume_cm3": k.required_volume_cm3,
            "n_dispatch": len(hist), "n_totes": len({h["tote_id"] for h in hist}),
        })

    # --- kit_sku: 키트 × 부품. lot_size 는 부품마다 하나 (토트가 달라도 같다) ------------------
    lot_by_sku: dict[str, int] = {}
    for (_, pid), row in tote_sku_rows.items():
        lot_by_sku.setdefault(pid, row["lot_size"])
    kit_sku_rows = []
    for k in om.get_all_kits():
        for pid, q in k.required_parts.items():
            lot = lot_by_sku.get(pid)  # 어느 토트에도 없는 부품이면 None
            kit_sku_rows.append({
                "kit_id": k.kit_id, "sku": pid, "qty_required": q, "lot_size": lot,
                "cartons_needed": _r(q / lot) if lot else None,
            })

    # --- stations ---------------------------------------------------------------------
    station_rows = []
    for s in sim.stations:
        active = s.active_kit_total_time_sec
        station_rows.append({
            "station_id": s.station_id,
            "x": s.position.x if s.position else None, "y": s.position.y if s.position else None,
            "n_kits": len(s.completed_kits),
            "active_kit_time": _r(active, 1), "dock_time": _r(s.dock_occupied_total_time_sec, 1),
            "dock_ratio": _r(s.dock_occupied_total_time_sec / active) if active > 0 else None,
        })

    # --- dispatches -------------------------------------------------------------------
    counts = metrics.tote_state_counts  # dispatch 마다 하나씩, 같은 순서
    chosen = policy.chosen_features if policy is not None else {}
    dispatch_rows = []
    for trip in trips:
        d = trip["dispatch"]
        seq = d["dispatch_seq"]
        ws, dg = trip["wait_start"], trip["dock_grant"]
        # 카톤 일부만 꺼낸 부품 수 (kitting_process 의 partial_carton_count 와 같은 조건)
        partial_picks = sum(
            1 for pid, q in d["matched_parts"].items()
            if q % max(1, int(_num(tote_sku_rows[(d["tote_id"], pid)]["lot_size"], 1))) != 0
        )
        row = {
            "dispatch_seq": seq, "time": _r(d["time"], 3),
            "agv_id": d["agv_id"], "tote_id": d["tote_id"], "station_id": d["station_id"], "kit_id": d["kit_id"],
            "matched_qty": sum(d["matched_parts"].values()), "matched_sku": len(d["matched_parts"]),
            "matched_parts": json.dumps(d["matched_parts"], ensure_ascii=False),
            "partial_picks": partial_picks,
            "wait_start": _r(ws, 3), "dock_grant": _r(dg, 3),
            # 도크 허락 - 대기 시작 = kitting_start - wait_start - (대기 위치 -> 도킹 위치 이동시간)
            "dock_wait": _r(dg - ws, 3) if ws is not None and dg is not None else None,
            "kitting_start": _r(trip["kitting_start"], 3), "kitting_end": _r(trip["kitting_end"], 3),
            "task_end": _r(trip["task_end"], 3),
            "kit_completed_here": None if trip["kit_completed_here"] is None else int(trip["kit_completed_here"]),
        }
        if seq < len(counts):
            row.update({f"after_{k.lower()}": v for k, v in counts[seq].items()})
        for k, v in d.items():
            if k not in BASE_DISPATCH_KEYS and k != "dispatch_seq":
                row[f"score_{k}"] = v
        feat = chosen.get(seq)
        if feat:
            row["decision_id"] = feat["decision_id"]
            for k in ("contribution", "completes_kit", "kit_progress", "kit_slack_sec", "distance_m",
                      "sku_emptied", "tote_emptied", "partial_before", "partial_after", "d_frag"):
                row[k] = feat[k]
        dispatch_rows.append(row)

    # --- 쓰기 ---------------------------------------------------------------------------
    _write_csv(out / "totes.csv", tote_rows)
    _write_csv(out / "tote_sku.csv", list(tote_sku_rows.values()))
    _write_csv(out / "kits.csv", kit_rows)
    _write_csv(out / "kit_sku.csv", kit_sku_rows, ["kit_id", "sku", "qty_required", "lot_size", "cartons_needed"])
    _write_csv(out / "stations.csv", station_rows)
    _write_csv(out / "dispatches.csv", dispatch_rows)
    _write_csv(out / "inventory_events.csv", inventory_rows, [
        "time", "dispatch_seq", "tote_id", "part_id", "kit_id", "station_id", "qty_picked",
        "qty_before", "qty_after", "cartons_before", "cartons_after", "partial_before", "partial_after",
        "dead_before", "dead_after", "tote_frag_after", "frag_index_after",
    ])
    if policy is not None:
        _write_csv(out / "decisions.csv", policy.decisions)

    kits_done = [r for r in kit_rows if r["completed"]]
    meta = {
        "label": label,
        "policy": getattr(policy, "name", None) if policy is not None else getattr(metrics.policy, "name", None),
        "n_totes": n_totes, "n_kits": len(kit_rows), "n_stations": len(sim.stations), "n_agvs": len(sim.agvs),
        "n_sku": len({pid for (_, pid) in tote_sku_rows}),
        "makespan": getattr(metrics, "makespan", None),
        "n_dispatch": metrics.dispatched_count,
        "total_agv_move_distance": metrics.total_agv_move_distance,
        "n_decisions": policy.decision_id if policy is not None else None,
        "n_candidate_rows": policy.n_candidate_rows if policy is not None else None,
        "completed_kits": len(kits_done),
        "tardy_kits": sum(1 for r in kits_done if r["tardiness"] and r["tardiness"] > 1e-6),
        "total_tardiness": sum(r["tardiness"] or 0 for r in kits_done),
        "totes_touched": sum(1 for r in tote_rows if r["lifecycle"] != "untouched"),
        "totes_opened_left": sum(1 for r in tote_rows if r["lifecycle"] == "opened_left"),
        "totes_emptied": sum(1 for r in tote_rows if r["lifecycle"] == "emptied"),
        "frag_index_init": frag_index_init,
        "frag_index_final": frag_index_final,
        # 재계산 값이 Metrics 값과 같아야 한다 (다르면 인스턴스의 초기 데드스페이스 정의가 식과 다른 것)
        "check_metrics_frag_init": metrics.initial_frag_index,
        "check_metrics_frag_final": metrics.calc_fragmentation_index(),
        "definitions": {
            "wait_start": "AGV.start_waiting() 호출 시각 (스테이션 대기 위치 도착), s",
            "dock_grant": "station.dock.request() 가 허락된 시각, s",
            "dock_wait": "dock_grant - wait_start = kitting_start - wait_start - (대기 위치 -> 도킹 위치 이동시간), s",
            "partial_picks": "그 트립의 matched_parts 중 qty % lot_size != 0 인 부품 수",
            "cartons_needed": "qty_required / lot_size (올림하지 않은 실수)",
        },
        "checks": _checks(dispatch_rows, kit_rows, kit_sku_rows, metrics, sim),
        **(extra_meta or {}),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _checks(dispatch_rows, kit_rows, kit_sku_rows, metrics, sim) -> dict[str, Any]:
    """추출 테이블 검증. ok 가 False 인 항목이 있으면 main 에서 경고를 찍는다."""
    from config.constants import AGVSpec

    waits = [r["dock_wait"] for r in dispatch_rows]
    kit_sum: dict[str, int] = {}
    for r in kit_sku_rows:
        kit_sum[r["kit_id"]] = kit_sum.get(r["kit_id"], 0) + r["qty_required"]
    kit_mismatch = [r["kit_id"] for r in kit_rows if kit_sum.get(r["kit_id"], 0) != r["qty_required"]]

    # 교란이 없으면 kitting_start - dock_grant 가 명목 이동시간(2 m / 속도)과 같아야 한다
    move = {s.station_id: s.waiting_position.manhattan_distance_to(s.position) / AGVSpec.SPEED_M_PER_S
            for s in sim.stations}
    resid = [abs(r["kitting_start"] - r["dock_grant"] - move[r["station_id"]])
             for r in dispatch_rows if r["kitting_start"] is not None and r["dock_grant"] is not None]
    return {
        "dispatch_rows_equal_n_dispatch": {
            "ok": len(dispatch_rows) == metrics.dispatched_count,
            "rows": len(dispatch_rows), "n_dispatch": metrics.dispatched_count,
        },
        "dock_wait_nonnegative": {
            "ok": all(w is not None and w >= 0 for w in waits),
            "n_missing": sum(1 for w in waits if w is None),
            "min": min((w for w in waits if w is not None), default=None),
            "max": max((w for w in waits if w is not None), default=None),
        },
        "kit_sku_sum_equals_kits_qty_required": {"ok": not kit_mismatch, "mismatched_kits": kit_mismatch},
        "dock_move_time_residual": {
            "nominal_sec": sorted(set(round(v, 6) for v in move.values())),
            "max_abs_residual_sec": round(max(resid), 6) if resid else None,
            "note": "교란(dist_cv>0)이 있으면 이동시간이 바뀌므로 0이 아닐 수 있다",
        },
    }


# ----------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------

def run_and_export(sim_builder, inner_policy: BasePolicy, out_dir: str | Path, label: str,
                   log_candidates: bool = True, extra_meta: dict | None = None) -> dict:
    """sim_builder(policy) -> Simulator. 감싼 정책으로 시뮬레이터를 만들고 돌린 뒤 테이블을 뽑는다."""
    out = Path(out_dir)
    policy = CandidateLogPolicy(inner_policy, out / "candidates.csv.gz" if log_candidates else None)
    sim = sim_builder(policy)
    task_end_log = attach_task_end_log(sim)
    dock_wait_log = attach_dock_wait_log(sim)
    metrics = sim.run()
    return export_tables(sim, metrics, out, label, task_end_log, policy, extra_meta, dock_wait_log)


def _make_policy(name: str) -> BasePolicy:
    from simulation_engine.load_validation import make_policy

    if name in ("greedy", "cpr"):
        return make_policy(name)
    if name == "new_cpr":
        from policy.cpr.new_cpr_policy import NewCPRPolicy
        return NewCPRPolicy()
    if name == "atc_cpr":
        from policy.cpr.atc_cpr_policy import ATCCPRPolicy
        return ATCCPRPolicy()
    raise ValueError(f"알 수 없는 정책: {name}")


def main() -> None:
    import argparse
    import contextlib
    import io
    from dataclasses import replace

    import dataset_generator3 as gen3
    from simulation_engine.disturbance import Disturbance, DisturbanceConfig
    from simulation_engine.load_validation import build_simulator

    ap = argparse.ArgumentParser(description="정보시각화용 시뮬레이션 테이블 추출")
    ap.add_argument("--size", default="medium")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--load", type=float, default=0.8)
    ap.add_argument("--policies", nargs="+", default=["greedy", "cpr", "new_cpr"])
    ap.add_argument("--out", default="vis_data")
    ap.add_argument("--no-candidates", action="store_true", help="후보 로그를 남기지 않는다")
    ap.add_argument("--dist-cv", type=float, default=0.0, help="0이면 결정적 실행")
    ap.add_argument("--dist-seed", type=int, default=0)
    args = ap.parse_args()

    data = gen3.generate(replace(gen3.PRESETS[args.size], target_load=args.load), args.seed)
    for name in args.policies:
        def builder(policy):
            dist = None
            if args.dist_cv > 0:
                dist = Disturbance(DisturbanceConfig(travel_cv=args.dist_cv, picking_cv=args.dist_cv,
                                                     seed=args.dist_seed))
            return build_simulator(data, policy, dist)

        out = Path(args.out) / f"{args.size}_s{args.seed}_L{args.load:g}" / name
        with contextlib.redirect_stdout(io.StringIO()):
            meta = run_and_export(builder, _make_policy(name), out, name, not args.no_candidates,
                                  {"size": args.size, "seed": args.seed, "target_load": args.load,
                                   "dist_cv": args.dist_cv, "dist_seed": args.dist_seed})
        print(f"[{name}] -> {out}  dispatch={meta['n_dispatch']}  candidates={meta['n_candidate_rows']}  "
              f"frag {meta['frag_index_init']:.4f}->{meta['frag_index_final']:.4f} "
              f"(metrics {meta['check_metrics_frag_init']:.4f}->{meta['check_metrics_frag_final']:.4f})")
        failed = [k for k, v in meta["checks"].items() if v.get("ok") is False]
        print(f"    checks: {'FAILED ' + ', '.join(failed) if failed else 'all ok'}")


if __name__ == "__main__":
    main()
