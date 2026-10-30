# STATUS — Tote-Kit Dispatch Trace

지시서: `docs/vis_impl_prompt.md` (무인 실행 모드). 형식: `[단계] 한 일 / 내린 판단과 이유 / 남은 일`

## 최근 변경: V2·V4 수정 (2026-10-26, 두 번째 지시)

V2와 V4만 고쳤다. V1·V3, 시뮬레이터·정책 코드는 건드리지 않았다. 자세한 판단은 맨 아래 `[추가] V2·V4 수정` 절에 있다.

- **V2 Congestion heatmap**
  - 스테이션 셀 가운데에 평균 대기 AMR 수를 점으로 찍었다 (면적 비례, `#F5F3EE`, 테두리 없음, 대기 0이면 점 없음, AMR fleet 행 제외).
  - 범례에 점 크기 예시 3개(0.25 / 0.5 / 1)를 넣었다. 툴팁에 평균·최대 대기 AMR 수가 나온다. 설명 문구도 지시대로 바꿨다.
  - 데이터: `busy_bins.json`의 스테이션 행에 `queue`(평균), `max_queue`(구간 안 동시 최대)를 추가했고, 맨 위에 `queue_max`, `max_queue_overall`을 넣었다.
- **V4 SKU spread**
  - 부제를 질문으로 바꾸고, 카드 머리에 "Min cartons needed" 입력을 넣었다. 기본값은 하위 25% = 10이고 데이터셋을 바꾸거나 Reset all을 누르면 다시 10이 된다.
  - 기준 미만 SKU는 opacity 0.15로 흐리게 그리고, brush 선택과 ρ 계산에서 뺀다. 축 아래에 "Faded: …"를, 오른쪽 위에 "ρ = … (n = …)"를 표시한다.
- **확인** (모두 통과)
  - queue 값은 모두 0 이상이다. 스테이션별 queue 시간 합과 Σ(t_dock − t_wait)의 차이는 최대 0.013 s다 (4개 실행 전부).
  - V4 흐린 수 + n = 전체 SKU 80 (21 + 59, 기준 20일 때 33 + 47). S2 필터에서는 38 + 26 + 그 스테이션에서 쓰지 않는 16 = 80.
  - ρ를 pandas Spearman과 대조했다 (−0.3327, 1:00–2:00 창 −0.0650). 같은 실행(New CPR, load 1.0)을 헤드리스 Chrome으로 다시 띄워 V2·V4가 정상으로 그려지는 것을 확인했다. 콘솔 오류는 0이다.
- **눈여겨볼 것**
  1. **V4 질문의 답이 이 데이터에서는 "아니오" 쪽이다.** ρ ≈ −0.33이고 4개 실행 모두 같다. 다만 토트 수와 필요 카톤의 상관이 +0.72라서, 많은 토트에 흩어진 SKU는 수요가 큰 SKU이고 분모(카톤)도 크다. 음의 상관은 "흩어짐 효과"보다 수요 교란일 가능성이 크다. 결론으로 쓰기 전에 수요를 통제한 비교(예: 수요 구간별 ρ)가 필요하다.
  2. **V2 점이 작다.** 5분 열이 약 4 px 폭이라, 이웃 셀과 겹치지 않는 가장 큰 점은 지름 약 3.6 px다. 대기가 많은 구간은 보이지만 크기 차이는 읽기 어렵다. 개선안: V2 폭 넓히기(레이아웃 비율 변경이라 이번에는 하지 않음), 점만 15분 단위로 묶기, 점 대신 셀 아래쪽 막대.
  3. 대기 구간은 지시대로 `[t_wait, t_dock]`이다. `t_dock`이 도크 허락 뒤 1.33 s 이동을 포함하므로, 실제로 기다리지 않은 트립도 1.33 s씩 들어간다. 실측 영향은 셀 약 240개 중 1~4개에 "대기 없이 이동만 있는" 아주 작은 점이 생기고, 최댓값이 0.01 달라지는 정도라 그대로 두었다.

## 요약 (먼저 읽을 것) — 2026-10-26

**1~5단계 모두 끝났다. 실제 시뮬레이터 데이터로 동작한다** (합성 데이터 `tools/make_synthetic.py`는 필요 없어서 만들지 않았다). 커밋은 하지 않았다.

실행:
```powershell
$env:Path = "$env:LOCALAPPDATA\Programs\node-v24.22.1-win-x64;$env:Path"   # 아래 '꼭 알아둘 것' 1 참고
cd web; npm run dev     # http://localhost:5173/
```

