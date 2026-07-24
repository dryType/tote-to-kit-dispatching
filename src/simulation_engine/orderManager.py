from typing import List, Optional

from simulation_engine.entities import Kit


class OrderManager:
    def __init__(self, pending_kits: List[Kit]):
        self.pending_kits: List[Kit] = pending_kits

    def pop_next_kit(self) -> Optional[Kit]:
        if not self.pending_kits:
            return None

        next_kit = min(self.pending_kits, key=lambda kit: kit.start_time_sec)
        self.pending_kits.remove(next_kit)
        return next_kit
