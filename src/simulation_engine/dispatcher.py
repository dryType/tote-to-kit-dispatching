import simpy

from policy.base_policy import BasePolicy
from simulation_engine.candidate_generator import generate_candidates
from simulation_engine.metrics import Metrics
from simulation_engine.processes import agv_transport_process
from simulation_engine.state import WorldStateSnapshot


class Dispatcher:
    def __init__(
        self,
        env: simpy.Environment,
        world_state: WorldStateSnapshot,
        policy: BasePolicy,
        metrics: Metrics | None,
    ):
        self.env = env
        self.world_state = world_state
        self.policy = policy
        self.metrics = metrics
        self.dispatch_event = env.event()

    def notify(self) -> None:
        if not self.dispatch_event.triggered:
            self.dispatch_event.succeed()

    def run(self):
        while True:
            yield self.dispatch_event
            self.dispatch_event = self.env.event()

            self._dispatch_batch()

    def _dispatch_batch(self) -> None:
        while self._dispatch_once():
            pass

    def _dispatch_once(self) -> bool:
        idle_agvs = self.world_state.get_idle_agvs()
        if not idle_agvs:
            return False

        tote_to_kit_candidates = generate_candidates(
            list(self.world_state.stations.values()),
            list(self.world_state.totes.values()),
        )
        if not tote_to_kit_candidates:
            return False

        selected_dispatching, selected_agv = self.policy.select(
            self.env.now,
            tote_to_kit_candidates,
            idle_agvs,
            self.world_state,
            self.metrics.dispatched_count,
        )
        if not selected_dispatching or not selected_agv:
            return False

        selected_dispatching.execute_dispatch(selected_agv, self.env.now)
        agv_move_distance = selected_agv.position.manhattan_distance_to(
            selected_dispatching.tote.position
        ) + 2 * (
            selected_dispatching.tote.position.manhattan_distance_to(
                selected_dispatching.station.position
            )
        )

        if self.metrics is not None:
            self.metrics.record_dispatch(
                self.env.now,
                agv_id=selected_agv.agv_id,
                tote_id=selected_dispatching.tote.tote_id,
                station_id=selected_dispatching.station.station_id,
                kit_id=selected_dispatching.kit.kit_id,
                matched_parts=dict(selected_dispatching.matched_parts),
                score_info=selected_dispatching.score_info,
                agv_move_distance=agv_move_distance,
            )

        self.env.process(
            agv_transport_process(
                self.env,
                selected_agv,
                selected_dispatching,
                self,
                self.metrics,
            )
        )

        return True
