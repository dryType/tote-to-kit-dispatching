import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

FILE = Path(__file__).resolve()
ROOT = FILE.parent.parent
SRC_DIR = ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from simulation_engine.dataset_loader import load_entities_from_scenario


def main():

    part_to_totes: dict[str, dict[str, int]] = defaultdict(dict)
    part_to_kits: dict[str, dict[str, int]] = defaultdict(dict)

    totes, kits, stations, agvs = load_entities_from_scenario("custom")

    for tote in totes:
        for component in tote.contents:
            part_id = component.part_id
            quantity = component.quantity

            if quantity > 0:
                part_to_totes[part_id][tote.tote_id] = quantity

    for kit in kits:
        for part_id, quantity in kit.required_parts.items():
            if quantity > 0:
                part_to_kits[part_id][kit.kit_id] = quantity

    # 1. part_to_totes 롱 포맷 변환 및 CSV 저장
    tote_rows = [
        {"part_id": part_id, "tote_id": tote_id, "quantity": qty}
        for part_id, tote_dict in part_to_totes.items()
        for tote_id, qty in tote_dict.items()
    ]
    df_totes = pd.DataFrame(tote_rows)
    df_totes.to_csv("part_to_totes.csv", index=False, encoding="utf-8-sig")

    # 2. part_to_kits 롱 포맷 변환 및 CSV 저장
    kit_rows = [
        {"part_id": part_id, "kit_id": kit_id, "required_quantity": qty}
        for part_id, kit_dict in part_to_kits.items()
        for kit_id, qty in kit_dict.items()
    ]
    df_kits = pd.DataFrame(kit_rows)
    df_kits.to_csv("part_to_kits.csv", index=False, encoding="utf-8-sig")

    print("CSV 파일 추출 완료! (part_to_totes.csv, part_to_kits.csv)")


if __name__ == "__main__":
    main()
