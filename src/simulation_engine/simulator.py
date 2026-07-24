# simulation_engine/simulator.py
import simpy

from simulation_engine.candidate_generator import find_feasible_candidates
from simulation_engine.processes import agv_transport_process
from simulation_engine.state import WorldStateSnapshot


class WarehouseSimulator:
    def __init__(self, scenario_name: str, policy):
        self.env = simpy.Environment()
        self.policy = policy
        self.scenario_name = scenario_name
