from __future__ import annotations
import random
from typing import TYPE_CHECKING

from ui import _int, _yes

if TYPE_CHECKING:
    from game import Game
    from player import Player
    from card import Card


def _gain_life(game: Game, ctrl: Player, n: int):
    ctrl.life += n
    print(f"  ★  {ctrl.name} gains {n} life → {ctrl.life}")

def _lose_life(game: Game, ctrl: Player, n: int):
    ctrl.life = max(0, ctrl.life - n)
    print(f"  ★  {ctrl.name} loses {n} life → {ctrl.life}")

def _damage_opp(game: Game, ctrl: Player, n: int):
    opp = game.opp(ctrl)
    opp.life = max(0, opp.life - n)
    print(f"  ★  Deals {n} damage to {opp.name} → {opp.name}: {opp.life} life")

def _opp_discards(game: Game, ctrl: Player, n: int):
    opp = game.opp(ctrl)
    discarded = 0
    while discarded < n and opp.hand:
        print(f"\n  {opp.name} must discard a card.")
        for i, c in enumerate(opp.hand, 1):
            print(f"    {c.full(i, game, opp)}")
        idx = _int(f"  {opp.name} – choose (1-{len(opp.hand)}): ",
                   1, len(opp.hand), decider=opp)
        disc = opp.hand.pop(idx - 1)
        opp.discard.append(disc)
        opp.draw_to(5)
        print(f"  ★  {opp.name} discards {disc.brief(game, opp)}.")
        discarded += 1
    if discarded < n:
        print(f"  ★  {opp.name} has no more cards to discard.")

def _steal_random_from_opp_hand(game: Game, ctrl: Player, n: int):
    opp = game.opp(ctrl)
    for _ in range(n):
        if not opp.hand:
            print(f"  ★  {opp.name} has no more cards to steal.")
            break
        card = opp.hand.pop(random.randrange(len(opp.hand)))
        ctrl.hand.append(card)
        opp.draw_to(5)
        print(f"  ★  {ctrl.name} steals {card.name} from {opp.name}!")

def _own_discard_to_hand(game: Game, ctrl: Player):
    if not ctrl.discard:
        print(f"  ★  {ctrl.name}'s discard pile is empty.")
        return
    ctrl.hand.extend(ctrl.discard)
    ctrl.discard.clear()
    print(f"  ★  {ctrl.name} draws their entire discard pile into hand!")

def _enter_play(game: Game, ctrl: Player, card: Card):
    ctrl.in_play.append(card)
    if card.on_played:
        if game._has_deathweaver(game.opp(ctrl)):
            print(f"  ★  {game.opp(ctrl).name}'s Deathweaver suppresses the Play effect!")
        else:
            card.on_played(game, ctrl, card)

def _compost_dragon_play(game: Game, ctrl: Player, card: Card):
    if not ctrl.discard:
        print(f"  ★  {ctrl.name}'s discard pile is empty.")
        return
    print(f"\n  {ctrl.name} plays a card from their discard pile.")
    for i, c in enumerate(ctrl.discard, 1):
        print(f"    {c.full(i, game, ctrl)}")
    idx = _int(f"  Choose (1-{len(ctrl.discard)}): ",
               1, len(ctrl.discard), decider=ctrl) - 1
    chosen = ctrl.discard.pop(idx)
    print(f"  ★  {chosen.name} enters play!")
    _enter_play(game, ctrl, chosen)

