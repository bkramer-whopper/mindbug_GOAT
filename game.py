from __future__ import annotations
import random

from card import Card
from player import Player
from constants import FRENZY, HUNTER, SNEAKY, TOUGH, POISONOUS
from deck import build_deck
from ui import _int, _yes, _sep, _hdr
from mcts import mcts_choose, mcts_choose_mindbug, mcts_choose_blocker


class Game:
    def __init__(self, p1: Player, p2: Player):
        self.players    = [p1, p2]
        self.active_idx = 0
        self.turn       = 1
        self.extra_turn = False

        deck = build_deck()
        for p in self.players:
            p.draw_pile = deck[:10]
            deck        = deck[10:]
            p.draw_to(5)

        # Snapshot of every card in play — used by _determinize to build
        # the unknown pool from public info rather than peeking at opp zones.
        self.all_dealt_cards: list[Card] = [
            c for p in self.players for c in p.hand + p.draw_pile
        ]

    def opp(self, player: Player) -> Player:
        return self.players[1] if player is self.players[0] else self.players[0]

    @property
    def active(self) -> Player:
        return self.players[self.active_idx]

    def _has_deathweaver(self, player: Player) -> bool:
        return any(c.name == "Deathweaver" for c in player.in_play)

    def _defeat(self, card: Card, ctrl: Player) -> bool:
        if TOUGH in card.keywords and not card.tough_used:
            print(f"  ★  {card.name}'s Tough shield absorbs the hit!")
            card.tough_used = True
            return False
        if card not in ctrl.in_play:
            return False
        ctrl.in_play.remove(card)
        ctrl.discard.append(card)
        print(f"  ✗  {card.name} is defeated.")
        if card.on_defeated:
            card.on_defeated(self, ctrl, card)
        return True

    def _check_win(self) -> Player | None:
        for p in self.players:
            if not p.alive():
                return self.opp(p)
        return None

    # ── Display ───────────────────────────────────────────────────────────────

    def display_state(self):
        W, cur = 66, self.active
        tag = "  [EXTRA TURN]" if self.extra_turn else ""
        print(f"\n{'═'*W}\n  Turn {self.turn}{tag}\n{'═'*W}")
        for p in reversed(self.players):
            marker = "→ " if p is cur else "  "
            bot_tag = " [BOT]" if p.is_bot else ""
            print(f"{marker}{p.name}{bot_tag}")
            print(f"    ♥ {p.life}  Mindbugs: {p.mindbugs}  "
                  f"Hand: {len(p.hand)}  Draw: {len(p.draw_pile)}")
            if p.in_play:
                for c in p.in_play:
                    print(f"    · {c.brief(self, p)}")
            else:
                print(f"    · (nothing in play)")
        print(f"{'─'*W}")

    def _show_hand(self, player: Player):
        print(f"\n  {player.name}'s hand:")
        if not player.hand:
            print("    (empty)")
        else:
            for i, c in enumerate(player.hand, 1):
                print(f"    {c.full(i, self, player)}")

    # ── Combat ────────────────────────────────────────────────────────────────

    def _resolve_combat(self, atk: Card, atk_ctrl: Player,
                              blk: Card, blk_ctrl: Player) -> bool:
        atk_p   = atk.effective_power(self, atk_ctrl)
        blk_p   = blk.effective_power(self, blk_ctrl)
        atk_kws = atk.effective_keywords(self, atk_ctrl)
        blk_kws = blk.effective_keywords(self, blk_ctrl)

        print(f"\n  ⚔  {atk_ctrl.name}'s {atk.brief(self, atk_ctrl)}")
        print(f"     vs  {blk_ctrl.name}'s {blk.brief(self, blk_ctrl)}")

        blk_loses = (atk_p > blk_p) or (POISONOUS in atk_kws) or (atk_p == blk_p)
        atk_loses = (blk_p > atk_p) or (POISONOUS in blk_kws) or (atk_p == blk_p)

        if blk_loses:
            self._defeat(blk, blk_ctrl)
        if atk_loses:
            self._defeat(atk, atk_ctrl)

        return atk in atk_ctrl.in_play

    # ── Attack sequence ───────────────────────────────────────────────────────

    def _do_attack(self, attacker: Card, ctrl: Player, already_frenzied: bool = False):
        opp     = self.opp(ctrl)
        atk_kws = attacker.effective_keywords(self, ctrl)

        if attacker.on_attack:
            attacker.on_attack(self, ctrl, attacker)
        if self._check_win():
            return

        is_sneaky   = SNEAKY in atk_kws
        is_hunter   = HUNTER in atk_kws
        is_bee_bear = attacker.name == "Bee Bear"

        if is_sneaky:
            eligible = [c for c in opp.in_play if c.can_block_sneaky(self, opp)]
        elif is_bee_bear:
            eligible = [c for c in opp.in_play if c.effective_power(self, opp) > 6]
        else:
            eligible = list(opp.in_play)

        if any(c.name == "Elephantopus" for c in ctrl.in_play):
            eligible = [c for c in eligible if c.effective_power(self, opp) > 4]

        notes = []
        if is_sneaky:    notes.append("Sneaky – only Sneaky can block")
        if is_bee_bear:  notes.append("Bee Bear – only power 7+ can block")
        if any(c.name == "Elephantopus" for c in ctrl.in_play):
            notes.append("Elephantopus – power ≤4 can't block")
        if notes:
            print(f"\n  Note: {'; '.join(notes)}.")

        blocker = None

        if is_hunter and opp.in_play:
            if _yes(f"\n  {attacker.name} has Hunter. {ctrl.name}, force an enemy to block?",
                    decider=ctrl):
                force_pool = list(opp.in_play)
                print(f"\n  Choose which enemy creature must block:")
                for i, c in enumerate(force_pool, 1):
                    print(f"    {c.full(i, self, opp)}")
                idx     = _int(f"  Choose (1-{len(force_pool)}): ",
                               1, len(force_pool), decider=ctrl) - 1
                blocker = force_pool[idx]
                print(f"  {blocker.name} is forced to block!")

        if blocker is None:
            if eligible:
                if opp.bot_type == "mcts":
                    blocker = mcts_choose_blocker(self, opp, ctrl, attacker, eligible)
                    if blocker:
                        print(f"  {blocker.name} blocks.")
                elif _yes(f"\n  {opp.name}, block the attack?", decider=opp):
                    if len(eligible) == 1:
                        blocker = eligible[0]
                        print(f"  {blocker.name} blocks.")
                    else:
                        print(f"\n  {opp.name}'s eligible blockers:")
                        for i, c in enumerate(eligible, 1):
                            print(f"    {c.full(i, self, opp)}")
                        idx     = _int(f"  Choose blocker (1-{len(eligible)}): ",
                                       1, len(eligible), decider=opp) - 1
                        blocker = eligible[idx]
            elif opp.in_play:
                print(f"  {opp.name} has no eligible blockers.")

        if blocker:
            self._resolve_combat(attacker, ctrl, blocker, opp)
        else:
            opp.life = max(0, opp.life - 1)
            print(f"\n  ★  {attacker.name} hits {opp.name}! ({opp.name}: {opp.life} life)")

        if self._check_win():
            return

        if not already_frenzied and attacker in ctrl.in_play:
            if FRENZY in attacker.effective_keywords(self, ctrl):
                if _yes(f"\n  {attacker.name} has Frenzy! Attack again?", decider=ctrl):
                    self._do_attack(attacker, ctrl, already_frenzied=True)

    # ── Turn phases ───────────────────────────────────────────────────────────

    def _phase_play(self, ctrl: Player):
        if ctrl.is_bot:
            self._show_hand(ctrl)
        if not ctrl.hand:
            print(f"  {ctrl.name} has no cards to play.")
            return

        idx  = _int(f"\n  {ctrl.name} – choose a card to play (1-{len(ctrl.hand)}): ",
                    1, len(ctrl.hand), decider=ctrl) - 1
        card = ctrl.hand.pop(idx)
        ctrl.draw_to(5)

        print(f"\n  {ctrl.name} plays {card.brief(self, ctrl)}.")
        opp  = self.opp(ctrl)
        dest = ctrl

        if opp.mindbugs > 0:
            print(f"  {opp.name} has {opp.mindbugs} Mindbug(s).")
            print(f"  Card: {card.full(game=self, ctrl=ctrl)}")
            if not opp.is_bot:
                self._show_hand(opp)
            if opp.bot_type == "mcts":
                use_mb = mcts_choose_mindbug(self, opp, card, ctrl)
            else:
                use_mb = _yes(f"  {opp.name}, use a Mindbug to steal {card.name}?", decider=opp)
            if use_mb:
                opp.mindbugs -= 1
                dest          = opp
                self.extra_turn = True
                print(f"  ★  MINDBUG! {card.name} goes to {opp.name}.")

        dest.in_play.append(card)

        if card.on_played:
            opp_of_dest = self.opp(dest)
            if self._has_deathweaver(opp_of_dest):
                print(f"  ★  {opp_of_dest.name}'s Deathweaver suppresses the Play effect!")
            else:
                card.on_played(self, dest, card)

    def _phase_attack(self, ctrl: Player):
        if not ctrl.in_play:
            print(f"  {ctrl.name} has no creatures in play.")
            return
        print(f"\n  {ctrl.name}'s creatures:")
        for i, c in enumerate(ctrl.in_play, 1):
            print(f"    {c.full(i, self, ctrl)}")
        idx      = _int(f"  Choose attacker (1-{len(ctrl.in_play)}): ",
                        1, len(ctrl.in_play), decider=ctrl) - 1
        attacker = ctrl.in_play[idx]
        self._do_attack(attacker, ctrl)

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self) -> Player:
        _hdr(f"MINDBUG  ·  {self.players[0].name}  vs  {self.players[1].name}")
        print("  Official First Contact base set  |  3 life  |  2 Mindbugs each")
        print("  Each turn: play a card OR attack with a creature.")
        _sep()

        while True:
            ctrl = self.active
            self.display_state()
            _hdr(f"Turn {self.turn} – {ctrl.name}{'  [BOT]' if ctrl.is_bot else ''}")

            if not ctrl.has_action():
                print(f"  {ctrl.name} cannot take any action and loses!")
                winner = self.opp(ctrl)
                break

            can_play   = bool(ctrl.hand)
            can_attack = bool(ctrl.in_play)

            if ctrl.bot_type == "mcts":
                action, forced = mcts_choose(self, ctrl)
                ctrl.choice_queue = [forced]
            elif ctrl.is_bot:   # random
                if can_play and can_attack:
                    action = random.choice(["play", "attack"])
                    print(f"  [Bot] action → {action}")
                elif can_play:
                    action = "play"
                else:
                    action = "attack"
            else:               # human
                self._show_hand(ctrl)
                if can_play and can_attack:
                    while True:
                        choice = input(f"\n  Action – [p]lay a card or [a]ttack? ").strip().lower()
                        if choice in ("p", "play"):   action = "play";   break
                        if choice in ("a", "attack"): action = "attack"; break
                        print("  Enter p or a.")
                elif can_play:
                    print(f"\n  {ctrl.name} has no creatures – must play a card.")
                    action = "play"
                else:
                    print(f"\n  {ctrl.name} has no cards – must attack.")
                    action = "attack"

            if action == "play":
                self._phase_play(ctrl)
            else:
                self._phase_attack(ctrl)

            winner = self._check_win()
            if winner:
                break

            if self.extra_turn:
                self.extra_turn = False
                self.turn += 1
            else:
                self.active_idx = 1 - self.active_idx
                self.turn += 1

        _hdr("GAME OVER")
        print(f"  {winner.name} wins!")
        for p in self.players:
            label = " [BOT]" if p.is_bot else ""
            print(f"  {p.name}{label}: {p.life} life remaining")
        _sep()
        return winner
