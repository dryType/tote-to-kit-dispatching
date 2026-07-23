from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_LAYOUT_PATH = BASE_DIR / "master_data" / "layout.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "layout_visualization.png"


def load_layout(layout_path: Path) -> Dict[str, Any]:
    if not layout_path.exists():
        raise FileNotFoundError(f"Layout file not found: {layout_path}")

    with layout_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _plot_points(
    ax: plt.Axes,
    items: Iterable[Dict[str, Any]],
    color: str,
    marker: str,
    label: str,
    text_offset: Tuple[float, float],
) -> None:
    items = list(items)
    if not items:
        return

    xs = [float(item.get("position_x", 0.0)) for item in items]
    ys = [float(item.get("position_y", 0.0)) for item in items]
    ax.scatter(xs, ys, s=90, c=color, marker=marker, label=label, edgecolors="black")

    for item in items:
        x = float(item.get("position_x", 0.0))
        y = float(item.get("position_y", 0.0))
        item_id = (
            item.get("location_id")
            or item.get("station_id")
            or item.get("depot_id")
            or ""
        )
        ax.text(x + text_offset[0], y + text_offset[1], item_id, fontsize=8)


def plot_layout(layout: Dict[str, Any], output_path: Path) -> None:
    storage_locations = layout.get("storage_locations", [])
    kitting_stations = layout.get("kitting_stations", [])
    agv_depots = layout.get("agv_depots", [])
    bounds = layout.get("map_bounds", {})

    min_x = float(bounds.get("min_x", 0.0))
    max_x = float(bounds.get("max_x", 0.0))
    min_y = float(bounds.get("min_y", 0.0))
    max_y = float(bounds.get("max_y", 0.0))

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 8))

    ax.add_patch(
        plt.Rectangle(
            (min_x, min_y),
            max_x - min_x,
            max_y - min_y,
            fill=False,
            linestyle="--",
            linewidth=2,
            edgecolor="#444444",
            label="Map bounds",
        )
    )

    _plot_points(
        ax,
        storage_locations,
        color="#4C78A8",
        marker="s",
        label="Storage locations",
        text_offset=(0.15, 0.15),
    )
    _plot_points(
        ax,
        kitting_stations,
        color="#F58518",
        marker="^",
        label="Kitting stations",
        text_offset=(0.15, -0.45),
    )
    _plot_points(
        ax,
        agv_depots,
        color="#54A24B",
        marker="o",
        label="AGV depots",
        text_offset=(0.15, 0.15),
    )

    ax.set_title("Warehouse Layout")
    ax.set_xlabel("X position")
    ax.set_ylabel("Y position")
    ax.set_xlim(min_x - 2, max_x + 2)
    ax.set_ylim(max_y + 2, min_y - 2)
    ax.set_aspect("equal", adjustable="box")
    ax.legend(loc="upper left")
    ax.grid(True, linestyle="--", alpha=0.4)

    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    print(f"Saved layout visualization: {output_path}")
    plt.show()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Visualize the warehouse layout")
    parser.add_argument(
        "--layout",
        type=Path,
        default=DEFAULT_LAYOUT_PATH,
        help="Path to layout.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to save the PNG visualization",
    )
    args = parser.parse_args()

    layout = load_layout(args.layout)
    plot_layout(layout, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
