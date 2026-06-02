from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from card import Card


class Player:
    def __init__(self, name: str, bot_type: str = "human"):
        # bot_type: "human" | "random" | "mcts"
        self.name       = name
        self.bot_type   = bot_type
        self.life       = 3
        self.mindbugs   = 2
        self.draw_pile: list[Card] = []
        self.hand:      list[Card] = []
        self.in_play:   list[Card] = []
        self.discard:   list[Card] = []
        self.choice_queue: list = []   # pre-loaded answers (consumed before random)
        self._sim_main: str | None = None  # forced main action for MCTS simulation

    @property
    def is_bot(self) -> bool:
        return self.bot_type != "human"

    def alive(self) -> bool:
        return self.life > 0

    def has_action(self) -> bool:
        return bool(self.hand) or bool(self.in_play)

    def draw_to(self, n: int = 5):
        while len(self.hand) < n and self.draw_pile:
            self.hand.append(self.draw_pile.pop())
