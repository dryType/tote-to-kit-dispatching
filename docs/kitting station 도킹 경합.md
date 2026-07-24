
# Kitting Station 도킹 경합(Race Condition) 및 공간(Spatial) 제어 설계서

## 1. 개요 및 문제 정의

### 발생 문제

1. **순서 역전 (Race Condition):** 디스패칭 순서(Order Time)와 물리적 현장 도착 순서(Arrival Time)가 일치하지 않는 현상. (원거리 출발 AGV보다 근거리 출발 AGV가 먼저 도착)
2. **공간 중첩 버그 (Spatial Collision):** Kitting Station을 단일 좌표로 처리할 경우, 대기 중인 AGV와 작업 중인 AGV가 동일한 물리 좌표에 겹쳐서 서 있는 시뮬레이션 오류 발생.

### 해결 방안

SimPy의 `simpy.Resource`와 **공간 분리(Waiting Zone / Dock Spot)** 레이아웃을 결합함.

* **Waiting Zone (대기 구역):** 도킹 자원을 확보하지 못한 AGV가 대기하는 물리적 공간.
* **Dock Spot (도킹 위치):** 토트 하차 작업이 진행되는 실제 작업 공간 (자원 capacity = 1).

---

## 2. 공간 분리 및 자원 라이프사이클

```text
 [ Storage ]
      │
      ▼  (이동 1: Storage ──▶ Waiting Zone)
 [ Waiting Zone ] ───▶ [ dock.request() 대기 ]
      │
      ▼  (이동 2: Waiting Zone ──▶ Dock Spot / 자원 획득 직후 진입)
 [ Dock Spot ]    ───▶ [ Tote 하차 ] ───▶ [ dock.release() & AGV 이탈 ]
      │
      ▼  (자립 프로세스)
 [ Kitting 작업 ]

```

### 단계별 흐름

1. **Storage $\rightarrow$ Waiting Zone 이동:** 앞차의 도킹 여부와 무관하게 Station의 대기 구역 좌표(`waiting_x`, `waiting_y`)로 이동.
2. **`dock.request()` 대기:** Waiting Zone에 정차한 상태에서 Dock 자원이 해제될 때까지 대기.
3. **Waiting Zone $\rightarrow$ Dock Spot 진입:** 선행 AGV가 Dock을 비워 자원을 획득(`yield dock_req`)하는 순간, Dock Spot 좌표(`dock_x`, `dock_y`)로 진입 이동 수행 (`yield env.timeout`).
4. **Tote 하차 및 자원 해제:** Dock Spot에서 토트를 내려놓은 후 AGV가 Dock 구역을 이탈하면서 `dock.release()` 호출. $\rightarrow$ 대기 구역에 있던 후행 AGV가 즉시 Dock 진입 이동 시작.
5. **Kitting 작업:** 하차된 토트를 대상으로 Station 작업자가 독립 프로세스(`kitting_process`)로 피킹 진행.

---

## 3. 구현 코드 (`simulation_engine/processes.py`)

```python
import simpy
from typing import Optional
from simulation_engine.entities import AGV, DispatchCandidate


def agv_transport_process(
    env: simpy.Environment,
    agv: AGV,
    candidate: DispatchCandidate,
    metrics: Optional[object] = None
):
    """AGV 이송 및 Dock 진입/하차 프로세스"""
    agv.status = "busy"
    candidate.tote.is_busy = True

    # 1. Storage 위치로 이동 및 Tote 적재
    yield from _move_agv(
        env, agv,
        candidate.tote.position_x, candidate.tote.position_y,
        event_type="ARRIVED_AT_STORAGE", metrics=metrics
    )

    # 2. Station 'Waiting Zone'으로 이동 (Dock Spot이 아님)
    yield from _move_agv(
        env, agv,
        candidate.station.waiting_x, candidate.station.waiting_y,
        event_type="ARRIVED_AT_WAITING_ZONE", metrics=metrics
    )

    # 3. Dock 자원 요청 및 Waiting Zone 정차 대기
    arrival_time = env.now
    dock_req = candidate.station.dock.request()

    # 💡 Dock 자원이 해제될 때까지 Waiting Zone 좌표에서 대기
    yield dock_req 

    # 대기 시간 지표 수집
    waiting_time = env.now - arrival_time
    if waiting_time > 0 and metrics:
        metrics.log_event(
            time=env.now,
            entity_id=agv.agv_id,
            event_type="DOCKING_WAIT_COMPLETE",
            details={
                "station_id": candidate.station.station_id,
                "waiting_time": waiting_time
            }
        )

    # 4. Dock 자원 획득 후: Waiting Zone -> Dock Spot 진입 이동
    yield from _move_agv(
        env, agv,
        candidate.station.dock_x, candidate.station.dock_y,
        event_type="ARRIVED_AT_DOCK", metrics=metrics
    )
    
    # Tote 좌표를 Dock Spot으로 동기화
    candidate.tote.position_x = candidate.station.dock_x
    candidate.tote.position_y = candidate.station.dock_y

    # 5. Tote 하차 작업 (예: 2초 소요)
    yield env.timeout(2.0)

    # 6. 🔥 [핵심] 하차 완료 후 AGV가 Dock을 비우며 자원 해제 및 IDLE 전환
    # 자원이 해제되는 순간 Waiting Zone의 다음 AGV가 Dock 진입 이동을 시작함
    candidate.station.dock.release(dock_req)
    agv.status = "idle"

    # 7. Station Kitting 작업 프로세스 독립 트리거
    env.process(kitting_process(env, candidate, metrics))


def kitting_process(
    env: simpy.Environment,
    candidate: DispatchCandidate,
    metrics: Optional[object] = None
):
    """Station 피킹/키팅 전용 프로세스 (AGV와 독립 동작)"""
    kitting_time = 5.0
    yield env.timeout(kitting_time)

    # 실재고 차감 및 Kit 진행률 업데이트
    for part_id, qty in candidate.matched_parts.items():
        candidate.kit.add_parts(part_id, qty)
        candidate.tote.remove_component(part_id, qty)

    candidate.tote.is_busy = False

    if metrics:
        metrics.log_event(
            time=env.now,
            entity_id=candidate.station.station_id,
            event_type="KITTING_COMPLETE",
            details={
                "kit_id": candidate.kit.kit_id,
                "tote_id": candidate.tote.tote_id,
                "matched_parts": candidate.matched_parts,
            },
        )

```