**꼭 알아둘 것**
1. **이 PC에 Node.js가 없었다.** 공식 포터블 zip(v24.22.1 LTS, SHA-256 검증)을 `C:\Users\an\AppData\Local\Programs\node-v24.22.1-win-x64`에 풀었다. **PATH에는 넣지 않았다** (시스템 설정 변경을 피함). 위 첫 줄처럼 세션마다 PATH에 붙이거나, Node LTS를 정식 설치한 뒤 그 폴더를 지우면 된다.
2. **지시서 명령(L0.8)은 늦은 키트가 0개**라 지연 인코딩이 안 보인다. 그래서 L1.0의 greedy / cpr / new_cpr도 추출했고, **웹 기본 데이터셋은 `new_cpr_L1.0`**(늦은 키트 16/39)이다. L0.8은 상단 Run 드롭다운에서 고를 수 있다.
3. `vis_export.py`는 지시서 명령 그대로 실행하면 import 오류로 죽었다 → 규칙 2로 그 파일만 고쳤다. 시뮬레이터·정책 코드는 건드리지 않았다.

**확인한 것** (헤드리스 Chrome + puppeteer-core로 실제 마우스 이벤트를 보내고 DOM·상태·스크린샷 확인)
- 시간 brush → V2 창 밖 열 흐림(245/300), V3 목록 축소, V4 y 재계산 / 휠 zoom / 히트맵 셀 클릭 → V1 2:25–2:40 확대 + S1 행 강조 / 늦은 키트 클릭 → V3 slip 표시 + V4 해당 키트 SKU 23개 테두리 / V4 brush → V1 트립 1,105/1,407 흐림 / V3 트립 호버·클릭, Late kits only, Station 필터, 데이터셋 전환.
- 콘솔 오류 0, HTTP 4xx 0, `npm run build` 성공, 1000 px 폭에서 가로 스크롤 없음.

**확인하지 못한 것**
- 사람이 실제 브라우저로 만져본 적은 없다 (휠/트랙패드 감각, 드래그 팬과 클릭이 섞일 때의 느낌). Chrome 외 브라우저, 760 px 미만 폭 화면 캡처.
- 느린 PC에서 V1 brush 드래그 중 갱신 속도 (트립 1,400여 개 SVG를 매 이벤트마다 다시 배치한다. 이 PC에서는 문제 없었다).

**다시 볼 만한 판단** (자세한 이유는 각 단계 아래)
- V4 x축을 선형으로 두었다. 토트 수가 1~122라 점이 왼쪽(0~40)에 몰린다. 로그 축이 더 읽기 쉬울 수 있다.
- V4에서 시간 창을 걸면 `trips_per_carton = 창 안 트립 수 / 교대 전체 필요 카톤` (지시서 정의 그대로)이라 값이 작아진다. 분모를 창 안 키트의 카톤으로 바꿀지는 정할 일.
- 히트맵은 도크 점유가 대부분 70% 이상이라 위 두 단계 색에 몰린다 (지시서의 고정 도메인 [0, 1] 5단계 그대로).
- `window.__trace`(store 노출)는 헤드리스 확인용이다. 제출 전에 `web/src/main.js` 마지막 부분에서 지워도 된다.
- `vis_data/`(약 16 MB, 대부분 `candidates.csv.gz`)는 `.gitignore`에 없다. `web/public/data/`(약 2.4 MB)는 앱이 읽으므로 같이 커밋해야 한다.

---

## [1단계] 레포 파악 (코드 수정 없음)

### 한 일

파일 역할 요약:

| 파일 | 역할 |
|---|---|
| `src/simulation_engine/simulator.py` | `Simulator`: simpy 환경, `Metrics`, `Dispatcher`를 만들고 스테이션마다 첫 키트를 건다. `run()`은 디스패처 프로세스를 띄우고 `sim_time_limit`까지 돈다. |
| `src/simulation_engine/processes.py` | AGV 왕복 1건(`agv_transport_process`): 토트로 이동 → 집기 5 s → 스테이션 대기 위치로 이동 → `agv.start_waiting()` → `station.dock.request()`(capacity 1) 허락 대기 → 도킹 위치로 2 m 이동 → `start_docking` + `record_kitting_started` → `kitting_process`(카톤 이송: 온전한 카톤 10 s, 일부 카톤 20 s) → `record_kitting_completed` → 도크 반납 → 토트 자리로 복귀 + 내려놓기 5 s → `finish_task`. 키트 완료 시 `kit_replacement_process`(60 s 후 다음 키트). |
| `src/simulation_engine/entities.py` | 데이터 클래스. `Component`(부품 수량, lot_size, 카톤/데드스페이스), `Tote`, `Kit`(required/reserved/filled, 시작·완료 시각), `KittingStation`(dock 자원, 도크 점유 시간 누적), `AGV`(상태 머신), `DispatchCandidate`(`execute_dispatch`로 예약), `Position`. 대기 위치 = 스테이션 좌표에서 y − 2 m. |
| `src/simulation_engine/metrics.py` | 이벤트 로그(`dispatch`, `kitting_started`, `kitting_completed`, `kit_replacement`)와 지표(지연, 단편화 지수 0.3·(1−사용률)+0.7·데드스페이스율, 토트 상태 수, 거리, makespan). |
| `src/simulation_engine/orderManager.py` | 대기/활성 키트 목록. `pop_next_kit`은 투입 규칙(기본: 납기 순, `load_validation.build_simulator`에서는 slack 순)으로 다음 키트를 고른다. |
| `src/simulation_engine/dispatcher.py` | 쉬는 AGV가 있을 때마다 후보(`generate_candidates`)를 만들고 정책 `select`로 (후보, AGV)를 받아 실행, 이벤트 기록, AGV 프로세스 시작. |
| `src/policy/` | `base_policy.BasePolicy`(인터페이스). `greedy/`, `cpr/`(CPR Top-1, 단순 적응, ATC형 CPR, **NewCPR**, 적응형/상한 적응형 실험), `atc/`(키트 단위 ATC), `plan_policy.py`(교란 실험용 계획 기록·재실행). 모두 AGV는 토트에 가장 가까운 쉬는 AGV를 고른다. |

