from __future__ import annotations
import copy, io, contextlib, random
from typing import TYPE_CHECKING

from constants import FRENZY

if TYPE_CHECKING:
    from game import Game
    from player import Player
    from card import Card

MCTS_SIMS = 100   # Monte Carlo simulations per candidate action


def _determinize(g: Game, perspective_idx: int):
    """
    Randomize the opponent's hidden cards without using knowledge the perspective
    player shouldn't have. Builds the unknown pool from all_dealt_cards minus every
    card visible to the perspective player (their own zones + opp's public zones),
    so each simulation samples a plausible world rather than the true hand contents.
    """
    ctrl = g.players[perspective_idx]
    opp  = g.players[1 - perspective_idx]

    # Everything ctrl can legitimately see
    known_uids = set(
        c.uid for c in
        ctrl.hand + ctrl.in_play + ctrl.discard + ctrl.draw_pile +
        opp.in_play + opp.discard
    )

    # Possible opponent cards = all dealt cards not accounted for in visible zones
    pool = [c for c in g.all_dealt_cards if c.uid not in known_uids]
    random.shuffle(pool)

    n_hand        = len(opp.hand)
    opp.hand      = pool[:n_hand]
    opp.draw_pile = pool[n_hand:]


def _run_to_end(game: Game, max_turns: int = 150) -> Player | None:
    """
    Run a game copy to completion with all-random play, silently.
    Returns the winning Player object (from the copy), or None if turn limit hit.
    """
    for p in game.players:
        p.bot_type = "random"

    with contextlib.redirect_stdout(io.StringIO()):
        for _ in range(max_turns):
            ctrl = game.active
            if not ctrl.has_action():
                return game.opp(ctrl)

            can_play   = bool(ctrl.hand)
            can_attack = bool(ctrl.in_play)

            if ctrl._sim_main:
                action         = ctrl._sim_main
                ctrl._sim_main = None
            elif can_play and can_attack:
                action = random.choice(["play", "attack"])
            elif can_play:
                action = "play"
            else:
                action = "attack"

            if action == "play" and can_play:
                game._phase_play(ctrl)
            elif can_attack:
                game._phase_attack(ctrl)

            winner = game._check_win()
            if winner:
                return winner

            if game.extra_turn:
                game.extra_turn = False
                game.turn += 1
            else:
                game.active_idx = 1 - game.active_idx
                game.turn += 1

    return None   # turn limit reached — treat as draw


def mcts_choose_mindbug(game: Game, opp: Player, card: Card, ctrl: Player) -> bool:
    """
    MCTS: should opp use a Mindbug on card?
    Simulates both paths from opp's perspective. Returns True to use Mindbug.
    Game state is mid-turn: card has been played from ctrl's hand, draw-back done.
    """
    opp_idx  = game.players.index(opp)
    ctrl_idx = game.players.index(ctrl)

    print(f"  [MCTS] Mindbug {card.name}? evaluating 2 paths × {MCTS_SIMS} sims…")

    wins: dict[bool, int] = {True: 0, False: 0}

    for use_mb in (True, False):
        for _ in range(MCTS_SIMS):
            g      = copy.deepcopy(game)
            g_opp  = g.players[opp_idx]
            g_ctrl = g.players[ctrl_idx]
            card_c = copy.deepcopy(card)

            _determinize(g, opp_idx)
            for p in g.players:
                p.bot_type = "random"

            with contextlib.redirect_stdout(io.StringIO()):
                if use_mb:
                    g_opp.mindbugs -= 1
                    g_opp.in_play.append(card_c)
                    if card_c.on_played and not g._has_deathweaver(g_ctrl):
                        card_c.on_played(g, g_opp, card_c)
                    g.extra_turn = False
                else:
                    g_ctrl.in_play.append(card_c)
                    if card_c.on_played and not g._has_deathweaver(g_opp):
                        card_c.on_played(g, g_ctrl, card_c)
                    g.active_idx = opp_idx
                    g.extra_turn = False

            winner = _run_to_end(g)
            if winner is not None and g.players.index(winner) == opp_idx:
                wins[use_mb] += 1

    for use_mb, label in [(True, "use"), (False, "skip")]:
        print(f"    {label}: {wins[use_mb] / MCTS_SIMS:.0%}")

    use_it = wins[True] >= wins[False]
    print(f"  [MCTS] → {'USE Mindbug' if use_it else 'skip'}")
    return use_it