---

## 4. 시뮬레이션 타임라인 시나리오 예시

* **Station Dock Capacity:** 1대
* **Waiting Zone $\rightarrow$ Dock Spot 이동 시간:** 2초
* **AGV A:** $t=0s$ 출발 (Waiting Zone까지 10초 소요)
* **AGV B:** $t=1s$ 출발 (Waiting Zone까지 2초 소요)
* **Tote 하차 소요 시간:** 2초

| 시각 (`env.now`) | 이벤트 발생 | AGV A 상태/위치 | AGV B 상태/위치 | Dock 자원 상태 |
| --- | --- | --- | --- | --- |
| **$t = 0.0s$** | AGV A 디스패치 | 이동 중 ($\rightarrow$ Waiting) | - | Free |
| **$t = 1.0s$** | AGV B 디스패치 | 이동 중 ($\rightarrow$ Waiting) | 이동 중 ($\rightarrow$ Waiting) | Free |
| **$t = 3.0s$** | **AGV B Waiting Zone 도착** | 이동 중 | **Waiting Zone 도착** $\rightarrow$ `dock.req` 획득 | **Busy (AGV B)** |
| **$t = 3.0s \sim 5.0s$** | AGV B Dock 진입 | 이동 중 | Waiting Zone $\rightarrow$ Dock Spot 진입 이동 (2초) | Busy (AGV B) |
| **$t = 5.0s \sim 7.0s$** | AGV B 하차 작업 | 이동 중 | Dock Spot에서 Tote 하차 중 (2초) | Busy (AGV B) |
| **$t = 7.0s$** | **AGV B 하차 완료 및 이탈** | 이동 중 | **Dock release & IDLE 전환** | **Free** |
| **$t = 10.0s$** | **AGV A Waiting Zone 도착** | **Waiting Zone 도착** $\rightarrow$ `dock.req` 획득 | 다른 미션 수행 가능 | **Busy (AGV A)** |
| **$t = 10.0s \sim 12.0s$** | AGV A Dock 진입 | Waiting Zone $\rightarrow$ Dock Spot 진입 이동 (2초) | - | Busy (AGV A) |

> **만약 AGV B 하차가 $t=12s$까지 지연되었다면?**
> AGV A는 $t=10s$에 Waiting Zone에 도착한 뒤 자원을 얻지 못해 **Waiting Zone 좌표에 정차하여 2초간 대기(Waiting)**한 후, $t=12s$에 AGV B가 이탈하면 Dock 진입 이동을 시작함.

---

## 5. 설계 핵심 요약

1. **물리적 공간 충돌 방지:** Waiting Zone과 Dock Spot을 분리하여 AGV 간 좌표 중첩(Collision) 현상을 완벽히 차단함.
2. **진입 지연 시간(Travel Latency) 반영:** 대기 상태가 해제된 후 Waiting Zone에서 Dock Spot까지 실제로 이동하는 데 걸리는 물리적 시간(2~3초 등)이 시뮬레이션 타임라인에 반영됨.
3. **AGV 회전율 극대화:** 하차 완료 즉시 Dock을 비우고 `dock.release()`를 수행하므로, Kitting 작업 시간(5초) 동안 Dock이 묶이지 않고 다음 대기 AGV가 연속적으로 진입할 수 있음.