`src/simulation_engine/vis_export.py`: **있음** (untracked). 정책 래퍼(`CandidateLogPolicy`), `attach_task_end_log`, `export_tables`, CLI.

실행 결과 (`--size medium --seed 42 --load 0.8 --policies new_cpr`):
- 지시서 명령 그대로는 **실패**: `ModuleNotFoundError: No module named 'policy'`. 모듈 맨 위에서 `policy`를 import하는데 `sys.path`에 `src`를 넣는 코드는 `main()` 안에 있다. `PYTHONPATH=src`를 주면 성공 (8.5 s).
- 출력 경로는 `vis_data/<policy>/`가 아니라 `vis_data/medium_s42_L0.8/new_cpr/`.
- 규모: 토트 787, 키트 39, 스테이션 4, AGV 9, SKU 80, 디스패치 1,407, makespan 17,764 s (약 4 h 56 m).
- 컬럼은 `vis_export.py` 모듈 docstring과 같음. `dispatches.csv`에 `kitting_start/kitting_end/task_end`가 모든 행에 있음.

교차 확인:
- 스테이션별 Σ(`kitting_end − kitting_start`) == `stations.csv`의 `dock_time` (4개 모두 일치). → 도크 점유 = `kitting_start ~ kitting_end`.
- 같은 SKU는 모든 토트에서 `lot_size`가 같다 (80개 중 불일치 0).
- 단편화 지수 재계산값 == Metrics 값.

### 내린 판단과 이유

- **import 실패 → 막혔을 때 규칙 2 적용** (원인이 `vis_export.py` 안에 있음). 2단계에서 `vis_export.py` 맨 위에 `src`, `data` 경로를 넣는 코드를 옮긴다. 시뮬레이터/정책 코드는 건드리지 않는다.
- **L0.8에서는 늦은 키트가 0개** (greedy, cpr, new_cpr 모두). L1.0에서는 new_cpr 16/39, greedy 17/39, cpr 25/39가 늦다 (스크래치 디렉터리에서 후보 로그 없이 확인). 지연 관련 뷰(주황, slip_start, Late kits only)가 지시서 데이터로는 아무것도 보여주지 못하므로, **지시서 실행(new_cpr L0.8)에 더해 L1.0의 greedy / cpr / new_cpr도 추출**해서 정책 드롭다운에 넣는다. 데이터 폴더 이름은 `new_cpr`(L0.8, 지시서 그대로), `new_cpr_L1.0`, `greedy_L1.0`, `cpr_L1.0`.

### 남은 일

2단계 ~ 5단계.

---

## [2단계] 데이터 보강 (`vis_export.py`만 수정)

### 한 일

- **import 실패 수정** (규칙 2): `src`, `data`를 `sys.path`에 넣는 코드를 `main()` 안에서 모듈 맨 위로 옮겼다. 이제 지시서 명령이 `PYTHONPATH` 없이 돈다.
- **`attach_dock_wait_log(sim)`** 추가 (`attach_task_end_log`와 같은 패턴):
  - `AGV.start_waiting`을 감싸 `wait_start = sim.env.now` 기록.
  - 스테이션의 `dock.request`를 감싸, 바로 앞에서 대기를 시작한 AGV 기록에 요청 이벤트 콜백을 붙여 **도크 허락 시각 `dock_grant`**를 남긴다. (`agv_transport_process`에서 `start_waiting()` 다음 줄이 `dock.request()`이고 사이에 `yield`가 없어 짝이 확정된다.)
  - 트립 매칭은 기존 `_build_trips`처럼 AGV별 k번째 기록 = k번째 디스패치.
