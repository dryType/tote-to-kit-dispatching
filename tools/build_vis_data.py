"""vis_export.py 출력(CSV) -> 웹 인터페이스용 JSON.

입력  vis_data/<scenario>/<policy>/   (vis_export.py 출력 폴더)
출력  web/public/data/<name>/         trips.json, kits.json, kit_sku.json, busy_bins.json, skus.json, meta.json
      web/public/data/index.json      데이터셋 목록 (웹 상단 드롭다운)

사용 예 (레포 루트에서):
    python tools/build_vis_data.py                          # vis_data 아래 실행을 모두 변환
    python tools/build_vis_data.py vis_data/medium_s42_L0.8/new_cpr:new_cpr_L0.8 --default new_cpr_L0.8

이름을 주지 않으면 <policy>_L<load> (예: new_cpr_L1.0) 로 붙인다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
BIN_SEC = 300  # busy_bins 구간 길이 (5분)
FLEET_ID = "AMR fleet"
EPS = 1e-6  # 지연 판정 (vis_export meta 의 tardy_kits 와 같은 기준)


# ----------------------------------------------------------------------
# 읽기
# ----------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(v: str | None) -> float | None:
    return None if v is None or v == "" else float(v)


def _i(v: str | None) -> int | None:
    return None if v is None or v == "" else int(float(v))


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(x, nd)


# ----------------------------------------------------------------------
# 계산
# ----------------------------------------------------------------------

def slip_start(start: float, deadline: float, steps: list[list[float]]) -> float:
    """선형 목표 진행선 (t - start) / (deadline - start) 아래로 내려간 뒤 다시 회복하지 못한 첫 시각.

    steps: [t, 진행률] 계단 (시간순, 첫 점은 [start, 0]). 진행률 p 인 계단은 c = start + p·(deadline − start)
    까지 목표선 위(같음 포함)에 있다. c 가 그 계단 시작 이후인 마지막 계단의 c 가 답이다.
    그 뒤 계단들은 시작하자마자 이미 목표선 아래이므로 회복하지 못한다.
    """
    if deadline <= start:  # 투입 시점에 이미 납기가 지났다
        return start
    span = deadline - start
    last = start
    for t, p in steps:
        c = start + p * span
        if c >= t:
            last = c
    return last


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _max_concurrent(intervals: list[tuple[float, float]], s: float, e: float) -> int:
    """[s, e) 안에서 동시에 열려 있는 구간 수의 최댓값. 한 구간이 끝나는 시각에 다른 구간이 시작하면 겹치지 않은 것으로 본다."""
    ev = []
    for a, b in intervals:
        a0, b0 = max(a, s), min(b, e)
        if b0 > a0:
            ev += [(a0, 1), (b0, -1)]
    ev.sort()  # 같은 시각이면 -1 이 먼저
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def busy_matrix(trips: list[dict], station_ids: list[str], n_agvs: int, t_end: float) -> dict:
    """5분 구간별 가동 비율. 스테이션: 도킹 점유(t_dock~t_kit_end), AMR fleet: 트립 중(t_dispatch~t_return).

    스테이션 행에는 대기도 붙인다.
      queue      평균 대기 AMR 수 = 구간과 겹치는 [t_wait, t_dock] 시간 합 / 구간 길이
      max_queue  구간 안에서 동시에 [t_wait, t_dock] 에 있던 AMR 수의 최댓값
    t_dock 은 kitting_start 라서 [t_wait, t_dock] 에는 도크 허락 뒤 대기 위치 -> 도킹 위치 이동(1.33 s)도 들어간다.
    t_wait 가 없는 트립이 하나라도 있으면 대기는 넣지 않는다 (queue_available = False).

    마지막 구간은 t_end 에서 끊기므로 그 구간 길이(300 s 미만)로 나눈다.
    AGV 고장(DOWN)은 finish_task 뒤에 오므로 트립 구간에 들어가지 않는다.
    """
    n_bins = max(1, math.ceil(t_end / BIN_SEC))
    starts = [k * BIN_SEC for k in range(n_bins)]
    lens = [min(BIN_SEC, t_end - s) for s in starts]

    def fill(intervals: list[tuple[float, float]], denom_scale: float) -> list[float]:
        acc = [0.0] * n_bins
        for a, b in intervals:
            k0, k1 = min(n_bins - 1, int(a // BIN_SEC)), min(n_bins - 1, int(b // BIN_SEC))
            for k in range(k0, k1 + 1):
                acc[k] += _overlap(a, b, starts[k], starts[k] + lens[k])
        return [acc[k] / (denom_scale * lens[k]) if lens[k] > 0 else 0.0 for k in range(n_bins)]

    docked = [t for t in trips if t["t_dock"] is not None]
    queue_available = bool(docked) and all(t["t_wait"] is not None for t in docked)

    rows = []
    for sid in station_ids:
        st_trips = [t for t in docked if t["station_id"] == sid]
        iv = [(t["t_dock"], t["t_kit_end"]) for t in st_trips if t["t_kit_end"] is not None]
        row = {"id": sid, "kind": "station", "values": fill(iv, 1.0)}
        if queue_available:
            wait_iv = [(t["t_wait"], t["t_dock"]) for t in st_trips]
            row["queue"] = [round(q, 5) for q in fill(wait_iv, 1.0)]
            row["max_queue"] = [_max_concurrent(wait_iv, starts[k], starts[k] + lens[k]) for k in range(n_bins)]
        rows.append(row)
    iv = [(t["t_dispatch"], t["t_return"]) for t in trips if t["t_return"] is not None]
    rows.append({"id": FLEET_ID, "kind": "fleet", "n_agvs": n_agvs, "values": fill(iv, float(n_agvs))})

    vmax = max(v for r in rows for v in r["values"])
    vmin = min(v for r in rows for v in r["values"])
    for r in rows:
        r["values"] = [round(v, 4) for v in r["values"]]
    out = {
        "bin_sec": BIN_SEC, "t_end": _r(t_end), "n_bins": n_bins,
        "bin_starts": starts, "bin_lengths": [_r(x) for x in lens],
        "queue_available": queue_available, "rows": rows,
        "_range": (vmin, vmax),
    }
    if queue_available:
        st_rows = [r for r in rows if r["kind"] == "station"]
        out["queue_max"] = max(q for r in st_rows for q in r["queue"])
        out["max_queue_overall"] = max(m for r in st_rows for m in r["max_queue"])
    return out


def build(src: Path, dst: Path, name: str) -> dict:
    meta_src = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    disp = _read_csv(src / "dispatches.csv")
    kits_csv = _read_csv(src / "kits.csv")
    kit_sku_csv = _read_csv(src / "kit_sku.csv")
    tote_sku = _read_csv(src / "tote_sku.csv")
    stations_csv = _read_csv(src / "stations.csv")

    lot_by_ts = {(r["tote_id"], r["part_id"]): max(1, _i(r["lot_size"]) or 1) for r in tote_sku}

    # --- trips ------------------------------------------------------------------------
    trips = []
    for r in disp:
        parts = json.loads(r["matched_parts"])
        partial_skus = [p for p, q in parts.items() if q % lot_by_ts[(r["tote_id"], p)] != 0]
        trips.append({
            "trip_id": int(r["dispatch_seq"]),
            "agv_id": r["agv_id"], "tote_id": r["tote_id"], "kit_id": r["kit_id"], "station_id": r["station_id"],
            "t_dispatch": _f(r["time"]), "t_wait": _f(r["wait_start"]), "t_dock": _f(r["kitting_start"]),
            "t_kit_end": _f(r["kitting_end"]), "t_return": _f(r["task_end"]),
            "dock_wait": _f(r["dock_wait"]), "distance_m": _f(r["distance_m"]),
            "matched_qty": int(r["matched_qty"]), "matched_parts": parts,
            "partial_picks": int(r["partial_picks"]), "partial_skus": partial_skus,
        })
    trips.sort(key=lambda t: t["trip_id"])

    # --- kits -------------------------------------------------------------------------
    trips_by_kit: dict[str, list[dict]] = {}
    for t in trips:
        trips_by_kit.setdefault(t["kit_id"], []).append(t)

    kits = []
    for r in kits_csv:
        kid = r["kit_id"]
        start, end, deadline = _f(r["start"]), _f(r["completion"]), _f(r["deadline"])
        qty_req = int(r["qty_required"])
        tardiness = _f(r["tardiness"])
        late = None if tardiness is None else tardiness > EPS

        # 트립의 kitting_end 마다 누적 matched_qty / qty_required. 같은 시각은 하나로 합친다.
        progress: list[list[float]] = [[start, 0.0]] if start is not None else []
        cum = 0
        for t in sorted((t for t in trips_by_kit.get(kid, []) if t["t_kit_end"] is not None),
                        key=lambda t: t["t_kit_end"]):
            cum += t["matched_qty"]
            p = cum / qty_req if qty_req else 0.0
            if progress and progress[-1][0] == t["t_kit_end"]:
                progress[-1][1] = p
            else:
                progress.append([t["t_kit_end"], p])

        slip = slip_start(start, deadline, progress) if late and start is not None else None
        kits.append({
            "kit_id": kid, "station_id": r["station_id"] or None,
            "product": r["product"], "line": r["line"], "release_order": _i(r["release_order"]),
            "start": start, "end": end, "deadline": deadline, "tardiness": tardiness,
            "lateness": _f(r["lateness"]),
            "qty_required": qty_req, "n_sku_required": int(r["n_sku_required"]),
            "n_trips": len(trips_by_kit.get(kid, [])), "late": late,
            "released_late": None if start is None or deadline is None else start >= deadline,
            "slip_start": _r(slip),
            "progress": [[_r(t), round(p, 5)] for t, p in progress],
        })
    kits.sort(key=lambda k: (k["station_id"] or "", k["start"] if k["start"] is not None else math.inf))

    # --- kit_sku ----------------------------------------------------------------------
    kit_sku = [{
        "kit_id": r["kit_id"], "sku": r["sku"], "qty_required": int(r["qty_required"]),
        "lot_size": _i(r["lot_size"]), "cartons_needed": _f(r["cartons_needed"]),
    } for r in kit_sku_csv]

    # --- skus -------------------------------------------------------------------------
    sku_ids = sorted({r["part_id"] for r in tote_sku} | {r["sku"] for r in kit_sku})
    n_totes_init = {s: 0 for s in sku_ids}
    lot_by_sku: dict[str, int] = {}
    for r in tote_sku:
        lot_by_sku.setdefault(r["part_id"], _i(r["lot_size"]))
        if (_i(r["qty_init"]) or 0) > 0:
            n_totes_init[r["part_id"]] += 1
    cartons = {s: 0.0 for s in sku_ids}
    demand = {s: 0 for s in sku_ids}
    for r in kit_sku:
        cartons[r["sku"]] += r["cartons_needed"] or 0.0
        demand[r["sku"]] += r["qty_required"]
    n_trips = {s: 0 for s in sku_ids}
    n_partial = {s: 0 for s in sku_ids}
    for t in trips:
        for p in t["matched_parts"]:
            n_trips[p] += 1
        for p in t["partial_skus"]:
            n_partial[p] += 1
    skus = [{
        "sku": s, "lot_size": lot_by_sku.get(s),
        "n_totes_init": n_totes_init[s], "n_trips": n_trips[s],
        "cartons_needed": round(cartons[s], 4),
        "trips_per_carton": round(n_trips[s] / cartons[s], 4) if cartons[s] > 0 else None,
        "demand_qty": demand[s],
        # 트립 1건에서 한 SKU 를 꺼낸 것을 피킹 1회로 센다
        "partial_share": round(n_partial[s] / n_trips[s], 4) if n_trips[s] else None,
    } for s in sku_ids]

    # --- busy bins --------------------------------------------------------------------
    station_ids = sorted(r["station_id"] for r in stations_csv)
    makespan = meta_src.get("makespan")
    t_end = max([makespan or 0.0] + [t["t_return"] for t in trips if t["t_return"] is not None])
    busy = busy_matrix(trips, station_ids, int(meta_src["n_agvs"]), t_end)
    vmin, vmax = busy.pop("_range")

    # --- 검증 -------------------------------------------------------------------------
    dist_sum = sum(t["distance_m"] or 0.0 for t in trips)
    checks = {
        "busy_values_in_0_1": {"ok": vmin >= -1e-9 and vmax <= 1 + 1e-9, "min": round(vmin, 6), "max": round(vmax, 6)},
        "completed_kits_progress_ends_at_1": {
            "ok": all(abs(k["progress"][-1][1] - 1.0) < 1e-9 for k in kits if k["end"] is not None and k["progress"]),
        },
        "progress_last_time_equals_kit_end": {
            "ok": all(abs(k["progress"][-1][0] - k["end"]) < 1e-3 for k in kits if k["end"] is not None and k["progress"]),
        },
        "slip_start_only_for_late_kits": {
            "ok": all((k["slip_start"] is not None) == bool(k["late"]) for k in kits),
        },
        # 납기가 지난 뒤 투입된 키트는 slip_start = start (> deadline)
        "slip_start_within_start_and_max_start_deadline": {
            "ok": all(k["start"] - 1e-6 <= k["slip_start"] <= max(k["start"], k["deadline"]) + 1e-6
                      for k in kits if k["slip_start"] is not None),
        },
        "trip_distance_sum_equals_metrics": {
            "ok": meta_src.get("total_agv_move_distance") is None
            or abs(dist_sum - meta_src["total_agv_move_distance"]) < 0.01 * len(trips),
            "trips_sum": round(dist_sum, 2), "metrics": meta_src.get("total_agv_move_distance"),
        },
        "station_dock_time_equals_stations_csv": {
            "ok": all(abs(sum(t["t_kit_end"] - t["t_dock"] for t in trips if t["station_id"] == s["station_id"])
                          - float(s["dock_time"])) < 1.0 for s in stations_csv),
        },
        "sku_n_trips_le_total_trips": {"ok": all(s["n_trips"] <= len(trips) for s in skus)},
    }
    if busy["queue_available"]:
        st_rows = [r for r in busy["rows"] if r["kind"] == "station"]
        # 저장된(반올림한) 값으로 다시 더해서 파일 자체를 검증한다
        diffs = {
            r["id"]: sum(q * L for q, L in zip(r["queue"], busy["bin_lengths"]))
            - sum(t["t_dock"] - t["t_wait"] for t in trips if t["station_id"] == r["id"] and t["t_dock"] is not None)
            for r in st_rows
        }
        checks["queue_nonnegative"] = {
            "ok": all(q >= 0 for r in st_rows for q in r["queue"]) and all(m >= 0 for r in st_rows for m in r["max_queue"]),
            "min": min(q for r in st_rows for q in r["queue"]),
        }
        checks["queue_time_equals_sum_t_dock_minus_t_wait"] = {
            "ok": all(abs(d) < 1.0 for d in diffs.values()),
            "max_abs_diff_sec": round(max(abs(d) for d in diffs.values()), 4),
        }
        checks["max_queue_ge_ceil_mean_queue"] = {  # 평균이 0보다 크면 그 구간에 최소 한 대는 있었다
            "ok": all(m >= (1 if q > 0 else 0) for r in st_rows for q, m in zip(r["queue"], r["max_queue"])),
        }

    n_late = sum(1 for k in kits if k["late"])
    meta = {
        **{k: v for k, v in meta_src.items() if k not in ("definitions", "checks")},
        "dataset": name,
        "policy_key": src.name,
        "policy_name": meta_src.get("policy"),
        "source_dir": src.relative_to(REPO_DIR).as_posix() if src.is_relative_to(REPO_DIR) else str(src),
        "bin_sec": BIN_SEC,
        "t_end": _r(t_end),
        "stations": station_ids,
        "n_trips": len(trips),
        "n_late_kits": n_late,
        "n_skus_plotted": sum(1 for s in skus if s["trips_per_carton"] is not None),
        "definitions": {
            **meta_src.get("definitions", {}),
            "t_dock": "kitting_start (도킹 위치 도착, 스테이션 도크 점유 시작), s",
            "t_end": "마지막 AGV 반납 시각 = max(makespan, t_return). makespan 은 마지막 키트 완료 시각",
            "late": f"tardiness > {EPS}",
            "progress": "[t, 누적 matched_qty / qty_required], 트립의 kitting_end 마다. 첫 점은 [start, 0]",
            "slip_start": "늦은 키트만: 선형 목표 진행선 (t-start)/(deadline-start) 아래로 내려간 뒤 회복하지 못한 첫 시각. 납기 뒤에 투입된 키트(released_late)는 start",
            "released_late": "start >= deadline (스테이션에 걸릴 때 이미 납기가 지났다)",
            "busy_bins": "스테이션: 구간 안 도킹 점유 시간 / 구간 길이. AMR fleet: 구간 안 트립 중 AGV 시간 합 / (AGV 수 x 구간 길이). 마지막 구간은 t_end 에서 끊긴 길이로 나눈다",
            "queue": "스테이션 행만: 평균 대기 AMR 수 = 구간과 겹치는 [t_wait, t_dock] 시간 합 / 구간 길이. 도크 허락 뒤 도킹 위치까지 이동(1.33 s)이 포함된다",
            "max_queue": "스테이션 행만: 구간 안에서 동시에 [t_wait, t_dock] 에 있던 AMR 수의 최댓값",
            "partial_share": "그 SKU 를 꺼낸 (트립, SKU) 중 qty % lot_size != 0 인 비율",
            "trips_per_carton": "n_trips / cartons_needed. cartons_needed 가 0 이면 null",
        },
        "source_checks": meta_src.get("checks"),
        "build_checks": checks,
    }

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    def dump(fname: str, obj) -> None:
        (dst / fname).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    dump("trips.json", trips)
    dump("kits.json", kits)
    dump("kit_sku.json", kit_sku)
    dump("busy_bins.json", busy)
    dump("skus.json", skus)
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


# ----------------------------------------------------------------------
# 실행
# ----------------------------------------------------------------------

def _discover(root: Path) -> list[tuple[Path, str]]:
    runs = []
    for meta_path in sorted(root.glob("*/*/meta.json")):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        load = m.get("target_load")
        name = f"{meta_path.parent.name}_L{load:.1f}" if load is not None else meta_path.parent.name
        runs.append((meta_path.parent, name))
    names = [n for _, n in runs]
    if len(set(names)) < len(names):  # 크기/seed 가 다른 실행이 섞이면 시나리오 이름까지 붙인다
        runs = [(p, f"{p.parent.name}_{p.name}") for p, _ in runs]
    return runs


def main() -> None:
    ap = argparse.ArgumentParser(description="vis_export CSV -> 웹용 JSON")
    ap.add_argument("runs", nargs="*", help="SRC[:NAME]. 비우면 --src-root 아래를 모두 변환")
    ap.add_argument("--src-root", default="vis_data")
    ap.add_argument("--out", default="web/public/data")
    ap.add_argument("--default", help="웹에서 처음 열 데이터셋 이름")
    args = ap.parse_args()

    if args.runs:
        runs = []
        for spec in args.runs:
            src, _, name = spec.partition(":")
            runs.append((Path(src).resolve(), name or Path(src).name))
    else:
        runs = [(p.resolve(), n) for p, n in _discover(Path(args.src_root))]
    if not runs:
        sys.exit(f"변환할 실행이 없다: {args.src_root}")

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    index_path = out_root / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"datasets": []}
    entries = {d["id"]: d for d in index.get("datasets", [])}

    failed = False
    for src, name in runs:
        meta = build(src, out_root / name, name)
        bad = [k for k, v in meta["build_checks"].items() if not v["ok"]]
        failed |= bool(bad)
        entries[name] = {
            "id": name, "policy": meta["policy_key"], "policy_name": meta["policy_name"],
            "size": meta.get("size"), "seed": meta.get("seed"), "target_load": meta.get("target_load"),
            "n_trips": meta["n_trips"], "n_kits": meta["n_kits"], "n_late_kits": meta["n_late_kits"],
        }
        print(f"[{name}] <- {meta['source_dir']}  trips={meta['n_trips']} kits={meta['n_kits']} "
              f"late={meta['n_late_kits']} bins={math.ceil(meta['t_end'] / BIN_SEC)}  "
              f"checks: {'FAILED ' + ', '.join(bad) if bad else 'all ok'}")

    # 지워진 폴더는 목록에서 뺀다
    datasets = [e for e in entries.values() if (out_root / e["id"] / "meta.json").exists()]
    datasets.sort(key=lambda e: (-(e["target_load"] or 0), e["policy"], e["id"]))
    default = args.default or index.get("default")
    if default not in {e["id"] for e in datasets}:
        default = datasets[0]["id"]
    index_path.write_text(json.dumps({"default": default, "datasets": datasets}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"index: {len(datasets)} datasets, default={default}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