def _grave_robber_play(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    if not opp.discard:
        print(f"  ★  {opp.name}'s discard pile is empty.")
        return
    print(f"\n  {ctrl.name} plays a card from {opp.name}'s discard pile.")
    for i, c in enumerate(opp.discard, 1):
        print(f"    {c.full(i, game, opp)}")
    idx = _int(f"  Choose (1-{len(opp.discard)}): ",
               1, len(opp.discard), decider=ctrl) - 1
    chosen = opp.discard.pop(idx)
    print(f"  ★  {chosen.name} enters play under {ctrl.name}'s control!")
    _enter_play(game, ctrl, chosen)

def _mermaid_play(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    ctrl.life = opp.life
    print(f"  ★  {ctrl.name}'s life is set to {opp.life} (equal to {opp.name}'s)!")

def _brain_fly_play(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    eligible = [c for c in opp.in_play if c.effective_power(game, opp) >= 6]
    if not eligible:
        print(f"  ★  Brain Fly: no enemy creatures with power 6 or more.")
        return
    print(f"\n  {ctrl.name} takes control of an enemy creature (power 6+).")
    for i, c in enumerate(eligible, 1):
        print(f"    {c.full(i, game, opp)}")
    idx = _int(f"  Choose (1-{len(eligible)}): ",
               1, len(eligible), decider=ctrl) - 1
    target = eligible[idx]
    opp.in_play.remove(target)
    ctrl.in_play.append(target)
    print(f"  ★  {ctrl.name} takes control of {target.name}!")

def _kangasaurus_play(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    targets = [c for c in list(opp.in_play) if c.effective_power(game, opp) <= 4]
    if not targets:
        print(f"  ★  Kangasaurus Rex: no enemy creatures with power 4 or less.")
        return
    print(f"  ★  Kangasaurus Rex defeats all enemy creatures with power 4 or less!")
    for c in targets:
        if c in opp.in_play:
            game._defeat(c, opp)

def _tiger_squirrel_play(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    eligible = [c for c in opp.in_play if c.effective_power(game, opp) >= 7]
    if not eligible:
        print(f"  ★  Tiger Squirrel: no enemy creatures with power 7 or more.")
        return
    print(f"\n  ★  Tiger Squirrel: defeat an enemy creature with power 7+!")
    for i, c in enumerate(eligible, 1):
        print(f"    {c.full(i, game, opp)}")
    idx = _int(f"  Choose (1-{len(eligible)}): ",
               1, len(eligible), decider=ctrl) - 1
    game._defeat(eligible[idx], opp)

def _shark_dog_attack(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    eligible = [c for c in opp.in_play if c.effective_power(game, opp) >= 6]
    if not eligible:
        print(f"  ★  Shark Dog: no enemy creatures with power 6 or more.")
        return
    print(f"\n  ★  Shark Dog: defeat an enemy creature with power 6+!")
    for i, c in enumerate(eligible, 1):
        print(f"    {c.full(i, game, opp)}")
    idx = _int(f"  Choose (1-{len(eligible)}): ",
               1, len(eligible), decider=ctrl) - 1
    game._defeat(eligible[idx], opp)

def _harpy_defeated(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    print(f"  ★  Harpy Mother's Defeated effect!")
    for _ in range(2):
        eligible = [c for c in opp.in_play if c.effective_power(game, opp) <= 5]
        if not eligible:
            print(f"  ★  No enemy creatures with power 5 or less remaining.")
            break
        print(f"\n  {ctrl.name} takes control of an enemy creature (power ≤ 5).")
        for i, c in enumerate(eligible, 1):
            print(f"    {c.full(i, game, opp)}")
        idx = _int(f"  Choose (1-{len(eligible)}): ",
                   1, len(eligible), decider=ctrl) - 1
        target = eligible[idx]
        opp.in_play.remove(target)
        ctrl.in_play.append(target)
        print(f"  ★  {ctrl.name} takes control of {target.name}!")
        remaining = [c for c in opp.in_play if c.effective_power(game, opp) <= 5]
        if not remaining:
            break
        if not _yes(f"  Take control of a second creature?", decider=ctrl):
            break

def _explosive_toad_defeated(game: Game, ctrl: Player, card: Card):
    all_c = [(c, ctrl) for c in ctrl.in_play] + \
            [(c, game.opp(ctrl)) for c in game.opp(ctrl).in_play]
    if not all_c:
        print(f"  ★  Explosive Toad: no creatures to defeat.")
        return
    print(f"  ★  BOOM! Explosive Toad destroys a creature!")
    for i, (c, owner) in enumerate(all_c, 1):
        print(f"    {i}. {c.brief(game, owner)} ({owner.name})")
    idx = _int(f"  Choose creature to defeat (1-{len(all_c)}): ",
               1, len(all_c), decider=ctrl) - 1
    target, target_ctrl = all_c[idx]
    game._defeat(target, target_ctrl)

def _strange_barrel_defeated(game: Game, ctrl: Player, card: Card):
    _steal_random_from_opp_hand(game, ctrl, 2)

def _turbo_bug_attack(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    if opp.life > 1:
        lost = opp.life - 1
        opp.life = 1
        print(f"  ★  TURBO! {opp.name} loses {lost} life → 1")
    else:
        print(f"  ★  TURBO! {opp.name} is already at {opp.life} life.")

def _snail_hydra_attack(game: Game, ctrl: Player, card: Card):
    opp = game.opp(ctrl)
    if len(ctrl.in_play) >= len(opp.in_play):
        return
    all_c = [(c, ctrl) for c in ctrl.in_play] + [(c, opp) for c in opp.in_play]
    if not all_c:
        return
    print(f"  ★  Snail Hydra: fewer creatures than opponent – defeat a creature!")
    for i, (c, owner) in enumerate(all_c, 1):
        print(f"    {i}. {c.brief(game, owner)} ({owner.name})")
    idx = _int(f"  Choose (1-{len(all_c)}): ",
               1, len(all_c), decider=ctrl) - 1
    target, target_ctrl = all_c[idx]
    game._defeat(target, target_ctrl)
