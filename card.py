from __future__ import annotations
from typing import TYPE_CHECKING

from constants import FRENZY, HUNTER, POISONOUS, SNEAKY, TOUGH, _KW_ORDER

if TYPE_CHECKING:
    from game import Game
    from player import Player


class Card:
    _uid = 0

    def __init__(self, name: str, power: int, text: str = "", keywords=None):
        Card._uid += 1
        self.uid        = Card._uid
        self.name       = name
        self.power      = power
        self.text       = text
        self.keywords: set[str] = set(keywords or [])
        self.tough_used = False

        self.on_played:   ... = None  # fn(game, ctrl, card)
        self.on_attack:   ... = None  # fn(game, ctrl, card)
        self.on_defeated: ... = None  # fn(game, ctrl, card)

    def clone(self) -> Card:
        c = Card(self.name, self.power, self.text, set(self.keywords))
        c.on_played   = self.on_played
        c.on_attack   = self.on_attack
        c.on_defeated = self.on_defeated
        return c

    def has(self, kw: str) -> bool:
        return kw in self.keywords

    # ── Context-aware power / keywords ────────────────────────────────────────

    def effective_power(self, game: Game, ctrl: Player) -> int:
        p = self.power
        if self.name == "Lone Yeti" and len(ctrl.in_play) == 1:
            p += 5
        if self.name == "Goblin Werewolf" and game.active is ctrl:
            p += 6
        if self.name != "Shield Bugs":
            p += sum(1 for c in ctrl.in_play if c.name == "Shield Bugs" and c is not self)
        if self.name != "Urchin Hurler" and game.active is ctrl:
            if any(c.name == "Urchin Hurler" for c in ctrl.in_play if c is not self):
                p += 2
        return max(1, p)

    def effective_keywords(self, game: Game, ctrl: Player) -> set[str]:
        kws = set(self.keywords)
        if self.name == "Lone Yeti" and len(ctrl.in_play) == 1:
            kws.add(FRENZY)
        if self.name == "Sharky Crab-Dog-Mummypus":
            for enemy in game.opp(ctrl).in_play:
                for kw in (HUNTER, SNEAKY, FRENZY, POISONOUS):
                    if enemy.has(kw):
                        kws.add(kw)
        if self.name != "Snail Thrower" and self.power <= 4:
            if any(c.name == "Snail Thrower" for c in ctrl.in_play if c is not self):
                kws.add(HUNTER)
                kws.add(POISONOUS)
        return kws

    def can_block_sneaky(self, game: Game, ctrl: Player) -> bool:
        return SNEAKY in self.effective_keywords(game, ctrl)

    # ── Display ───────────────────────────────────────────────────────────────

    def _kw_str(self, kws: set[str]) -> str:
        active = [k for k in _KW_ORDER if k in kws]
        return f" ({', '.join(active)})" if active else ""

    def brief(self, game: Game | None = None, ctrl: Player | None = None) -> str:
        if game and ctrl:
            p, kws = self.effective_power(game, ctrl), self.effective_keywords(game, ctrl)
        else:
            p, kws = self.power, self.keywords
        ex = " [tough-exhausted]" if self.tough_used else ""
        return f"{self.name} [P:{p}]{self._kw_str(kws)}{ex}"

    def full(self, idx: int | None = None,
             game: Game | None = None, ctrl: Player | None = None) -> str:
        if game and ctrl:
            p, kws = self.effective_power(game, ctrl), self.effective_keywords(game, ctrl)
        else:
            p, kws = self.power, self.keywords
        prefix = f"{idx}. " if idx is not None else ""
        top = f"{prefix}{self.name} [Power {p}]{self._kw_str(kws)}"
        return (top + f"\n   {self.text}") if self.text else top
