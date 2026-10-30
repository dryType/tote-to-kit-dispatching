# Tote-Kit Dispatch Trace: 구현 지시서

이 레포는 내 학위논문 시뮬레이터(AMR 기반 고정형 키팅, 토트-키트 디스패칭)다. 이걸로 정보시각화 텀프로젝트(성균관대 조재민 교수) 인터페이스를 구현하려고 한다. 아래 순서대로 진행해라.

## 무인 실행 모드

나는 자리에 없고 질문에 답할 수 없다.

- 절대 멈춰서 기다리지 말고, 막히면 아래 "막혔을 때 규칙"대로 판단해서 계속 진행해라.
- 단계가 끝날 때마다, 그리고 네가 판단을 내릴 때마다 `STATUS.md`에 기록해라.
  - 형식: `[단계] 한 일 / 내린 판단과 이유 / 남은 일`
- 아침에 `STATUS.md`만 읽고 상황을 파악할 수 있어야 한다.

### 막혔을 때 규칙

1. **`vis_export.py`가 없거나, 시뮬레이터 실행이 실패하는 경우**
   - 원인을 `STATUS.md`에 남긴다.
   - 시뮬레이터와 정책 코드는 고치지 않는다.
   - 대신 `tools/make_synthetic.py`로 3단계 JSON과 **같은 스키마**의 합성 데이터를 만든다.
     - 규모: 토트 1,000개, 키트 30개, 스테이션 3개, AMR 10대, 트립 약 1,200개, SKU 약 200개
     - 늦은 키트와 혼잡 구간이 일부 있게 만든다.
   - 그 데이터로 4단계(웹)를 끝까지 진행한다.
   - 실제 데이터 연결은 남은 일로 적는다.
2. **실행 실패가 `vis_export.py` 안의 문제인 경우:** 그 파일은 고쳐도 된다.
3. **정의가 애매한 값:** 지시서의 정의를 따른다. 지시서에도 없으면 가장 단순한 정의를 쓰고 `STATUS.md`에 적는다.
4. **라이브러리 선택:** D3 v7 + vanilla JS로 고정한다. 다른 프레임워크는 쓰지 않는다.
5. **설치 실패(npm, pip):** 다른 버전을 시도하고, 그래도 안 되면 CDN 대신 로컬 파일로 넣는 방법을 쓴다. 결과는 기록한다.

## 0. 과제 조건 (반드시 지킬 것)

- 웹에서 동작해야 하고, **D3.js(v7) 또는 Vega-Lite**로 구현해야 한다. 이 프로젝트는 D3 v7을 쓴다.
- 시각화 컴포넌트는 3개 이상, 전부 인터랙티브해야 하고, primary 페르소나의 태스크를 받쳐야 한다.
- 외부 코드나 생성형 AI를 쓴 부분은 **공개 의무**가 있다. 네가 만들거나 고친 파일과 범위를 `AI_USAGE.md`에 계속 기록해라 (파일 경로, 새로 작성 / 수정, 한 줄 설명).
- UI 문구는 영어로 쓴다. 코드 주석은 한국어도 괜찮다.

## 1. 먼저 레포 파악 (코드 수정 없이)

1. 레포 구조를 훑어보고 아래 파일의 역할을 요약해라.
   - `src/simulation_engine/simulator.py`, `processes.py`, `entities.py`, `metrics.py`, `orderManager.py`
   - `src/policy/`
2. `src/simulation_engine/vis_export.py`가 있는지 확인해라. **없으면 "막혔을 때 규칙 1"을 따른다.**
   - 이 파일은 시뮬레이터 코드를 고치지 않고 래핑만 해서 CSV를 뽑는 추출기다.
   - 출력: `totes.csv`, `tote_sku.csv`, `kits.csv`, `stations.csv`, `dispatches.csv`, `decisions.csv`, `inventory_events.csv`, `candidates.csv.gz`, `meta.json`
3. 한 번 실행해서 출력과 컬럼을 확인해라. 실행 명령:
   `python src/simulation_engine/vis_export.py --size medium --seed 42 --load 0.8 --policies new_cpr --out vis_data`
   실행이 안 되면 "막혔을 때 규칙 1, 2"를 따른다.

**원칙: 시뮬레이터와 정책 로직(`simulator.py`, `processes.py`, `entities.py`, `src/policy/`)은 수정하지 않는다.** 필요한 로그는 `vis_export.py` 안에서 메서드를 감싸는 방식(기존 `attach_task_end_log`와 같은 패턴)으로만 추가한다.

## 2. 데이터 보강 (`vis_export.py`)

제안서에 적었지만 아직 추출되지 않는 값들이다.

### 2-1. `dock_wait` (트립별 도킹 대기 시간, 초)

