import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "master_data")

ACTIVE_LAYOUT_FILE = "layout.json"
ACTIVE_AGV_CONFIG_FILE = "agv_custom.json"
ACTIVE_BOM_FILE = "bom_custom.json"
ACTIVE_PROD_PLAN = "prod_plan_custom.json"

LAYOUT_PATH = os.path.join(DATA_DIR, ACTIVE_LAYOUT_FILE)
AGV_CONFIG_PATH = os.path.join(DATA_DIR, "agv_configs", ACTIVE_AGV_CONFIG_FILE)
BOM_PATH = os.path.join(DATA_DIR, "boms", ACTIVE_BOM_FILE)
PROD_PLAN_PATH = os.path.join(DATA_DIR, "prod_plans", ACTIVE_PROD_PLAN)

PART_MARGIN = 0.05
TOTE_SINGLE_PART_RATIO = 0.6
TOTE_MIXED_PART_RATIO = 0.35
TOTE_RESIDUAL_RATIO = 0.05

if TOTE_SINGLE_PART_RATIO + TOTE_MIXED_PART_RATIO + TOTE_RESIDUAL_RATIO != 1.0:
    raise ValueError(
        "The sum of TOTE_SINGLE_PART_RATIO, TOTE_MIXED_PART_RATIO, and TOTE_RESIDUAL_RATIO must equal 1.0."
    )

if not os.path.exists(LAYOUT_PATH):
    raise FileNotFoundError(f"Layout file not found: {LAYOUT_PATH}")
if not os.path.exists(AGV_CONFIG_PATH):
    raise FileNotFoundError(f"AGV config file not found: {AGV_CONFIG_PATH}")
if not os.path.exists(BOM_PATH):
    raise FileNotFoundError(f"BOM file not found: {BOM_PATH}")
if not os.path.exists(PROD_PLAN_PATH):
    raise FileNotFoundError(f"Production plan file not found: {PROD_PLAN_PATH}")

print("All files loaded successfully.")
