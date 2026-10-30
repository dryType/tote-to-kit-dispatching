from simulation_engine.entities import Kit


class OrderManager:
    def __init__(self, pending_kits: list[Kit], release_rule=None):
        self.pending_kits: list[Kit] = pending_kits
        self.activated_kits: list[Kit] = []
        # 다음에 스테이션에 걸 키트를 고르는 규칙: (대기 키트, 활성 키트, 현재 시각) -> Kit. None이면 납기 순
        self.release_rule = release_rule

    def pop_next_kit(self, now: float = 0.0) -> Kit | None:
        if not self.pending_kits:
            return None

        if self.release_rule is None:
            next_kit = min(self.pending_kits, key=lambda kit: kit.deadline_time_sec)
        else:
            next_kit = self.release_rule(self.pending_kits, self.activated_kits, now)
        self.pending_kits.remove(next_kit)
        self.activated_kits.append(next_kit)
        return next_kit

    def is_all_completed(self) -> bool:
        return len(self.pending_kits) == 0 and all(
            kit.is_completed() for kit in self.activated_kits
        )

    def get_all_kits(self) -> list[Kit]:
        return self.pending_kits + self.activated_kits
