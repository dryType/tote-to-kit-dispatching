from __future__ import annotations

import math
from typing import Any

import pandas as pd

from simulation_engine.entities import AGV


class Metrics:
    def __init__(self):
        self.event_logs: list[dict[str, Any]] = []
        self.dispatched_count = 0
        self.kitting_started_count = 0
        self.tote_kitting_completed_count = 0
        self.completed_kit_count = 0
        self.kit_replacement_count = 0

    @property
    def kitting_completed_count(self) -> int:
        return self.tote_kitting_completed_count

    def log_event(self, event_type: str, now: float, **payload: Any) -> None:
        self.event_logs.append({"type": event_type, "time": now, **payload})

    def record_dispatch(
        self,
        now: float,
        *,
        agv_id: str,
        tote_id: str,
        station_id: str,
        kit_id: str,
        matched_parts: dict[str, int],
    ) -> None:
        self.dispatched_count += 1
        self.log_event(
            "dispatch",
            now,
            agv_id=agv_id,
            tote_id=tote_id,
            station_id=station_id,
            kit_id=kit_id,
            matched_parts=matched_parts,
        )

    def record_kitting_started(
        self,
        now: float,
        *,
        agv_id: str,
        tote_id: str,
        station_id: str,
        kit_id: str,
    ) -> None:
        self.kitting_started_count += 1
        self.log_event(
            "kitting_started",
            now,
            agv_id=agv_id,
            tote_id=tote_id,
            station_id=station_id,
            kit_id=kit_id,
        )

    def record_kitting_completed(
        self,
        now: float,
        *,
        agv_id: str,
        tote_id: str,
        station_id: str,
        kit_id: str,
        transferred_parts: dict[str, int],
        completed: bool,
    ) -> None:
        self.tote_kitting_completed_count += 1
        if completed:
            self.completed_kit_count += 1
        self.log_event(
            "kitting_completed",
            now,
            agv_id=agv_id,
            tote_id=tote_id,
            station_id=station_id,
            kit_id=kit_id,
            transferred_parts=transferred_parts,
            completed=completed,
        )

    def record_kit_replacement(
        self,
        now: float,
        *,
        station_id: str,
        old_kit_id: str,
        new_kit_id: str | None,
    ) -> None:
        self.kit_replacement_count += 1
        self.log_event(
            "kit_replacement",
            now,
            station_id=station_id,
            old_kit_id=old_kit_id,
            new_kit_id=new_kit_id,
        )

    @property
    def completed_kits_count(self) -> int:
        return self.completed_kit_count

    def record_simulation_end(self, now: float) -> None:
        self.makespan = now

    # =========================================================================
    # 🎯 목적함수 계산 메서드들 (Objective Functions)
    # =========================================================================

    def _calc_hat_T(self, t_greedy: float) -> float:
        """① 총 납기 지연 지표 (Normalized Total Tardiness)"""
        if t_greedy <= 0:
            return 0.0

        total_sq_tardiness = sum(
            max(0.0, k["completion_time"] - k["deadline"]) ** 2
            for k in self.completed_kits_info
        )
        return total_sq_tardiness / t_greedy

    def _calc_hat_F(
        self,
        totes: list[Any],
        part_specs: dict[str, dict[str, float]],
        v_max: float,
        w_f1: float = 0.5,
        w_f2: float = 0.5,
    ) -> float:
        """② 파편화 지표 (Normalized Warehouse Fragmentation Index)"""
        if not totes:
            return 0.0

        total_f_score = 0.0

        for tote in totes:
            # tote.inventory: {part_model: current_quantity}
            q_jm = tote.inventory
            if sum(q_jm.values()) == 0:
                continue  # 재고가 없으면 f_score = 0

            v_carton_jm_sum = 0.0
            v_dead_jm_sum = 0.0

            for part_m, q in q_jm.items():
                if q <= 0 or part_m not in part_specs:
                    continue

                spec = part_specs[part_m]
                L_m = spec["L_m"]  # Carton 표준 입고 수량
                v_carton_m = spec["v_carton_m"]  # Carton 외형 부피
                v_m = spec["v_m"]  # 부품 낱개 부피

                carton_count = math.ceil(q / L_m)

                # V_carton,jm
                v_carton_jm_sum += carton_count * v_carton_m
                # V_dead,jm
                v_dead_jm_sum += (carton_count * L_m - q) * v_m

            f_score = w_f1 * (1.0 - (v_carton_jm_sum / v_max)) + w_f2 * (
                v_dead_jm_sum / v_max
            )
            total_f_score += f_score

        return total_f_score / len(totes)

    def _calc_hat_D(self, grid_x_max: float, grid_y_max: float) -> float:
        """③ AGV 이동 거리 지표 (Normalized Distance Index)"""
        num_events = len(self.dispatch_distances)
        if num_events == 0:
            return 0.0

        d_max = 3.0 * (grid_x_max + grid_y_max)
        total_actual_dist = sum(self.dispatch_distances)

        return total_actual_dist / (num_events * d_max)

    def calculate_global_objective(
        self,
        t_greedy: float,
        totes: list[Any],
        part_specs: dict[str, dict[str, float]],
        v_max: float,
        grid_x_max: float,
        grid_y_max: float,
        w_f1: float = 0.5,
        w_f2: float = 0.5,
    ) -> dict[str, float]:
        """
        최종 전역 목적함수 계산 (Z = 0.6*hat_T + 0.3*hat_F + 0.1*hat_D)
        """
        hat_T = self._calc_hat_T(t_greedy)
        hat_F = self._calc_hat_F(totes, part_specs, v_max, w_f1, w_f2)
        hat_D = self._calc_hat_D(grid_x_max, grid_y_max)

        Z = 0.6 * hat_T + 0.3 * hat_F + 0.1 * hat_D

        return {
            "Z": Z,
            "hat_T": hat_T,
            "hat_F": hat_F,
            "hat_D": hat_D,
        }

    def print_agv_utilization(self, agvs: list[AGV]) -> None:
        for agv in agvs:
            print(
                f"AGV {agv.agv_id} idle ratio: {agv.get_idle_ratio(self.makespan):.2f}"
            )

    def to_dataframe(self) -> pd.DataFrame:
        """이벤트 로그를 데이터프레임으로 바로 반환"""
        return pd.DataFrame(self.event_logs)

    def print_summary(self) -> None:
        """종료 시점 텍스트 리포트 출력"""
        print("\n=== Simulation Metrics Summary ===")
        print(f"Makespan (End Time)        : {self.makespan:.2f} s")
        print(f"Total Dispatches           : {self.dispatched_count}")
        print(f"Total Completed Kits       : {self.completed_kits_count}")
        print(f"Total Tote Process Completed: {self.kitting_completed_count}")
        print(f"Total Kit Replacements     : {self.kit_replacement_count}")
        print("==================================\n")