- `processes.py`의 `agv_transport_process` 흐름: AMR이 스테이션 대기 위치에 도착하면 `agv.start_waiting()`을 호출하고, `station.dock.request()`(capacity 1)가 허락될 때까지 기다린다. 그다음 도킹 위치로 이동하고, `record_kitting_started`가 기록된다.
- `AGV.start_waiting`을 감싸서 그 시각(`sim.env.now`)을 `wait_start`로 기록해라. AMR id와 디스패치 순서로 트립에 매칭한다.
- `dock_wait = kitting_start − wait_start − (대기 위치 → 도킹 위치 이동시간)`
  - 이동시간을 정확히 빼기 어렵다면 `dock_wait = kitting_start − wait_start`로 두고, 그 정의를 주석과 `meta.json`에 명시해라.
- `dispatches.csv`에 `wait_start`, `dock_wait` 컬럼을 추가한다.

### 2-2. `partial_picks` (트립별)

- 정의: 그 트립에서 피킹한 SKU 중 `qty % lot_size != 0`인(카톤 일부만 꺼낸) SKU 수.
- `matched_parts`(JSON)와 `tote_sku.csv`의 `lot_size`로 계산해서 `dispatches.csv`에 추가한다.

### 2-3. `kit_sku.csv` (새 테이블)

- 컬럼: `kit_id, sku, qty_required, lot_size, cartons_needed = qty_required / lot_size`
- 출처: `Kit.required_parts`

### 2-4. 검증

- `dispatches` 행 수 == `meta.json`의 디스패치 수
- 모든 `dock_wait >= 0`
- `kit_sku`의 키트별 합 == `kits.csv`의 `qty_required`

## 3. 전처리: CSV → 웹용 JSON

`tools/build_vis_data.py`를 만들어 `vis_data/<policy>/` → `web/public/data/<policy>/`로 변환한다. pandas를 써도 된다.

| 파일 | 내용 |
|---|---|
| `trips.json` | 트립 1개 = 1객체: `trip_id, agv_id, tote_id, kit_id, station_id, t_dispatch, t_wait, t_dock, t_kit_end, t_return, dock_wait, distance_m, matched_qty, matched_parts, partial_picks` |
| `kits.json` | 키트 1개 = 1객체: `kit_id, station_id, start, end, deadline, tardiness, qty_required, n_sku_required, n_trips, late (bool), slip_start` + `progress: [[t, filled_ratio], …]` (트립의 `kitting_end`마다 누적 `matched_qty / qty_required`) |
| `busy_bins.json` | 5분(300 s) 구간별 가동 비율 행렬. 행 = 각 스테이션 + `AMR fleet` |
| `skus.json` | SKU 1개 = 1객체: `sku, n_totes_init, n_trips, cartons_needed, trips_per_carton, demand_qty, partial_share` |
| `meta.json` | 원본 meta + 정책 이름, 구간 길이, 시뮬레이션 종료 시각 |

필드 정의:
- **`slip_start`** (늦은 키트만): 시작~납기를 잇는 선형 목표 진행선 `(t − start) / (deadline − start)` 아래로 진행률이 내려간 뒤 다시는 회복하지 못한 첫 시각. 늦지 않은 키트는 `null`.
- **`busy_bins.json` 값:**
  - 스테이션 행: 구간 안에서 도킹 점유 시간(`t_dock`~`t_kit_end`) ÷ 구간 길이 (dock capacity = 1)
  - AMR fleet 행: 구간 안에서 트립 중인 AMR 시간 합(`t_dispatch`~`t_return`) ÷ (AMR 대수 × 구간 길이)
  - 값은 반드시 0~1. 고장(DOWN)은 가동에서 제외한다.
- **`skus.json`:**
  - `n_totes_init` = 시작 시 그 SKU 재고가 0보다 큰 토트 수
  - `n_trips` = `matched_parts`에 그 SKU가 들어간 트립 수
  - `cartons_needed` = `kit_sku`에서 SKU별 합
  - `trips_per_carton = n_trips / cartons_needed`
  - `partial_share` = 그 SKU 피킹 중 카톤 일부 피킹 비율

## 4. 웹 인터페이스 (`web/`)

- 스택: Vite + vanilla JS(ES modules) + D3 v7. 백엔드 없이 정적 JSON만 읽는다.
- 상단에서 정책(데이터 폴더)을 고를 수 있게 한다.

### 레이아웃 (제안서 스케치와 동일)

1. **헤더:** 제목 "Tote-Kit Dispatch Trace", shift 정보(토트 수, 키트 수, 트립 수), 필터 2개
   - "Late kits only" 토글
   - "Station: all / S1 / S2 …" 드롭다운
2. **1행:** V1이 전체 폭
3. **2행:** V2 | V3 | V4 (대략 폭 비율 4 : 5 : 6.5)

### 색 규칙 (모든 뷰 공통, 어기지 말 것)

- 잉크 `#16213A`, 배경 `#F5F3EE`, 카드 `#FBFAF7`, 그리드 `#D8D4CA`
- 파랑 `#2D63A8`: 기본 데이터, 선택 / 브러시 박스
- **주황 `#C2610F`: 지연(late)에만 쓴다.** 다른 의미로 쓰지 않는다.
- 카톤 일부 피킹: 진한 남색 `#16213A`. 일반 피킹: 연파랑 `#8FADD3`
- 히트맵: 순차 파랑 5단계 `#EEF2F8 → #2D5A94`

