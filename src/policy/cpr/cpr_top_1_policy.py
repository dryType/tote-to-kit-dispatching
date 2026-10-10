from dataclasses import replace
from typing import Any

from policy.base_policy import BasePolicy
from policy.cpr.cpr_score import CPRScore
from simulation_engine.entities import AGV, DispatchCandidate
from simulation_engine.state import WorldStateSnapshot


class CPRTop1Policy(BasePolicy):
    def __init__(
        self,
        alpha_1: float = 0.9,
        alpha_2: float = 0.0,
        alpha_3: float = 0.1,
        w_s1: float = 0.5,
        w_s2: float = 0.5,
        g1: float = 0.2,
        g2: float = 0.3,
        margin_sec: float = 1200.0,
        lmb: float = 0.006,
        p: float = 2.0,
        epsilon: float = 0.2,
        beta: float = 0.1,
    ):
        self.scorer = CPRScore(
            alpha_1=alpha_1,
            alpha_2=alpha_2,
            alpha_3=alpha_3,
            w_s1=w_s1,
            w_s2=w_s2,
            gamma1=g1,
            gamma2=g2,
            margin_sec=margin_sec,
            lambda_=lmb,
            p=p,
            epsilon=epsilon,
            beta=beta,
        )

    @property
    def name(self):
        return "CPR Top-1 Policy"

    def select(
        self,
        now: float,
        candidates: list[DispatchCandidate],
        idle_agvs: list[AGV],
        state: WorldStateSnapshot,
        dispatched_count: int,
    ) -> tuple[DispatchCandidate | None, AGV | None]:
        if not candidates or not idle_agvs:
            return None, None

        best_candidate: DispatchCandidate | None = None
        best_agv: AGV | None = None
        best_score = float("-inf")
        d_max = self.scorer._calc_d_max(state)
        best_score_info: dict[str, Any] | None = None

        for candidate in candidates:
            nearest_agv = min(
                idle_agvs,
                key=lambda agv: agv.position.manhattan_distance_to(
                    candidate.tote.position
                ),
            )

            score_info = self.scorer.build_score_info(
                now,
                candidate,
                nearest_agv,
                state,
                d_max=d_max,
                dispatch_count=dispatched_count,
            )
            score = score_info["total_score"]
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_agv = nearest_agv
                best_score_info = score_info

        if best_candidate is not None and best_score_info is not None:
            best_candidate = replace(best_candidate, score_info=best_score_info)

        return best_candidate, best_agv
