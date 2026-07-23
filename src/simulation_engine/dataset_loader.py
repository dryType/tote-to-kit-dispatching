from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from simulation_engine import entities
except ModuleNotFoundError:
    # allow running this file directly from project root by adding `src` to sys.path
    current = Path(__file__).resolve()
    src_dir = current.parent.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from simulation_engine import entities


def _load_json(path: Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    return _repo_root() / "data"


def _scenario_dataset_dir(scenario_name: str) -> Path:
    return _data_root() / "generated_datasets" / f"scenario_{scenario_name}"


def _scenario_agv_config_path(scenario_name: str) -> Path:
    return _data_root() / "master_data" / "agv_configs" / f"agv_{scenario_name}.json"


def _layout_path() -> Path:
    return _data_root() / "master_data" / "layout.json"


def load_totes(totes_path: Path) -> List[entities.Tote]:
    data = _load_json(Path(totes_path))
    totes_list = data.get("totes") if isinstance(data, dict) else data
    return [entities.Tote.from_dict(t) for t in totes_list]


def load_kits(kits_path: Path) -> List[entities.Kit]:
    data = _load_json(Path(kits_path))
    kits_list = data.get("kits") if isinstance(data, dict) else data
    return [entities.Kit.from_dict(k) for k in kits_list]


def load_agvs(agv_config_path: Path) -> List[entities.AGV]:
    data = _load_json(Path(agv_config_path))
    agv_list = data.get("agvs") if isinstance(data, dict) else data
    return [entities.AGV.from_dict(agv) for agv in agv_list]


def load_stations_from_layout(layout_path: Path) -> List[entities.KittingStation]:
    layout = _load_json(Path(layout_path))
    stations = layout.get("kitting_stations", [])
    return [entities.KittingStation.from_dict(s) for s in stations]


def create_agvs(count: int, start_index: int = 1) -> List[entities.AGV]:
    agvs: List[entities.AGV] = []
    for i in range(start_index, start_index + max(0, int(count))):
        agv_id = f"AGV_{i:03d}"
        agvs.append(entities.AGV(agv_id=agv_id))
    return agvs


def load_entities_from_dataset(
    totes_path: Path,
    kits_path: Path,
    layout_path: Optional[Path] = None,
    agv_count: int = 0,
) -> Dict[str, Any]:
    """Return a dict of instantiated entities from dataset files.

    Returns a dictionary with keys: `totes`, `kits`, `stations`, `agvs`.
    """
    totes = load_totes(Path(totes_path))
    kits = load_kits(Path(kits_path))

    stations: List[entities.KittingStation] = []
    if layout_path is not None and Path(layout_path).exists():
        stations = load_stations_from_layout(Path(layout_path))

    agvs = create_agvs(int(agv_count) if agv_count else 0)

    return {
        "totes": totes,
        "kits": kits,
        "stations": stations,
        "agvs": agvs,
    }


def load_entities_from_scenario(scenario_name: str) -> Dict[str, Any]:
    dataset_dir = _scenario_dataset_dir(scenario_name)
    totes_path = dataset_dir / "totes.json"
    kits_path = dataset_dir / "kits.json"
    agv_config_path = _scenario_agv_config_path(scenario_name)
    layout_path = _layout_path()

    if not totes_path.exists():
        raise FileNotFoundError(f"Tote file not found: {totes_path}")
    if not kits_path.exists():
        raise FileNotFoundError(f"Kit file not found: {kits_path}")
    if not agv_config_path.exists():
        raise FileNotFoundError(f"AGV config file not found: {agv_config_path}")
    if not layout_path.exists():
        raise FileNotFoundError(f"Layout file not found: {layout_path}")

    return {
        "totes": load_totes(totes_path),
        "kits": load_kits(kits_path),
        "stations": load_stations_from_layout(layout_path),
        "agvs": load_agvs(agv_config_path),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Load a scenario dataset into entity objects"
    )
    parser.add_argument("scenario", help="scenario name without the scenario_ prefix")
    args = parser.parse_args()

    entities_map = load_entities_from_scenario(args.scenario)

    print(
        f"Loaded {len(entities_map['totes'])} totes, {len(entities_map['kits'])} kits"
    )
    print(
        f"Loaded {len(entities_map['stations'])} stations, {len(entities_map['agvs'])} agvs"
    )
