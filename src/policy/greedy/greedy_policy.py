from typing import List, Optional

from policy.base_policy import BasePolicy
from simulation_engine.entities import AGV, DispatchCandidate
from simulation_engine.state import WorldStateSnapshot


class GreedyPolicy(BasePolicy):
    @property
    def name(self):
        return "Greedy Policy"

    def select(
        self,
        candidates: List[DispatchCandidate],
        idle_agvs: List[AGV],
        state: WorldStateSnapshot,
    ) -> tuple[Optional[DispatchCandidate], Optional[AGV]]:
        if not candidates or not idle_agvs:
            return None

        min_start_time = min(c.kit.start_time_sec for c in candidates)

        same_deadline_candidates = [
            c for c in candidates if c.kit.start_time_sec == min_start_time
        ]
        best_candidate = max(same_deadline_candidates, key=self._calc_progress_score)
        best_agv = min(
            idle_agvs,
            key=lambda agv: agv.position.manhattan_distance_to(
                best_candidate.tote.position
            ),
        )

        return best_candidate, best_agv

    def _calc_progress_score(self, candidate: DispatchCandidate) -> float:
        total_req = sum(candidate.kit.required_parts.values())
        if total_req == 0:
            return 1.0

        current_filled = sum(candidate.kit.filled_parts.values())
        add_qty = sum(candidate.matched_parts.values())

        # 이번 이송 후 최종 진행률 (0.0 ~ 1.0)
        projected_rate = (current_filled + add_qty) / total_req

        # 이번 이송으로 100% 완공되면 보너스 점수 부여 (스테이션 회전율 극대화)
        is_completed = (current_filled + add_qty) >= total_req
        clearing_bonus = 1.0 if is_completed else 0.0

        return clearing_bonus + projected_rate