- `dispatches.csv`에 `partial_picks`, `wait_start`, `dock_grant`, `dock_wait` 추가.
- `kit_sku.csv` 추가: `kit_id, sku, qty_required, lot_size, cartons_needed`.
- `meta.json`에 `definitions`(컬럼 정의), `checks`(검증 결과), `total_agv_move_distance`(Metrics 값, 3단계 교차 확인용) 추가. `main()`이 검증 실패 항목을 출력.
- 추출 실행: `vis_data/medium_s42_L0.8/new_cpr` (지시서 명령), `vis_data/medium_s42_L1/{greedy,cpr,new_cpr}` (`--load 1.0`).

검증 결과 (4개 실행 모두 통과):
- dispatches 행 수 == `n_dispatch` (new_cpr L0.8: 1,407 == 1,407)
- `dock_wait >= 0`, 누락 0 (new_cpr L0.8: 최소 0, 최대 162.8 s, 평균 16.2 s, 40%가 0)
- `kit_sku` 키트별 합 == `kits.csv`의 `qty_required` (불일치 0)
- 추가 확인: `kitting_start − dock_grant − 명목 이동시간(2 m / 1.5 m/s = 1.333 s)`의 최대 절댓값 0.000667 s (소수 3자리 반올림 오차). 즉 지시서 식 `kitting_start − wait_start − 이동시간`과 같은 값이다.

### 내린 판단과 이유

- **`dock_wait` = `dock_grant − wait_start`** (정확한 정의). 이동시간을 빼는 근사 대신 도크 허락 시각을 직접 잡았다. 교란(`--dist-cv > 0`)이 있어도 이동시간 배수와 무관하게 정확하다. 정의는 코드 주석과 `meta.json`의 `definitions`에 적었다.
- **`partial_picks`의 lot_size**는 `tote_sku`의 (토트, 부품) 행에서 가져온다. 시뮬레이터 `kitting_process`의 일부 카톤 판정(`qty % lot_size > 0`)과 같은 조건.
- **`cartons_needed`는 올림하지 않은 실수** (`qty_required / lot_size`, 지시서 식 그대로). 예: 234 / 20 = 11.7.
- `dock_grant` 컬럼은 지시서에 없지만 `dock_wait` 계산 근거라 같이 남겼다.

### 남은 일

3단계 ~ 5단계.

---

## [3단계] 전처리 `tools/build_vis_data.py`

### 한 일

- `vis_data/<scenario>/<policy>/` → `web/public/data/<name>/`: `trips.json`, `kits.json`, `kit_sku.json`, `busy_bins.json`, `skus.json`, `meta.json`, 그리고 `web/public/data/index.json`(데이터셋 목록, 기본값). pandas 대신 표준 `csv`/`json`만 썼다.
- 변환한 데이터셋 4개 (모두 medium, seed 42):

  | 이름 | 정책 | 부하 | 트립 | 늦은 키트 |
  |---|---|---|---|---|
  | `new_cpr_L0.8` | New CPR | 0.8 (지시서 명령) | 1,407 | 0 / 39 |
  | `new_cpr_L1.0` | New CPR | 1.0 | 1,407 | 16 / 39 |
  | `greedy_L1.0` | Greedy | 1.0 | 1,408 | 17 / 39 |
  | `cpr_L1.0` | CPR Top-1 | 1.0 | 1,470 | 25 / 39 |

- 내장 검증(모두 통과, 결과는 각 `meta.json`의 `build_checks`): 가동 비율 0~1 / 완료 키트의 progress 마지막 값 = 1, 마지막 시각 = 완료 시각 / slip_start는 늦은 키트에만 / Σ`distance_m` = Metrics `total_agv_move_distance` / 스테이션별 Σ(`t_kit_end − t_dock`) = `stations.csv` dock_time.

### 내린 판단과 이유

