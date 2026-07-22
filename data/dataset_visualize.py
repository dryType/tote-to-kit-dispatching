import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# 1. 현재 실행 중인 파일(dataset_visualize.py)의 절대 경로를 따서 기준점 잡기
# 이렇게 하면 BASE_DIR은 무조건 '.../data' 폴더가 됨
BASE_DIR = Path(__file__).resolve().parent

# 2. 기준점으로부터 하위 폴더 경로 조인 (슬래시 기호로 깔끔하게 엮임)
KITS_JSON_PATH = BASE_DIR / "generated_datasets" / "scenario_custom" / "kits.json"
TOTES_JSON_PATH = BASE_DIR / "generated_datasets" / "scenario_custom" / "totes.json"

# 3. 절대 경로로 파일 오픈
with open(KITS_JSON_PATH, "r", encoding="utf-8") as f:
    kit_data = json.load(f)["kits"]

with open(TOTES_JSON_PATH, "r", encoding="utf-8") as f:
    tote_data = json.load(f)["totes"]
# 데이터프레임 변환
df_kits = pd.DataFrame(kit_data)
df_totes = pd.DataFrame(tote_data)

print("=" * 60)
print("📊 [REPORT] KIT & TOTE DATASET INTEGRITY CHECK")
print("=" * 60)

# ----------------─────────────────────────────────────────
# 검증 1: 총 자재 수급 밸런스 검사 (Supply vs Demand)
# ----------------─────────────────────────────────────────
# 키트 총 소요량 계산
demand_dict = {}
for kit in kit_data:
    for part, qty in kit["required_parts"].items():
        demand_dict[part] = demand_dict.get(part, 0) + qty

# 창고 총 재고량 계산
supply_dict = {}
for tote in tote_data:
    for content in tote["contents"]:
        p_id = content["part_id"]
        supply_dict[p_id] = supply_dict.get(p_id, 0) + content["quantity"]

# 밸런스 비교
df_balance = pd.DataFrame(
    [
        {
            "PART_ID": p,
            "Initial_Supply(창고)": supply_dict.get(p, 0),
            "Total_Demand(계획)": demand_dict.get(p, 0),
        }
        for p in sorted(list(set(demand_dict.keys()) | set(supply_dict.keys())))
    ]
)
df_balance["Shortage_Risk"] = (
    df_balance["Initial_Supply(창고)"] < df_balance["Total_Demand(계획)"]
)

print("\n1. 자재 수급 정합성 검사 (Supply vs Demand)")
print(df_balance.to_string(index=False))

if df_balance["Shortage_Risk"].any():
    print(
        "🚨 [WARNING] 창고 재고가 총 소요량보다 모자란 파트가 있음! 시뮬레이터 무한대기각임."
    )
else:
    print("✅ [OK] 모든 파트의 창고 초기 재고가 소요량 이상으로 널널함.")

# ----------------─────────────────────────────────────────
# 검증 2: 이동형 랙(Kit) 체적 가동률 및 분할 상태 검사
# ----------------─────────────────────────────────────────
df_kits["utilization_rate"] = (
    df_kits["required_volume_cm3"] / df_kits["kit_total_capacity_cm3"] * 100
)

print("\n2. 이동형 랙(Kit) 체적 분석")
print(f"- 총 생성된 키트(카트) 수: {len(df_kits)}대")
print(f"- 카트당 평균 자재 적재율: {df_kits['utilization_rate'].mean():.2f}%")
print(
    f"- 최고 적재율 카트: {df_kits['utilization_rate'].max():.2f}% ({df_kits.loc[df_kits['utilization_rate'].idxmax(), 'kit_id']})"
)

# 카트 용량 초과 뇌절 검사
overflow_kits = df_kits[df_kits["utilization_rate"] > 100]
if not overflow_kits.empty:
    print(
        f"🚨 [ERROR] 카트 용량(100%) 초과한 미친 키트 발견: {overflow_kits['kit_id'].tolist()}"
    )
else:
    print("✅ [OK] 모든 키트가 카트 최대 용량(1,512,000 cm³) 이내로 안전하게 분할됨.")

# ----------------─────────────────────────────────────────
# 검증 3: 창고 토트 과적 및 형태 분포 검사
# ----------------─────────────────────────────────────────
overflow_totes = df_totes[df_totes["used_volume_cm3"] > 57600]
print("\n3. 창고 토트 물리 제약 검사")
print(f"- 총 토트 개수: {len(df_totes)}개")
print(f"- 토트 종류 분포:\n{df_totes['tote_type'].value_counts().to_string()}")

if not overflow_totes.empty:
    print(
        f"🚨 [ERROR] 토트 한계 체적(57,600) 초과해서 물리 법칙 파괴한 토트 발견: {overflow_totes['tote_id'].tolist()}"
    )
else:
    print("✅ [OK] 모든 토트가 규격 체적 이내로 정상 패킹됨.")


# =========================================================
# 📈 시각화 차트 생성 (Matplotlib)
# =========================================================
plt.figure(figsize=(14, 10))
plt.rcParams["font.family"] = "Malgun Gothic"  # 윈도우 한글 깨짐 방지
plt.rcParams["axes.unicode_minus"] = False

# Chart 1: 파트별 수급 비교 (Bar Chart)
plt.subplot(2, 2, 1)
x_indices = range(len(df_balance))
plt.bar(
    [x - 0.2 for x in x_indices],
    df_balance["Initial_Supply(창고)"],
    width=0.4,
    label="창고 재고(Supply)",
    color="g",
)
plt.bar(
    [x + 0.2 for x in x_indices],
    df_balance["Total_Demand(계획)"],
    width=0.4,
    label="계획 소요(Demand)",
    color="r",
)
plt.xticks(x_indices, df_balance["PART_ID"], rotation=45)
plt.title("파트별 초기 재고 vs 총 소요량 비교")
plt.legend()
plt.grid(axis="y", linestyle="--", alpha=0.7)

# Chart 2: 키트 카트 체적 가동률 분포 (Histogram)
plt.subplot(2, 2, 2)
plt.hist(df_kits["utilization_rate"], bins=10, color="skyblue", edgecolor="black")
plt.axvline(100, color="r", linestyle="--", linewidth=2, label="카트 한계선 (100%)")
plt.title("이동형 랙(Kit) 체적 가동률(%) 분포")
plt.xlabel("적재율 (%)")
plt.ylabel("카트 대수")
plt.legend()
plt.grid(axis="y", linestyle="--", alpha=0.7)

# Chart 3: 창고 내부 토트 타입 비율 (Pie Chart)
plt.subplot(2, 2, 3)
tote_counts = df_totes["tote_type"].value_counts()
plt.pie(
    tote_counts,
    labels=tote_counts.index,
    autopct="%1.1f%%",
    colors=["gold", "coral"],
    startangle=90,
)
plt.title("창고 초기 토트 타입(Single vs Mixed) 비율")

plt.tight_layout()
plt.show()
