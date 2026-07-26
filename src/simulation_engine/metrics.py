from __future__ import annotations

import math
from typing import Any

import pandas as pd

from policy.base_policy import BasePolicy
from simulation_engine.entities import AGV, Kit, KittingStation, Tote
from simulation_engine.orderManager import OrderManager


class Metrics:
    def __init__(
        self,
        agvs: list[AGV],
        stations: list[KittingStation],
        totes: list[Tote],
        order_manager: OrderManager,
        policy: BasePolicy,
    ):
        self.event_logs: list[dict[str, Any]] = []
        self.dispatched_count = 0
        self.kitting_started_count = 0
        self.tote_kitting_completed_count = 0
        self.completed_kit_count = 0
        self.kit_replacement_count = 0
        self.agvs = agvs
        self.stations = stations
        self.totes = totes
        self.order_manager = order_manager
        self.policy = policy

    @property
    def kitting_completed_count(self) -> int:
        return self.tote_kitting_completed_count

    def log_event(self, event_type: str, now: float, **payload: Any) -> None:
        self.event_logs.append({"type": event_type, "time": now, **payload})

    def record_dispatch(
        self,
        now: float,
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

    def export_to_html_report(
        self,
        kits: list[Kit],
        totes: list[Tote],
        filename: str = "simulation_report.html",
    ):
        """전체 이력을 브라우저에서 바로 볼 수 있는 HTML 리포트로 추출"""

        # 1. 데이터 프레임 생성 (이전 로직 동일)
        # [Tote DataFrame]
        tote_logs = []
        for tote in totes:
            history = getattr(tote, "assigned_history", [])
            assigned_kits = [h[0] for h in history] if history else []
            tote_logs.append(
                {
                    "Tote ID": tote.tote_id,
                    "총 이송 횟수": len(history),
                    "잔량": f"{tote.get_remaining_component_summary()}",
                    "할당된 Kit 목록": ", ".join(assigned_kits),
                }
            )
        df_totes = pd.DataFrame(tote_logs)

        # [Kit Summary DataFrame]
        kit_logs = []
        for kit in kits:
            history = getattr(kit, "tote_reservation_history", [])
            unique_totes = list(set(h["tote_id"] for h in history)) if history else []
            start_t = getattr(kit, "start_time", 0.0)
            comp_t = getattr(kit, "completed_time", 0.0)
            deadline = getattr(kit, "deadline", 0.0)
            tardiness = max(0.0, comp_t - deadline) if comp_t else 0.0

            kit_logs.append(
                {
                    "Kit ID": kit.kit_id,
                    "투입 토트 수": len(unique_totes),
                    "총 배차 횟수": len(history),
                    "소요 시간(s)": round(comp_t - start_t, 1) if comp_t else "-",
                    "데드라인(s)": deadline,
                    "지연 시간(s)": round(tardiness, 1),
                    "지연 여부": "LATE" if tardiness > 0 else "OK",
                }
            )
        df_kits = pd.DataFrame(kit_logs)

        # [Kit Progress Timeline DataFrame]
        progress_logs = []
        for kit in kits:
            history = getattr(kit, "tote_reservation_history", [])
            prev_prog = 0.0
            for step, h in enumerate(history, 1):
                curr_prog = h.get("current_progress", 0.0)
                gain = curr_prog - prev_prog
                progress_logs.append(
                    {
                        "Kit ID": kit.kit_id,
                        "Step": step,
                        "할당 토트": h.get("tote_id"),
                        "할당 시각(s)": round(h.get("assigned_at", 0.0), 1),
                        "부품 매칭 내역": str(h.get("matched_parts")),
                        "진행률 상승폭": f"+{gain * 100:.1f}%p",
                        "누적 진행률": f"{curr_prog * 100:.1f}%",
                    }
                )
                prev_prog = curr_prog
        df_timeline = pd.DataFrame(progress_logs)

        # 2. HTML 템플릿 및 CSS 스타일 정의
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Simulation Results Report</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f5f5f5; }}
                h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
                h2 {{ color: #555; margin-top: 30px; }}
                .table-container {{ max-height: 400px; overflow-y: auto; background: white; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; }}
                th {{ background-color: #4CAF50; color: white; position: sticky; top: 0; padding: 10px; }}
                td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
                tr:hover {{ background-color: #f1f1f1; }}
                .late {{ color: red; font-weight: bold; }}
                .ok {{ color: green; font-weight: bold; }}
            </style>
        </head>
        <body>
            <h1>📊 물류 시뮬레이션 전수 분석 리포트</h1>
            
            <h2>📦 1. 전체 토트(Tote) 상태 및 이력</h2>
            <div class="table-container">
                {df_totes.to_html(index=False, classes="data-table")}
            </div>

            <h2>📋 2. 전체 키트(Kit) 수행 결과</h2>
            <div class="table-container">
                {df_kits.to_html(index=False, classes="data-table").replace("<td>LATE</td>", '<td class="late">LATE</td>').replace("<td>OK</td>", '<td class="ok">OK</td>')}
            </div>

            <h2>⏱️ 3. 키트별 스텝 바이 스텝 진행 타임라인</h2>
            <div class="table-container">
                {df_timeline.to_html(index=False, classes="data-table")}
            </div>
        </body>
        </html>
        """

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        print(
            f"✅ HTML 리포트 생성 완료: {filename} (더블 클릭하여 브라우저에서 확인 가능)"
        )