- **데이터셋 이름 `<policy>_L<load>`**: 1단계에서 적은 `new_cpr`(L0.8) 대신 `new_cpr_L0.8`로 통일했다. 같은 정책을 부하별로 넣으니 이름에 부하가 있어야 구분된다.
- **웹 기본 데이터셋 = `new_cpr_L1.0`**: 지시서 실행(L0.8)은 늦은 키트가 0개라 지연 관련 인코딩(주황, slip, Late kits only)이 첫 화면에서 보이지 않는다. 드롭다운에서 `new_cpr_L0.8`을 고를 수 있다.
- **`t_dock` = `kitting_start`**: 스테이션의 도크 점유 누적(`start_docking`~`end_docking`)과 같은 구간이다. 도크 자원 자체는 허락 시각부터 잡히지만(이동 1.33 s 포함) 시뮬레이터 지표와 맞추었다.
- **`distance_m`**: `dispatches.csv`의 선택 후보 특징(쉬는 AGV 중 가장 가까운 AGV→토트 + 2×토트→스테이션)을 그대로 썼다. 모든 정책이 가장 가까운 쉬는 AGV를 고르므로 실제 이동거리와 같고, 합이 Metrics 값과 일치함을 검증했다.
- **시뮬레이션 종료 시각 `t_end` = max(makespan, 마지막 `t_return`)**: makespan은 마지막 키트 완료 시각이라 그 뒤 AGV 복귀(수십 초)가 잘린다. 히트맵 AMR 행이 복귀까지 포함하도록 했다.
- **마지막 5분 구간은 잘린 길이로 나눈다** (예: 46.75 s). 300 s로 나누면 마지막 열이 인위적으로 낮아진다.
- **progress 첫 점 `[start, 0]`**: 지시서는 kitting_end마다 누적값이라고만 했다. 시작 시각의 0%는 사실값이고 계단선에 필요해서 넣었다.
- **slip_start 알고리즘**: 진행률 p인 계단은 `start + p·(deadline − start)`까지 목표선 위에 있다. 이 시각이 그 계단 시작 이후인 마지막 계단의 그 시각이 답. 늦은 키트는 마지막 계단(완료) 직전에 반드시 목표선 아래이므로 항상 정의된다.
  - **납기 뒤에 투입된 키트**(new_cpr L1.0에서 2개, cpr L1.0에서 7개)는 `start ≥ deadline`이라 목표선이 정의되지 않는다. `slip_start = start`로 두고 `released_late = true` 플래그를 추가했다 (V3 라벨에 표시).
- **`late` = `tardiness > 1e-6`** (vis_export의 `tardy_kits`와 같은 기준).
- **`partial_share`**: (트립, SKU) 1쌍을 피킹 1회로 세고, 그중 `qty % lot_size != 0`인 비율. 피킹이 없으면 `null`.
- 지시서에 없는 필드를 몇 개 추가했다: trips의 `partial_skus`(V4 재계산, V1 강조용), kits의 `product/line/release_order/lateness/released_late`, `kit_sku.json`(스테이션 필터 시 SKU별 필요 카톤 재계산, 선택 키트의 SKU 강조용).

### 남은 일

4단계 ~ 5단계.

---

## [4단계] 웹 인터페이스 `web/`

### 한 일

- **설치**: 시스템에 Node.js가 없었다 (bash/PowerShell 모두 `node` 없음, winget만 있음). 공식 포터블 zip v24.22.1을 내려받아 SHA256SUMS로 검증한 뒤 `%LOCALAPPDATA%\Programs\node-v24.22.1-win-x64`에 풀었다. `npm install d3@7` → 7.9.0, `npm install -D vite` → 8.3.5. 설치 실패는 없었다.
- **구조**: `index.html`, `src/main.js`(store 연결, 헤더, 데이터셋 전환), `src/store.js`, `src/data.js`, `src/util.js`(색, 포맷, 공용 필터, 툴팁), `src/style.css`, `src/views/{timeline,heatmap,kittrace,skuscatter}.js`. 각 뷰는 `deps`(반응할 상태 키)와 `setData`, `update(state, changed)`를 가진다. store는 바뀐 키 집합을 넘기고, 뷰는 deps와 겹칠 때만 다시 그린다. 위치가 바뀌는 변경(시간 창, 스테이션, 크기)은 다시 배치하고, 선택·호버는 스타일만 바꾼다.
- **레이아웃**: 헤더(제목, 토트/키트/트립 수 등, Run·Late kits only·Station·Reset all) → V1 전체 폭 → V2 : V3 : V4 = 4 : 5 : 6.5. 1180 px 미만에서는 V2|V3 / V4, 760 px 미만에서는 한 열.
- **V1**: 스테이션마다 키트 레인(시작~납기 파랑, 납기 뒤 주황, 레인 위 잉크 눈금 = 납기)과 도킹 레인(`t_dock~t_kit_end` 파랑 블록). 아래 overview 띠에 x축 brush, 본문에 휠 zoom(드래그 팬 포함). brush와 zoom은 서로 맞춰진다. 키트 클릭 → `selectedKit`. V4/V3에서 SKU가 선택되면 그 SKU를 실은 트립만 진하고 나머지는 흐리다. V3 트립 호버 시 V1 블록에 테두리.
- **V2**: 5단계 순차 파랑(`#EEF2F8`→`#2D5A94`를 Lab 보간), 고정 도메인 [0, 1], 범례(5칸 + 0%, 100%). 셀 클릭 → V1 행 강조 + 그 시간대 zoom. 창 밖 열은 흐리게.
- **V3**: 진행률 계단선(납기 전 파랑, 납기 뒤 주황, clipPath로 나눔), 납기 점선, 목표 진행선(점선), 늦은 키트는 slip 지점에 주황 원과 "slipped at h:mm". 아래 트립 글리프(일부 카톤 피킹 있음 = 남색, 없음 = 연파랑). 선택 키트가 없으면 "Click a kit in V1".
- **V4**: x = `n_totes_init`, y = `trips_per_carton`, 크기 = `cartons_needed`(sqrt), 색 = `partial_share >= 0.5`. 축 제목, 색·크기 범례. 2D brush → `selectedSkus`. 시간 창·스테이션이 바뀌면 다시 계산.

