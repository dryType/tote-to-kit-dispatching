"""작업 시간 교란: AGV 이동 시간과 스테이션 작업자 피킹(카톤 이송) 시간.

- 명목 시간에 평균 1인 로그정규 배수를 곱한다. 평균이 그대로라 명목 부하는 바뀌지 않는다.
- 소요 시간은 작업을 시작할 때 뽑고, 정책은 명목 시간만 본다.
- 난수 흐름을 교란 종류와 개체(AGV, 스테이션)별로 나눈다. 정책마다 작업 순서가 달라도
  같은 seed면 "AGV_03의 k번째 이동"은 같은 배수를 받으므로 정책끼리 공통 난수로 비교할 수 있다.
- 변동계수가 0이면 난수를 뽑지 않고 1을 돌려준다 (결정적 실행과 같은 결과).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class DisturbanceConfig:
    travel_cv: float = 0.0  # AGV 이동 구간마다
    picking_cv: float = 0.0  # 디스패치 1회의 카톤 이송 전체에 하나
    seed: int = 0


class Disturbance:
    def __init__(self, config: DisturbanceConfig):
        self.config = config
        self._streams: dict[tuple[str, str], random.Random] = {}

    def _stream(self, source: str, entity_id: str) -> random.Random:
        key = (source, entity_id)
        if key not in self._streams:
            # 문자열 seed는 PYTHONHASHSEED와 무관하게 재현된다
            self._streams[key] = random.Random(f"{self.config.seed}:{source}:{entity_id}")
        return self._streams[key]

    @staticmethod
    def _factor(cv: float, rng: random.Random) -> float:
        sigma = math.sqrt(math.log(1.0 + cv * cv))
        return rng.lognormvariate(-0.5 * sigma * sigma, sigma)

    def travel_factor(self, agv_id: str) -> float:
        if self.config.travel_cv <= 0:
            return 1.0
        return self._factor(self.config.travel_cv, self._stream("travel", agv_id))

    def picking_factor(self, station_id: str) -> float:
        if self.config.picking_cv <= 0:
            return 1.0
        return self._factor(self.config.picking_cv, self._stream("picking", station_id))