def mcts_choose_blocker(
    game: Game, opp: Player, ctrl: Player,
    attacker: Card, eligible: list[Card],
) -> Card | None:
    """
    MCTS: should opp block, and with which creature?
    Returns the chosen blocker or None. Candidates: don't block + each eligible creature.
    """
    opp_idx  = game.players.index(opp)
    ctrl_idx = game.players.index(ctrl)
    atk_uid  = attacker.uid

    candidates: list[tuple[Card | None, str]] = [(None, "don't block")]
    for c in eligible:
        candidates.append((c, f"block {c.name}"))

    print(f"  [MCTS] block? {len(candidates)} options × {MCTS_SIMS} sims…")

    best_blocker: Card | None = None
    best_wr = -1.0

    for blocker_card, label in candidates:
        blk_uid = blocker_card.uid if blocker_card else None
        wins = 0

        for _ in range(MCTS_SIMS):
            g      = copy.deepcopy(game)
            g_opp  = g.players[opp_idx]
            g_ctrl = g.players[ctrl_idx]

            _determinize(g, opp_idx)
            for p in g.players:
                p.bot_type = "random"

            atk_c = next((c for c in g_ctrl.in_play if c.uid == atk_uid), None)

            with contextlib.redirect_stdout(io.StringIO()):
                if blocker_card is None or atk_c is None:
                    g_opp.life = max(0, g_opp.life - 1)
                else:
                    blk_c = next((c for c in g_opp.in_play if c.uid == blk_uid), None)
                    if blk_c:
                        g._resolve_combat(atk_c, g_ctrl, blk_c, g_opp)

                if (atk_c is not None
                        and atk_c in g_ctrl.in_play
                        and FRENZY in atk_c.effective_keywords(g, g_ctrl)
                        and not g._check_win()):
                    g._do_attack(atk_c, g_ctrl, already_frenzied=True)

                g.extra_turn = False
                g.active_idx = opp_idx

            winner = _run_to_end(g)
            if winner is not None and g.players.index(winner) == opp_idx:
                wins += 1

        wr = wins / MCTS_SIMS
        print(f"    {label}: {wr:.0%}")
        if wr > best_wr:
            best_wr      = wr
            best_blocker = blocker_card

    chosen_label = "no block" if best_blocker is None else f"block with {best_blocker.name}"
    print(f"  [MCTS] → {chosen_label}")
    return best_blocker


def mcts_choose(game: Game, ctrl: Player) -> tuple[str, int]:
    """
    Evaluate every legal action for ctrl via Monte Carlo rollouts.
    Returns (action_type, choice_idx_1based) for the best action found.
    """
    ctrl_idx = game.players.index(ctrl)

    candidates: list[tuple[str, int, str]] = []
    for i, c in enumerate(ctrl.hand):
        candidates.append(("play",   i + 1, f"play {c.name}"))
    for i, c in enumerate(ctrl.in_play):
        candidates.append(("attack", i + 1, f"attack with {c.name}"))

    if len(candidates) == 1:
        print(f"  [MCTS] only one action available → {candidates[0][2]}")
        return candidates[0][0], candidates[0][1]

    print(f"  [MCTS] evaluating {len(candidates)} actions × {MCTS_SIMS} simulations…")

    opp_idx = 1 - ctrl_idx
    opp     = game.players[opp_idx]

    best_i, best_wr = 0, -1.0
    for i, (action_type, choice_idx, label) in enumerate(candidates):
        wins = 0

        mb_prob = 0.0
        if action_type == "play" and opp.mindbugs > 0 and ctrl.hand:
            mb_prob = min(1.0, opp.mindbugs / len(ctrl.hand))

        for _ in range(MCTS_SIMS):
            g     = copy.deepcopy(game)
            _determinize(g, ctrl_idx)
            bot   = g.players[ctrl_idx]
            g_opp = g.players[opp_idx]
            bot._sim_main    = action_type
            bot.choice_queue = [choice_idx]

            if action_type == "play" and g_opp.mindbugs > 0:
                g_opp.choice_queue = [random.random() < mb_prob]

            winner = _run_to_end(g)
            if winner is not None and g.players.index(winner) == ctrl_idx:
                wins += 1

        wr = wins / MCTS_SIMS
        print(f"    {label:<40} {wr:5.0%}  ({wins}/{MCTS_SIMS})")
        if wr > best_wr:
            best_wr, best_i = wr, i

    chosen = candidates[best_i]
    print(f"  [MCTS] → {chosen[2]}  (best at {best_wr:.0%})")
    return chosen[0], chosen[1]