### 내린 판단과 이유

- **상태 키 추가**: 지시서의 `{policy, timeWindow, selectedKit, selectedSkus, lateOnly, station, hoveredTrip}`에 `dataVersion`(데이터셋 교체 알림), `skuSource`(SKU 선택이 V4 brush인지 V3 트립 클릭인지), `selectedTrip`(V3 클릭 트립), `focusRow`/`focusCell`(V2 셀 클릭 강조)을 더했다. 상태 간 규칙은 `main.js`의 `normalize` 한 곳에 모았다:
  - 필터(Late kits only, Station)에 걸린 키트는 선택 해제 (V1에서 숨겨진 키트가 V3에 남지 않게).
  - 키트를 바꾸면 이전 키트의 트립 클릭으로 고른 SKU 선택은 해제.
- **"트립이 시간 창 안" = 도킹 구간 `[t_dock, t_kit_end]`이 창과 겹침**. V1에 보이는 블록과 같은 기준이라 뷰끼리 어긋나지 않는다. 키트는 `[start, end]`가 창과 겹치면 창 안.
- **V1 brush는 아래 overview 띠에 둔다** (focus + context). 본문 위에 brush를 두면 키트 클릭·트립 호버와 충돌한다. 휠 zoom과 드래그 팬은 본문에서. 최소 창 2분.
- **V2 셀 클릭 zoom 폭 = 그 구간 ± 한 구간 (15분)**. 5분만 보이면 트립 2~4개라 맥락이 없다. 같은 셀을 다시 누르면 강조만 해제.
- **V3 "필터링"**: 시간 창은 키트 선택 목록(창과 겹치는 키트만)과, 그래프에서 창 띠 표시 + 창 밖 글리프 흐림으로 반영했다. 키트 한 개의 진행을 창으로 잘라 보이면 납기·slip 맥락이 사라져서 x축은 키트 전체 구간으로 둔다.
- **V3 트립 클릭 → `selectedSkus`를 그 트립의 SKU로 설정** (V4 강조 + V1에서 그 SKU를 실은 트립 강조). V4 brush와 같은 선택 상태를 쓴다. V4 brush 상자는 이때 지운다.
- **V3 글리프 폭 = 도킹 구간, 앞의 가는 선 = 도킹 대기(`t_wait`→`t_dock`)**. 혼잡(T2)을 키트 단위로도 볼 수 있게 했다. 목표 진행선은 slip 정의를 눈으로 확인하게 하려고 넣었다 (납기 뒤 투입 키트는 정의되지 않아 생략).
- **slip 라벨과 원은 주황**: 지연에서 파생된 표시라 색 규칙(주황 = 지연 전용)에 맞는다.
- **V4 partial_share(색)**: 시간 창에서는 다시 계산하지 않는다 (지시서: n_trips, trips_per_carton만). 스테이션 필터에서는 그 스테이션 트립(교대 전체)으로 다시 계산하고, 필요 카톤도 그 스테이션 키트만 더한다. 점 크기 도메인은 데이터셋 전체 최댓값으로 고정해 필터를 바꿔도 크기를 비교할 수 있게 했다. 필요 카톤이 0인 SKU(그 스테이션에서 안 쓰는 SKU)는 y가 정의되지 않아 빼고 캡션에 개수를 적는다.
- **V4 y축은 다시 계산할 때마다 최댓값에 맞춘다**. 고정하면 짧은 창에서 점이 모두 바닥에 붙는다. 이때 brush 상자는 지우고 선택한 SKU 집합은 유지한다 (상태줄에 "N SKUs selected … Clear"). 창 크기만 바뀐 경우에는 brush 상자를 데이터 좌표로 되살린다.
- **V4 호버는 Delaunay 최근접 점**으로 찾는다. brush 오버레이가 점을 덮어도 툴팁이 뜬다.
- **V1 키트 막대 납기 전 부분은 파랑 16% 채움 + 파랑 테두리**. 30%로 했더니 "일반 피킹" 연파랑(`#8FADD3`)과 비슷해 보여서 낮췄다.
- **색 외 보조 글자색**: 잉크(`#16213A`)의 투명도만 바꿔 썼다. 새 색은 없다. 파비콘도 팔레트 색만 쓴 인라인 SVG(404 제거용).
- **드롭다운 라벨 "Run"**: 데이터 폴더가 정책 × 부하라서 "Policy"보다 정확하다. 표시는 "New CPR · load 1.0 · 16 late".
- 디버그 중 고친 것: 전체 페이지 캡처 때 뷰포트 크기가 바뀌어 V4가 다시 그려지며 brush 상자가 사라지던 문제(위 복원 로직), 납기 뒤 투입 키트의 slip 라벨이 계단선과 겹치던 문제(라벨을 위로), 확대 시 키트 라벨이 사라지던 문제(보이는 구간 왼쪽에 붙임), CSS 우선순위로 slip 라벨이 주황이 아니던 문제.

