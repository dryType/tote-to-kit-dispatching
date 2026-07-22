"""
Lightweight dataset visualizer for generated kits/totes.
Saves summary CSVs and a PNG with three charts:
 - Kit utilization histogram
 - Tote used-volume histogram
 - Tote-type pie chart

Run: python data/dataset_visualize_v2.py
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict

import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "generated_datasets" / "scenario_custom"
KITS_JSON = OUT_DIR / "kits.json"
TOTES_JSON = OUT_DIR / "totes.json"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PNG_OUT = OUT_DIR / "visualization_v2.png"
KITS_CSV = OUT_DIR / "kits_summary.csv"
TOTES_CSV = OUT_DIR / "totes_summary.csv"


def load_data() -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    if not KITS_JSON.exists() or not TOTES_JSON.exists():
        print(f"Error: expected files not found in {OUT_DIR}")
        sys.exit(1)

    with KITS_JSON.open("r", encoding="utf-8") as f:
        kits = json.load(f).get("kits", [])
    with TOTES_JSON.open("r", encoding="utf-8") as f:
        totes = json.load(f).get("totes", [])
    return kits, totes


def summarize_and_save(kits: list[Dict[str, Any]], totes: list[Dict[str, Any]]):
    df_k = pd.DataFrame(kits)
    df_t = pd.DataFrame(totes)

    # Kits: compute utilization
    if not df_k.empty:
        df_k["util_pct"] = (
            df_k["required_volume_cm3"] / df_k["kit_total_capacity_cm3"] * 100
        )
    else:
        df_k["util_pct"] = pd.Series(dtype=float)

    # Totes: ensure numeric
    if not df_t.empty:
        df_t["used_volume_cm3"] = pd.to_numeric(
            df_t["used_volume_cm3"], errors="coerce"
        ).fillna(0)
    else:
        df_t["used_volume_cm3"] = pd.Series(dtype=float)

    # Save summaries
    df_k.to_csv(KITS_CSV, index=False)
    df_t.to_csv(TOTES_CSV, index=False)

    # Print a compact report
    print("--- Dataset Summary ---")
    print(f"kits: {len(df_k)}  |  totes: {len(df_t)}")
    if not df_k.empty:
        print(
            f"kit util mean: {df_k['util_pct'].mean():.2f}%  median: {df_k['util_pct'].median():.2f}%"
        )
    if not df_t.empty:
        print(f"tote used vol mean: {df_t['used_volume_cm3'].mean():.0f} cm3")

    return df_k, df_t


def plot_and_save(df_k: pd.DataFrame, df_t: pd.DataFrame):
    plt.style.use("seaborn-v0_8")
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))

    # Kit utilization histogram
    ax1 = axes[0, 0]
    if not df_k.empty:
        ax1.hist(df_k["util_pct"], bins=12, color="#4C9F70", edgecolor="#2E2E2E")
        ax1.axvline(100, color="r", linestyle="--", label="Capacity 100%")
        ax1.set_xlabel("Kit utilization (%)")
        ax1.set_ylabel("Count")
        ax1.set_title("Kit Utilization")
        ax1.legend()
    else:
        ax1.text(0.5, 0.5, "No kits", ha="center")

    # Tote used volume histogram
    ax2 = axes[0, 1]
    if not df_t.empty:
        ax2.hist(df_t["used_volume_cm3"], bins=20, color="#7FB3D5", edgecolor="#2E2E2E")
        ax2.set_xlabel("Tote used volume (cm3)")
        ax2.set_ylabel("Count")
        ax2.set_title("Tote used volume distribution")
    else:
        ax2.text(0.5, 0.5, "No totes", ha="center")

    # Tote type pie
    ax3 = axes[1, 0]
    if not df_t.empty and "tote_type" in df_t.columns:
        counts = df_t["tote_type"].value_counts()
        ax3.pie(counts, labels=counts.index, autopct="%1.1f%%")
        ax3.set_title("Tote type distribution")
    else:
        ax3.text(0.5, 0.5, "No tote types", ha="center")

    # Top 6 largest totes table
    ax4 = axes[1, 1]
    if not df_t.empty:
        top = df_t.sort_values(by="used_volume_cm3", ascending=False).head(6)
        # display table-like text
        ax4.axis("off")
        table_data = top[["tote_id", "tote_type", "used_volume_cm3"]].to_string(
            index=False
        )
        ax4.text(
            0, 1, "Top 6 largest totes:\n" + table_data, va="top", family="monospace"
        )
    else:
        ax4.text(0.5, 0.5, "No totes", ha="center")
        ax4.axis("off")

    plt.tight_layout()
    plt.savefig(PNG_OUT, dpi=150)
    print(f"Saved figure: {PNG_OUT}")


if __name__ == "__main__":
    kits, totes = load_data()
    df_k, df_t = summarize_and_save(kits, totes)
    plot_and_save(df_k, df_t)
    print(f"Summary CSVs: {KITS_CSV}, {TOTES_CSV}")
