## CPR(Composite Priority Rule) 

$$\text{CPR}(a, j, i) = \alpha_1 \cdot S_T(j,i) - \alpha_2 \cdot \Delta S_F(j,i) - \alpha_3 \cdot S_D(a,j,i)$$
- 디스패칭 이벤트 발생 시점에, 토트-키트 디스패칭 목록의 우선순위를 구하기 위한 수식화
- $\alpha_1 + \alpha_2 + \alpha_3 = 1.0 $

#### ① 납기 점수 ($S_T$)

$$S_T(j, i) = \text{Urgency}(i) + \gamma \cdot \text{Progress}(j, i)$$
- 키트 $i$의 시간적 긴급도($\text{Urgency}$)를 메인 뼈대로 삼고, 토트 $j$의 자재 진행률($\text{Progress}$)을 보조로 더해주는 구조.

- 첫번째 항 $Urgency(i)$:
$$\text{Urgency}(i) = \begin{cases} \epsilon + \beta \cdot \left( \frac{t_{\text{now}}}{d_i - \Delta t_{\text{margin}}} \right), & \text{if } t_{\text{now}} < d_i - \Delta t_{\text{margin}} \quad \text{(평상시)} \\ (\epsilon + \beta) + (1.0 - \beta) \cdot \left( 1 - e^{-\lambda \cdot x_i} \right)^p, & \text{if } t_{\text{now}} \ge d_i - \Delta t_{\text{margin}} \quad \text{(데드라인 임박 시)} \end{cases}$$
  - $t_{\text{now}}$ : 현재 시뮬레이션 타임스탬프(s)
  - $d_i$ : 키트 $i$의 납기 마감 시간(s)
  - $\Delta t_{\text{margin}}$ : 긴급도 가속을 시작할 안전마진(예: 600초로 설정하여, 데드라인 마감 600초 전 부터 urgency 급격하게 증가 시킴)
  - $\epsilon$ : 긴급도 항이 0이 되는걸 방지 하기 위한 최소 하한선(예: 0.2)
  - $\beta$ : 평상시 점진적 상승치 상한값 (예: 0.1)
  - $\lambda$ : 2단계 지수 포화 민감도 상수 (예: 0.006)
  - $p$ : 가속 곡선 지수 (예: $2$). 초반에는 완만하다가 데드라인 임박 시 수직 상승하게 만드는 역할

- 두번째 항 $\text{Progress}(j, i) = \begin{cases} \frac{\sum_{m \in M} \min(r_{im}, q_{jm})}{\sum_{m \in M} r_{im}}, & \text{if } \sum_{m \in M} r_{im} > 0 \\ 0, & \text{if } \sum_{m \in M} r_{im} = 0 \end{cases}$
  - $r_{im}$ : 현재 시점 키트 $i$에 남은 부품 $m$의 잔여 요구 수량 (Remaining Demand)
  - $q_{jm}$ :  현재 토트 $j$에 담겨 있는 부품 $m$의 재고 수량 (Tote Inventory)

- Progress 미세 가중치 $\gamma$
  - 납기 시간 차이가 어느정도 난다면, 덜 급한 키트의 Progress 점수가 높더라도 점수가 역전이 안되게 하는 장치