### 남은 일

5단계.

---

## [5단계] 마무리

### 한 일

- `npm run dev`로 띄우고 헤드리스 Chrome(puppeteer-core, 스크래치 폴더에 설치 — 프로젝트 의존성에는 넣지 않음)으로 인터랙션 4종을 실제 마우스 이벤트로 확인했다. 결과 (`new_cpr_L1.0`):
  1. 시간 brush(overview 35%→52% 드래그) → 창 1:43–2:33, V2 300칸 중 245칸 흐림, V3 목록 11개, V4 캡션·y 재계산, V1 축 1:45~2:30. 휠 zoom → 창이 좁아짐.
  2. 히트맵 셀(S1, 2:30–2:35) 클릭 → 창 2:25–2:40, V1 S1 행 강조, 헤더 "Window 2:25 – 2:40".
  3. 늦은 키트 KIT_0018_01 클릭 → V3 "late by 3 min", "slipped at 2:53", 글리프 37개 / V4 그 키트 SKU 23개 테두리.
  4. V4 brush → 19 SKU 선택, V1 트립 1,407개 중 1,105개 흐림.
  - 추가: V3 글리프 호버 툴팁(tote, distance, dock wait, matched qty, partial picks) + V1 블록 테두리, 글리프 클릭 → V4 1 SKU 선택·V1 1,398개 흐림, V4 점 호버 툴팁, Late kits only(키트 16개), Station S2(V1 1행, V2 2행), 데이터셋 전환(L0.8에서 "No late kits in this run").
  - 콘솔 오류·HTTP 4xx 없음, `npm run build` 성공(JS 132 kB, gzip 44 kB), 1000 px 폭에서 가로 스크롤 없음.
- `README.md`(비어 있었음)에 데이터 생성 → 전처리 → 실행 명령을 적었다.
- `AI_USAGE.md` 최종 정리.
- 정리: dev 서버 종료, `web/dist` 삭제, 내려받은 Node zip 삭제. 스크린샷과 확인 스크립트는 스크래치 폴더에만 있다.

### 내린 판단과 이유

- README와 AI_USAGE는 영어로 썼다 (UI 문구가 영어이고 과제 제출물로 읽힐 문서라서).
- 커밋하지 않았다 (요청 없음). 브랜치 `new-cpr-policy-design`에는 이 작업 전부터 커밋 안 된 변경이 많아서 섞이지 않게 두었다.

### 남은 일

- 사람이 실제 브라우저에서 한 번 만져보기 (위 '확인하지 못한 것').
- 위 '다시 볼 만한 판단' 중 고칠 것 고르기.
- Node.js 정식 설치 여부 결정.

---

## [추가] V2·V4 수정 (두 번째 지시, 2026-10-26)

### 한 일

- `tools/build_vis_data.py`
  - `busy_matrix`가 스테이션 행에 `queue`, `max_queue`를 붙인다.
    - `queue[k]` = 구간 k와 겹치는 [t_wait, t_dock] 시간 합 / 구간 길이 (소수 5자리).
    - `max_queue[k]` = 구간 안에서 동시에 [t_wait, t_dock]에 있던 AMR 수의 최댓값 (시작·끝 이벤트 sweep, 한 구간이 끝나는 시각에 다른 구간이 시작하면 겹치지 않음).
  - 맨 위에 `queue_available`, `queue_max`, `max_queue_overall`을 둔다.
  - `build_checks`에 `queue_nonnegative`, `queue_time_equals_sum_t_dock_minus_t_wait`(저장된 반올림 값으로 다시 더해 비교, 허용 1 s), `max_queue_ge_ceil_mean_queue`를 추가했다. 4개 실행 모두 통과 (최대 차이 0.013 s, `max_queue_overall` = 2, `queue_max` 0.78~0.90).
  - `t_wait`가 없는 트립이 하나라도 있으면 대기 데이터를 넣지 않는다 (`queue_available = false` → 웹은 점과 점 범례를 그리지 않음). 이번 데이터는 모든 트립에 `t_wait`가 있다.
- `web/src/views/heatmap.js`: 대기 점, 점 범례, 툴팁 행. 점은 창 밖 열이면 셀과 같이 흐려진다. `pointer-events: none`이라 클릭·호버는 아래 셀이 받는다.
- `web/index.html`: V2 설명 문구를 지시 문구로 바꿨고, V4 부제를 질문으로 바꾸고 "Min cartons needed" 입력을 넣었다.
- `web/src/views/skuscatter.js`: 흐림, brush 제외, Spearman ρ(평균 순위 처리), 축 아래 문구, 툴팁에 "Below N cartons — ratio unreliable, not selectable".
- `web/src/data.js`: 데이터셋별 기본 기준 `defaultMinCartons`. `web/src/main.js`: store 키 `minCartons`, 데이터셋 전환과 Reset all에서 기본값으로. `web/src/style.css`: 숫자 입력, 문구 스타일.

