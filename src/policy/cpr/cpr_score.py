from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from simulation_engine.entities import AGV, DispatchCandidate, Kit
from simulation_engine.state import WorldStateSnapshot


@dataclass(frozen=True)
class CPRScore:
    alpha_1: float = 0.9
    alpha_2: float = 0.0
    alpha_3: float = 0.1
    gamma1: float = 0.2
    gamma2: float = 0.3
    epsilon: float = 0.2
    beta: float = 0.1
    lambda_: float = 0.006
    p: float = 2.0
    margin_sec: float = 1200.0
    w_s1: float = 0.5
    w_s2: float = 0.5

    def score(
        self,
        now: float,
        candidate: DispatchCandidate,
        agv: AGV,
        state: WorldStateSnapshot,
        d_max: float | None = None,
    ) -> float:
        return self.build_score_info(now, candidate, agv, state, d_max=d_max)[
            "total_score"
        ]

    def build_score_info(
        self,
        now: float,
        candidate: DispatchCandidate,
        agv: AGV,
        state: WorldStateSnapshot,
        d_max: float | None = None,
    ) -> dict[str, Any]:
        st_urgency, st_progress, st_contribution = self.calc_st(candidate, now)
        st = st_urgency + st_progress + st_contribution
        sf = self.calc_sf(candidate)
        sd = self.calc_sd(candidate, agv, state, d_max=d_max)

        return {
            "deadline": float(candidate.kit.deadline_time_sec or 0.0),
            "st": st,
            "st_urgency": st_urgency,
            "st_progress": st_progress,
            "st_contribution": st_contribution,
            "sf": sf,
            "sd": sd,
            "alpha_1": self.alpha_1,
            "alpha_2": self.alpha_2,
            "alpha_3": self.alpha_3,
            "gamma1": self.gamma1,
            "gamma2": self.gamma2,
            "epsilon": self.epsilon,
            "beta": self.beta,
            "lambda_": self.lambda_,
            "p": self.p,
            "margin_sec": self.margin_sec,
            "total_score": self.alpha_1 * st + self.alpha_2 * sf - self.alpha_3 * sd,
        }

    def calc_st(
        self, candidate: DispatchCandidate, now: float
    ) -> tuple[float, float, float]:
        urgency = self.calc_urgency(candidate.kit, now)
        total_progress = self.gamma1 * (1.0 - self.calc_progress(candidate.kit))
        contribution = self.gamma2 * self.calc_contribution(candidate)

        return urgency, total_progress, contribution

    def calc_urgency(self, kit, now: float) -> float:
        deadline = float(kit.deadline_time_sec or 0.0)
        threshold = deadline - self.margin_sec

        if now < threshold:
            denominator = threshold if threshold > 0 else 1.0
            return self.epsilon + self.beta * (now / denominator)

        x_i = now - threshold
        return (self.epsilon + self.beta) + (1.0 - self.beta) * (
            1.0 - math.exp(-self.lambda_ * x_i)
        ) ** self.p

    def calc_progress(self, kit: Kit) -> float:
        return kit.get_reserved_progress_ratio()

    def calc_contribution(self, candidate: DispatchCandidate) -> float:
        total_required = sum(candidate.kit.get_remaining_parts().values())
        if total_required <= 0:
            return 0.0

        return sum(candidate.matched_parts.values()) / total_required

    def calc_sf(self, candidate: DispatchCandidate) -> float:
        tote = candidate.tote
        matched_parts = candidate.matched_parts

        if not tote.contents or not matched_parts:
            return 0.0

        score = 0.0
        any_remaining = False

        for component in tote.contents:
            matched_qty = matched_parts.get(component.part_id, 0)
            if matched_qty <= 0:
                if component.quantity > 0:
                    any_remaining = True
                continue

            lot_size = component.lot_size or 1
            before_qty = component.quantity
            after_qty = max(before_qty - matched_qty, 0)

            before_ratio = math.ceil(before_qty / lot_size) - (before_qty / lot_size)
            after_ratio = (
                math.ceil(after_qty / lot_size) - (after_qty / lot_size)
                if after_qty > 0
                else 0.0
            )
            score += after_ratio - before_ratio

            if after_qty > 0:
                any_remaining = True

        return self.w_s1 * score + self.w_s2 * (1.0 if not any_remaining else 0.0)

    def calc_sd(
        self,
        candidate: DispatchCandidate,
        agv: AGV,
        state: WorldStateSnapshot,
        d_max: float | None = None,
    ) -> float:
        if (
            agv.position is None
            or candidate.tote.position is None
            or candidate.station.position is None
        ):
            return 0.0

        d_actual = agv.position.manhattan_distance_to(
            candidate.tote.position
        ) + 2.0 * candidate.tote.position.manhattan_distance_to(
            candidate.station.position
        )
        d_max = d_max or self._calc_d_max(state)
        return (d_actual / d_max) ** 2

    def _calc_d_max(self, state: WorldStateSnapshot) -> float:
        positions = []

        for agv in state.agvs.values():
            if agv.position is not None:
                positions.append(agv.position)

        for tote in state.totes.values():
            if tote.position is not None:
                positions.append(tote.position)

        for station in state.stations.values():
            if station.position is not None:
                positions.append(station.position)

        if not positions:
            return 1.0

        max_x = max(position.x for position in positions)
        max_y = max(position.y for position in positions)
        return max(3.0 * (max_x + max_y), 1.0)