② 파편화 점수 ($\Delta S_F$) 
$$\Delta S_F(j, i) = f_{\text{score}}(j') - f_{\text{score}}(j)$$
- 피킹 작업 전 후의 파편화 수치 변화량
- $f_{\text{score}}$ : 목적함수에 정의된 파편화 점수
- $j$ : 현재 토트 $j$의 상태 (자재 차감 전)
- $j'$ : 토트 $j$에서 키트 $i$의 요구 부품을 공급한 직후의 예상 토트 상태 (자재 차감 후)

​
③ 이동거리 점수 ($S_D$)
$$\displaystyle S_D(a, j, i) = \frac{D_{\text{actual}}(a, j, i)}{D_{\text{max}}}$$

- 디스패칭 의사결정에 의한 AGV의 이동거리 패널티 점수
- $D_{\text{actual}}$ : 목적함수에 정의된, 디스패칭 이벤트에 의해 발생할 AGV 이동거리
- $D_{\text{max}}$ : 목적함수에 정의된, AGV의 최대 이동거리



---

## CPR (Composite Priority Rule) 스코어링 모델

$$\text{CPR}(a, j, i) = \alpha_1 \cdot S_T(j, i) - \alpha_2 \cdot \Delta S_F(j, i) - \alpha_3 \cdot S_D(a, j, i)$$

- 실시간 디스패칭 이벤트 발생 시점에 가용한 AGV $a \in A$, 보관 랙의 토트 $j \in \mathcal{T}$, 그리고 대기 중인 활성 키트 $i \in K$ 조합의 매칭 우선순위를 결정하는 복합 규칙 수식임.
- 각 평가지표의 가중치 변수는 다음 제약조건을 만족함:
$$\alpha_1 + \alpha_2 + \alpha_3 = 1.0$$

---

### ① 납기 점수 ($S_T$)

$$S_T(j, i) = \text{Urgency}(i) + \gamma \cdot \text{Progress}(j, i)$$

- 키트 $i$의 시간적 긴급도($\text{Urgency}$)를 기본 뼈대로 설정하고, 해당 토트 $j$가 키트 $i$의 잔여 오더를 해결하는 기여도($\text{Progress}$)를 보조 버프로 결합하는 합연산 구조임.

#### 1) 긴급도 항 ($\text{Urgency}$)
$$\text{Urgency}(i) = \begin{cases} \epsilon + \beta \cdot \left( \frac{t_{\text{now}}}{d_i - \Delta t_{\text{margin}}} \right), & \text{if } t_{\text{now}} < d_i - \Delta t_{\text{margin}} \quad \text{(평상시)} \\ (\epsilon + \beta) + (1.0 - \beta) \cdot \left( 1 - e^{-\lambda \cdot x_i} \right)^p, & \text{if } t_{\text{now}} \ge d_i - \Delta t_{\text{margin}} \quad \text{(데드라인 임박 시)} \end{cases}$$

- $t_{\text{now}}$ : 현재 시뮬레이션 타임스탬프 (s)
- $d_i$ : 키트 $i$의 납기 마감 시각 (s)
- $\Delta t_{\text{margin}}$ : 긴급도 급증(가속)을 시작할 안전마진 임계 시간 버퍼 (s)
- $x_i = t_{\text{now}} - (d_i - \Delta t_{\text{margin}})$ : 안전마진 진입 후 누적 경과 시간 (s)
- $\epsilon$ : 긴급도 점수가 $0$으로 수렴하여 매칭 우선순위에서 완전히 배제되는 현상을 방지하기 위한 최소 하한값
- $\beta$ : 평상시 구간에서의 선형 상승 폭 상한값
- $\lambda$ : 임박 구간 진입 후 지수 포화 곡선의 민감도를 통제하는 상수
- $p$ : 마감 직전 시점에 지수 수식을 한 차례 더 가속화하여 수직 상승을 유도하는 가속 지수

#### 2) 오더 진행률 항 ($\text{Progress}$)
$$\text{Progress}(j, i) = \begin{cases} \frac{\sum_{m \in M} \min(r_{im}, q_{jm})}{\sum_{m \in M} r_{im}}, & \text{if } \sum_{m \in M} r_{im} > 0 \\ 0, & \text{if } \sum_{m \in M} r_{im} = 0 \end{cases}$$

- $r_{im}$ : 현재 의사결정 시점 기준 키트 $i$가 요구하는 부품 $m$의 잔여 오더 요구량 (Remaining Demand)
- $q_{jm}$ : 토트 $j$에 담겨 있는 부품 $m$의 실시간 재고 수량 (Tote Inventory)
- **물리적 효과**: 잔여 오더 요구량($\sum r_{im}$)을 분모로 두어, 조립 완료 직전 단계에 도달한 키트의 잔여 소량 오더를 빠르게 털어내는 재공(WIP) 최소화 메커니즘을 수행함.

#### 3) 오더 진행률 미세 가중치 ($\gamma$)
- 납기 긴급도 수준이 유의미하게 차이 날 때, 오더 진행률 점수의 하극상에 의해 더 급한 오더가 지연되는 우선순위 역전 현상을 방지하는 밸런서 장치임.
- 임의의 두 키트 간 하극상을 방지하고자 하는 최소 긴급도 점수 격차 임계값을 $\Delta U_{\text{threshold}}$로 정의할 때, 가중치 $\gamma$는 다음 제약 조건을 만족하도록 설정함:
$$\gamma < \Delta U_{\text{threshold}}$$

---

### ② 파편화 변동 점수 ($\Delta S_F$)

$$\Delta S_F(j, i) = f_{\text{score}}(j') - f_{\text{score}}(j)$$

- 토트 $j$에서 키트 $i$의 요구 부품을 피킹하기 전과 후의 토트 단위 공간 파편화 수치의 변동량을 측정함.
- $f_{\text{score}}$ : 전역 목적함수 $\hat{F}$ 내에 정의된 동일한 토트 파편화 평가 함수를 재사용함.
- $j$ : 자재 피킹 작업 전의 현재 토트 $j$의 재고 상태
- $j'$ : 토트 $j$에서 키트 $i$의 요구 부품을 공급한 직후의 가상 잔여 재고 상태
  - 토트 $j'$의 가상 잔여 재고량은 $q'_{jm} = q_{jm} - \min(r_{im}, q_{jm})$ 수식에 의해 업데이트됨.
- **물리적 효과**: 본 지표를 최소화하는 방향으로 우선순위를 설정함으로써, 잔량이 얼마 남지 않은 토트를 우선적으로 완전히 비워내어 창고 적재 공간을 확보하는 용기 통폐합(Consolidation) 효과를 유도함.

---

### ③ 이동거리 점수 ($S_D$)

$$S_D(a, j, i) = \frac{D_{\text{actual}}(a, j, i)}{D_{\text{max}}}$$

- 단일 디스패칭 의사결정에 의해 발생하는 AGV $a$의 실시간 주행 이동 거리 페널티 점수이며, 값의 범위는 $[0, 1]$로 제한됨.
- $D_{\text{actual}}(a, j, i)$ : 선택된 AGV $a$, 토트 $j$, 키트 $i$의 물리 좌표 기반 실제 예상 맨해튼 주행 거리
  $$D_{\text{actual}}(a, j, i) = \left( |x_a - x_j| + |y_a - y_j| \right) + 2 \times \left( |x_j - x_{s(i)}| + |y_j - y_{s(i)}| \right)$$
  - $(x_a, y_a)$ : AGV $a \in A$의 현재 위치 좌표
  - $(x_j, y_j)$ : 토트 $j \in \mathcal{T}$의 보관 랙 위치 좌표
  - $(x_{s(i)}, y_{s(i)})$ : 키트 $i \in K$가 작업 중인 키팅 스테이션 $s(i) \in S$의 위치 좌표
- $D_{\text{max}}$ : 단일 디스패칭 의사결정 시 기하학적 구조상 발생할 수 있는 이론적 최대 맨해튼 주행 거리 상수
  $$D_{\text{max}} = 3 \times (X_{\text{max}} + Y_{\text{max}})$$