### V1 Station timeline (→ T1, T2)

- 스윔레인. 스테이션마다 한 행이고, 각 행에 위아래 두 줄을 둔다.
  - 키트 막대: `start`~`end`. 납기 이후 부분은 주황. 납기 위치에 잉크색 눈금.
  - 도킹 레인: 트립 블록 `t_dock`~`t_kit_end`, 파랑.
- x = 시간(초 → `h:mm` 표기).
- 인터랙션:
  - x축 brush와 휠 zoom으로 시간 창 선택 → V2, V3, V4가 그 창으로 필터링
  - 키트 막대 클릭 → `selectedKit` 설정 → V3에 열림
  - 툴팁: kit_id, 납기, 지연 시간, 트립 수
  - V4에서 SKU를 브러시하면 해당 SKU를 실은 트립 블록만 강조하고 나머지는 흐리게

### V2 Congestion heatmap (→ T2)

- 행 = 스테이션들 + AMR fleet, 열 = 5분 구간, 셀 명도 = 가동 비율(0~100%, 고정 도메인 [0, 1])
- 범례(그라데이션 + 0%, 100%) 필수
- 인터랙션:
  - 셀 클릭 → V1이 그 스테이션 행을 강조하고 그 시간대로 zoom
  - 툴팁: 자원, 시간대, 가동 비율
  - V1 시간 창 밖의 열은 흐리게

### V3 Kit trace (→ T1, T3)

- 선택된 키트 하나의 진행률 계단선: x = 시간, y = 0~100% 채움. 납기에 점선 세로선. 납기 이후 구간은 주황.
- 아래에 트립 글리프 줄: 트립마다 작은 막대 하나. 카톤 일부 피킹이 있는 트립은 진한 남색, 나머지는 연파랑.
- 늦은 키트면 `slip_start`에 표시를 하고 "slipped at h:mm" 라벨을 단다.
- 인터랙션:
  - 트립 호버 → 툴팁: tote_id, distance_m, dock_wait, matched_qty, partial_picks
  - 트립 클릭 → 그 트립이 피킹한 SKU들을 V4에서 강조
- 선택된 키트가 없으면 "Click a kit in V1" 안내를 띄운다.

### V4 SKU spread scatterplot (→ T4)

- SKU마다 점 하나
  - x = `n_totes_init` (교대 시작 시 그 SKU를 담은 토트 수)
  - y = `trips_per_carton`
  - 점 크기 = `cartons_needed` (sqrt 스케일)
  - 색: `partial_share >= 0.5`이면 진한 남색, 아니면 연파랑
- 축 제목을 반드시 단다.
- 인터랙션:
  - 2D brush로 SKU 선택 → `selectedSkus` → V1에서 해당 트립 강조
  - 호버 → 툴팁: sku, 담긴 토트 수, 트립 수, 필요 카톤, 일부 피킹 비율
  - V1 시간 창이 바뀌면 `n_trips`, `trips_per_carton`을 그 창 안의 트립으로 다시 계산 (x는 시작 시점 기준이라 고정)

### 상태 관리

- 단일 store에 상태를 모은다: `{policy, timeWindow, selectedKit, selectedSkus, lateOnly, station, hoveredTrip}`
- 뷰마다 `update(state)`를 구현한다. 상태가 바뀌면 영향받는 뷰만 다시 그린다.
- "Late kits only"는 V1 키트 막대와 V3 키트 선택 목록에 적용한다.
- Station 필터는 V1, V2 행과 V3, V4 데이터에 적용한다.

### 성능

- 트립은 약 1,000~1,500개, 토트는 1,000개 이상, SKU는 수백 개 수준이다. SVG로 충분하다.
- 느리면 V1 도킹 레인만 canvas로 바꾼다.

## 5. 마무리

1. `npm run dev`로 띄워서 인터랙션 4종을 직접 확인한다.
   - 시간 brush → V2~V4 연동
   - 히트맵 셀 클릭 → V1 zoom
   - 늦은 키트 클릭 → V3, V4 강조
   - V4 brush → V1 트립 강조
2. `README.md`에 데이터 생성 → 전처리 → 실행 명령을 순서대로 적는다.
3. `AI_USAGE.md`를 최종 정리한다.
4. 끝나면 남은 이슈와 확인하지 못한 것을 `STATUS.md` 맨 위에 요약한다.

## 하지 말 것

- 시뮬레이터, 정책 코드 수정
- 백엔드 서버 추가
- React 등 프레임워크 도입
- 나에게 질문하고 기다리기 (판단은 `STATUS.md`에 기록하고 진행)
- 위 색 규칙과 다른 색 사용
- 데이터가 없는 값을 임의로 채우기 (없으면 `null`로 두고 보고)
