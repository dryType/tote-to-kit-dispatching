from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from simulation_engine.entities import AGV, DispatchCandidate, Kit, Tote
from simulation_engine.state import WorldStateSnapshot


class CPRScore:
    def __init__(
        self,
        alpha_1: float = 0.9,
        alpha_2: float = 0.0,
        alpha_3: float = 0.1,
        w_s1: float = 0.5,
        w_s2: float = 0.5,
    ):
        self.alpha_1 = alpha_1
        self.alpha_2 = alpha_2
        self.alpha_3 = alpha_3
        self.w_s1 = w_s1
        self.w_s2 = w_s2
        self.gamma1 = 0.2
        self.gamma2 = 0.3
        self.epsilon = 0.2
        self.beta = 0.1
        self.lambda_ = 0.006
        self.p = 2.0
        self.margin_sec = 1200.0
        self.max_clearance_cache: dict[str, dict[str, Any]] = {}
        self.dispatch_count: int = 0

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
        dispatch_count: int = 0,
    ) -> dict[str, Any]:
        st_urgency, st_progress, st_contribution = self.calc_st(candidate, now)
        st = st_urgency + st_progress + st_contribution
        sf = self.calc_sf(candidate, state.order_manager.get_all_kits())
        sd = self.calc_sd(candidate, agv, state, d_max=d_max)
        self.dispatch_count = dispatch_count

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

    def calc_sf(self, candidate: DispatchCandidate, kits: list[Kit]) -> float:
        tote = candidate.tote
        matched_parts = candidate.matched_parts

        if not tote.contents or not matched_parts:
            return 0.0

        component_empty_count = 0
        perfect_empty_count = 0
        after_carton_dead_space_total = 0
        for component in tote.contents:
            matched_qty = matched_parts.get(component.part_id, 0)
            if matched_qty <= 0:
                after_carton_dead_space_total += component.dead_space_volume_cm3
                continue

            after_qty = max(component.quantity - matched_qty, 0)
            after_last_carton_qty = after_qty % component.lot_size
            after_carton_dead_space_total += (
                0
                if after_last_carton_qty == 0
                else component.v_carton - (after_last_carton_qty * component.v_part)
            )
            if after_qty == 0:
                component_empty_count += 1

            if component.quantity == candidate.kit.required_parts[component.part_id]:
                perfect_empty_count += 1

        carton_dead_space_change_ratio = (
            tote.calc_carton_dead_space() - after_carton_dead_space_total
        ) / tote.max_capacity_cm3

        clearance_bonus = (0.5 * component_empty_count + perfect_empty_count) / len(
            tote.contents
        )

        future_penalty = max(
            0,
            self.get_or_compute_max_clearance(tote, kits)
            - (component_empty_count / len(tote.contents)),
        )

        return self.w_s1 * carton_dead_space_change_ratio + self.w_s2 * max(
            0, clearance_bonus - future_penalty
        )

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

    def get_or_compute_max_clearance(self, tote: Tote, kits: list[Kit]) -> float:
        cached = self.max_clearance_cache.get(tote.tote_id)

        if cached and cached["version"] == self.dispatch_count:
            return cached["max_clearance"]

        n_distinct_parts = len(tote.contents)
        if n_distinct_parts == 0:
            return 0.0

        max_clearance = 0.0
        for kit in kits:
            if kit.is_completed():
                continue

            remaining_parts = kit.get_remaining_parts()
            clearance_count = sum(
                1
                for part in tote.contents
                if remaining_parts.get(part.part_id, 0) >= part.quantity
            )
            max_clearance = max(max_clearance, clearance_count)

        max_ratio = max_clearance / n_distinct_parts

        self.max_clearance_cache[tote.tote_id] = {
            "max_clearance": max_ratio,
            "version": self.dispatch_count,
        }

        return max_ratio