### 내린 판단과 이유

- **대기 구간은 지시 그대로 `[t_wait, t_dock]`**. 더 정확한 대기는 `[t_wait, t_wait + dock_wait]`(= 도크 허락까지)지만, 지시문의 계산식과 검증식(Σ(t_dock − t_wait))이 명시돼 있었고 실측 차이가 무시할 만해서(위 요약 3) 그대로 따랐다. 바꾸려면 `busy_matrix`의 `wait_iv` 한 줄과 검증식 하나만 고치면 된다.
- **나누는 길이**: 지시문은 300 s라고 했지만, 가동 비율과 같은 기준으로 마지막(잘린) 구간만 그 구간 길이로 나눴다. 나머지 구간은 모두 300 s다. 마지막 구간(교대 끝 수십 초)에는 대기가 없어 결과는 같다.
- **점 크기 스케일**: `d3.scaleSqrt`, 도메인 [0, max(1, queue_max)]. 실행끼리 비교할 수 있게 1 AMR로 고정하고, 넘는 데이터가 오면 늘린다. 1 AMR일 때 지름 = 5분 셀 폭(약 3.6 px)이라 이웃 점과 겹치지 않는다. 스테이션 AGV 상한이 2라 평균 대기는 1을 넘기 어렵다 (실측 최대 0.90).
- **범례 값 0.25 / 0.5 / 1** (지시문 예시는 0.5 / 1 / 2): 평균 대기가 2가 되는 구간은 이 설정에서 생길 수 없어서 실제 범위 안의 값으로 골랐다. 점 색이 `#F5F3EE`라 카드 바탕 위에서는 안 보이므로, 범례 점은 가장 진한 히트맵 칸 위에 실제 크기로 그렸다.
- **점이 연한 셀 위에서는 잘 안 보인다** (`#F5F3EE` vs `#EEF2F8`). 지시대로 색과 테두리 없음은 지켰다. 대기는 거의 가동률이 높은 진한 셀에서 생기므로 실제로 가려지는 점은 적다.
- **V4 기본 기준** = 데이터셋의 SKU별 필요 카톤(교대 전체, 스테이션 필터 없음) 분포의 하위 25%(d3.quantile, 선형 보간 = numpy 기본과 같음)를 반올림, 최소 1. 4개 실행 모두 9.92 → 10.
- **기준과 비교하는 카톤은 현재 화면의 값**이다. 스테이션 필터를 걸면 그 스테이션 키트의 카톤이라 흐려지는 SKU가 늘어난다 (S2: 38개). 기준값 자체는 필터를 바꿔도 유지된다.
- **"흐린 수 + n = 전체 SKU" 검증**은 전체 보기에서 정확히 성립한다 (21 + 59 = 80). 스테이션 필터에서는 그 스테이션에서 쓰지 않는 SKU(필요 카톤 0, y가 정의되지 않음)를 그릴 수 없으므로 "흐린 수 + n + 그리지 않은 수 = 80"으로 확인했다 (38 + 26 + 16). 그리지 않은 SKU를 "Faded"에 세면 화면에 없는 점을 흐렸다고 말하게 되어 따로 두었다 (캡션에 이미 개수를 표시함).
- **흐린 SKU의 링(선택 키트의 SKU)도 0.15**: 링은 그대로 두되, 믿기 어려운 점에 강한 파란 링이 시선을 끌지 않도록 점과 같은 투명도를 줬다.
- **기준을 바꿀 때 brush 선택**: 점 위치는 기준과 무관하므로 brush 상자를 그대로 두고, 같은 상자 안의 기준 이상 SKU로 선택을 다시 만든다 (확인: 기준 20 → 47개).
- **ρ는 기준 이상 SKU로**, x = `n_totes_init`, y = 현재 `trips_per_carton`(시간 창·스테이션 반영). 동순위는 평균 순위. n < 3이거나 한쪽 순위가 모두 같으면 "ρ = –".
- **입력 위치**: "헤더"를 V4 카드 머리로 해석했다 (V4 전용 설정이라서). 0 이상 실수를 받고, 빈 값·음수는 무시한다. 0이면 흐림이 꺼진다.

### 남은 일

- V2 점이 작은 문제(위 요약 2)를 어떻게 할지.
- V4 질문에 답하려면 수요 교란을 통제한 비교가 필요하다(위 요약 1). 지금 화면은 질문을 던지는 데까지만 한다.
