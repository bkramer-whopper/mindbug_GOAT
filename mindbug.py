#!/usr/bin/env python3
"""Mindbug – two-player CLI simulator using the official First Contact base set.

Official rules (Mindbug: First Contact):
  - 3 life each, 2 Mindbugs each.
  - 48 creature cards shuffled; each player takes 10 as their personal draw pile.
  - Each player draws 5 opening cards.
  - Each turn: take ONE action — play a card OR attack with a creature.
    If you cannot, you lose.
  - Playing from hand: immediately draw back to 5, THEN opponent may Mindbug it.
    If Mindbugged: card goes to opponent (they trigger Play effect); your turn ends
    and you immediately get an extra turn.
  - FRENZY   – may attack twice this turn if still in play after first attack.
  - HUNTER   – when attacking, may force any enemy creature to block (overrides Sneaky).
  - POISONOUS – always defeats the enemy creature in combat regardless of power.
  - SNEAKY   – can only be blocked by Sneaky creatures (Hunter overrides).
  - TOUGH    – first lethal hit (combat or effect) exhausts the creature instead of
               defeating it; being exhausted does not restrict its actions.

Card data sourced from https://mindbug.fandom.com/wiki/First_Contact
"""
from __future__ import annotations
import copy, io, contextlib, random

MCTS_SIMS = 100   # Monte Carlo simulations per candidate action

FRENZY    = "Frenzy"
HUNTER    = "Hunter"
POISONOUS = "Poisonous"
SNEAKY    = "Sneaky"
TOUGH     = "Tough"

_KW_ORDER = [FRENZY, HUNTER, POISONOUS, SNEAKY, TOUGH]


# ─── Card ─────────────────────────────────────────────────────────────────────

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


# ─── Player ───────────────────────────────────────────────────────────────────

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


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def _int(prompt: str, lo: int, hi: int, decider: Player | None = None) -> int:
    """Prompt for an integer in [lo, hi]. Bot players choose randomly (or from queue)."""
    if decider and decider.is_bot:
        if decider.choice_queue:
            v = max(lo, min(hi, int(decider.choice_queue.pop(0))))
        else:
            v = random.randint(lo, hi)
        print(f"  [Bot] {prompt.strip()} → {v}")
        return v
    while True:
        try:
            v = int(input(prompt).strip())
            if lo <= v <= hi:
                return v
            print(f"  Enter {lo}–{hi}.")
        except (ValueError, EOFError):
            print("  Invalid input.")

def _yes(prompt: str, decider: Player | None = None) -> bool:
    """Prompt for y/n. Bot players choose randomly (or from queue)."""
    if decider and decider.is_bot:
        if decider.choice_queue:
            v = bool(decider.choice_queue.pop(0))
        else:
            v = random.choice([True, False])
        print(f"  [Bot] {prompt.strip()} → {'yes' if v else 'no'}")
        return v
    while True:
        a = input(prompt + " [y/n]: ").strip().lower()
        if a in ("y", "yes"): return True
        if a in ("n", "no"):  return False
        print("  y or n.")

def _sep(w: int = 66): print("─" * w)
def _hdr(title: str, w: int = 66): print(f"\n{'═'*w}\n  {title}\n{'═'*w}")


# ─── Effect helpers ───────────────────────────────────────────────────────────

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


# ─── Deck builder ─────────────────────────────────────────────────────────────

def build_deck() -> list[Card]:
    """Return all 48 official First Contact base set cards (shuffled).
    Stats sourced from https://mindbug.fandom.com/wiki/First_Contact
    """
    all_cards: list[Card] = []

    def add(copies: int, name: str, power: int, text: str = "", keywords=None,
            on_played=None, on_attack=None, on_defeated=None):
        c = Card(name, power, text, keywords)
        c.on_played   = on_played
        c.on_attack   = on_attack
        c.on_defeated = on_defeated
        for _ in range(copies):
            all_cards.append(c.clone())

    S, D = 1, 2

    # ── Singles ────────────────────────────────────────────────────────────────
    add(S, "Bee Bear", 8,
        "Cannot be blocked by creatures with power 6 or less.")
    add(S, "Brain Fly", 4,
        "Play: Take control of an enemy creature with power 6 or more.",
        on_played=_brain_fly_play)
    add(S, "Chameleon Sniper", 1,
        "Sneaky. Attack: The opponent loses 1 life point.",
        [SNEAKY],
        on_attack=lambda g, ctrl, card: _damage_opp(g, ctrl, 1))
    add(S, "Deathweaver", 2,
        "Poisonous. While in play: enemy Play effects don't trigger.",
        [POISONOUS])
    add(S, "Elephantopus", 7,
        "Tough. The opponent cannot block with creatures with power 4 or less.",
        [TOUGH])
    add(S, "Giraffodile", 7,
        "Play: Draw your entire discard pile.",
        on_played=lambda g, ctrl, card: _own_discard_to_hand(g, ctrl))
    add(S, "Gorillion", 10, "")
    add(S, "Harpy Mother", 5,
        "Defeated: Take control of up to 2 enemy creatures with power 5 or less.",
        on_defeated=_harpy_defeated)
    add(S, "Lone Yeti", 5,
        "Tough. While your only allied creature: +5 power and Frenzy.",
        [TOUGH])
    add(S, "Mysterious Mermaid", 7,
        "Play: Set your life points equal to the opponent's.",
        on_played=_mermaid_play)
    add(S, "Shark Dog", 4,
        "Hunter. Attack: Defeat an enemy creature with power 6 or more.",
        [HUNTER],
        on_attack=_shark_dog_attack)
    add(S, "Sharky Crab-Dog-Mummypus", 5,
        "While an enemy has Hunter/Sneaky/Frenzy/Poisonous, this creature has it too.")
    add(S, "Snail Thrower", 1,
        "Poisonous. Other allied creatures with base power 4 or less gain Hunter and Poisonous.",
        [POISONOUS])
    add(S, "Strange Barrel", 6,
        "Defeated: Steal 2 random cards from the opponent's hand.",
        on_defeated=_strange_barrel_defeated)
    add(S, "Turbo Bug", 4,
        "Attack: The opponent loses all life points except one.",
        on_attack=_turbo_bug_attack)
    add(S, "Urchin Hurler", 5,
        "Hunter. Other allied creatures have +2 power while it is your turn.",
        [HUNTER])

    # ── Doubles ────────────────────────────────────────────────────────────────
    add(D, "Axolotl Healer", 4,
        "Poisonous. Play: Gain 2 life points.",
        [POISONOUS],
        on_played=lambda g, ctrl, card: _gain_life(g, ctrl, 2))
    add(D, "Compost Dragon", 3,
        "Hunter. Play: Put a card from your discard pile into play.",
        [HUNTER],
        on_played=_compost_dragon_play)
    add(D, "Explosive Toad", 5,
        "Frenzy. Defeated: Defeat a creature.",
        [FRENZY],
        on_defeated=_explosive_toad_defeated)
    add(D, "Ferret Bomber", 2,
        "Sneaky. Play: The opponent discards 2 cards.",
        [SNEAKY],
        on_played=lambda g, ctrl, card: _opp_discards(g, ctrl, 2))
    add(D, "Goblin Werewolf", 2,
        "Hunter. Has +6 power while it is your turn (P:2 base → P:8 when attacking).",
        [HUNTER])
    add(D, "Grave Robber", 7,
        "Tough. Play: Put a card from the opponent's discard pile into play under your control.",
        [TOUGH],
        on_played=_grave_robber_play)
    add(D, "Kangasaurus Rex", 7,
        "Play: Defeat all enemy creatures with power 4 or less.",
        on_played=_kangasaurus_play)
    add(D, "Killer Bee", 5,
        "Hunter. Play: The opponent loses 1 life point.",
        [HUNTER],
        on_played=lambda g, ctrl, card: _damage_opp(g, ctrl, 1))
    add(D, "Luchataur", 9,
        "Frenzy.",
        [FRENZY])
    add(D, "Plated Scorpion", 2,
        "Tough, Poisonous.",
        [TOUGH, POISONOUS])
    add(D, "Rhino Turtle", 8,
        "Frenzy, Tough.",
        [FRENZY, TOUGH])
    add(D, "Shield Bugs", 4,
        "Tough. Other allied creatures have +1 power.",
        [TOUGH])
    add(D, "Snail Hydra", 9,
        "Attack: If you have fewer creatures than the opponent, defeat a creature.",
        on_attack=_snail_hydra_attack)
    add(D, "Spider Owl", 3,
        "Sneaky, Poisonous.",
        [SNEAKY, POISONOUS])
    add(D, "Tiger Squirrel", 3,
        "Sneaky. Play: Defeat an enemy creature with power 7 or more.",
        [SNEAKY],
        on_played=_tiger_squirrel_play)
    add(D, "Tusked Extorter", 8,
        "Attack: The opponent discards a card.",
        on_attack=lambda g, ctrl, card: _opp_discards(g, ctrl, 1))

    assert len(all_cards) == 48, f"Expected 48, got {len(all_cards)}"
    random.shuffle(all_cards)
    return all_cards


# ─── Monte Carlo simulation ───────────────────────────────────────────────────

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
                action            = ctrl._sim_main
                ctrl._sim_main    = None
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

            _determinize(g, opp_idx)   # hide ctrl's hand/draw_pile from opp's perspective
            for p in g.players:    # ensure all bots use random during effects
                p.bot_type = "random"

            with contextlib.redirect_stdout(io.StringIO()):
                if use_mb:
                    g_opp.mindbugs -= 1
                    g_opp.in_play.append(card_c)
                    if card_c.on_played and not g._has_deathweaver(g_ctrl):
                        card_c.on_played(g, g_opp, card_c)
                    # ctrl gets an extra turn — active_idx already points at ctrl
                    g.extra_turn = False
                else:
                    g_ctrl.in_play.append(card_c)
                    if card_c.on_played and not g._has_deathweaver(g_opp):
                        card_c.on_played(g, g_ctrl, card_c)
                    # ctrl's turn is over; advance to opp
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
    Note: Frenzy follow-up attacks are not modelled (conservative simplification).
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
            g     = copy.deepcopy(game)
            g_opp = g.players[opp_idx]
            g_ctrl= g.players[ctrl_idx]

            _determinize(g, opp_idx)   # hide ctrl's hand/draw_pile from opp's perspective
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

                # If attacker survived and has Frenzy, force a second attack
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

    # Build candidate list: (action_type, 1-based index, display label)
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

        # Probability the opponent Mindbugs this card if we play it
        mb_prob = 0.0
        if action_type == "play" and opp.mindbugs > 0 and ctrl.hand:
            mb_prob = min(1.0, opp.mindbugs / len(ctrl.hand))

        for _ in range(MCTS_SIMS):
            g     = copy.deepcopy(game)
            _determinize(g, ctrl_idx)   # hide opp's hand/draw_pile from ctrl's perspective
            bot   = g.players[ctrl_idx]
            g_opp = g.players[opp_idx]
            bot._sim_main    = action_type
            bot.choice_queue = [choice_idx]

            # Pre-load the opponent's Mindbug decision using the risk probability
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


# ─── Game ─────────────────────────────────────────────────────────────────────

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

    def run(self):
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


# ─── Entry point ──────────────────────────────────────────────────────────────

def run_batch(n: int):
    """Run n silent games of Random Bot vs MCTS Bot and print a summary."""
    wins = {"Random Bot": 0, "MCTS Bot": 0}
    for i in range(1, n + 1):
        p1 = Player("Random Bot", bot_type="random")
        p2 = Player("MCTS Bot",   bot_type="mcts")
        with contextlib.redirect_stdout(io.StringIO()):
            winner = Game(p1, p2).run()
        wins[winner.name] += 1
        print(f"  Game {i:>{len(str(n))}}/{n}  →  {winner.name} wins"
              f"  (Random {wins['Random Bot']} – {wins['MCTS Bot']} MCTS)")
    _sep()
    total = wins["Random Bot"] + wins["MCTS Bot"]
    print(f"  Results after {total} games:")
    for name, w in wins.items():
        print(f"    {name:<12}  {w:>4} wins  ({w/total:.1%})")
    _sep()


def main():
    _hdr("MINDBUG SIMULATOR")
    _sep()
    p1_name = input("  Your name [Player 1]: ").strip() or "Player 1"

    print("  Opponent:  [h]uman  [r]andom bot  [m]cts bot  [s]imulate (random vs mcts)")
    mode = input("  Choice: ").strip().lower()

    if mode in ("s", "simulate"):
        while True:
            try:
                n = int(input("  Number of games to simulate: ").strip())
                if n > 0:
                    break
                print("  Enter a positive integer.")
            except ValueError:
                print("  Enter a positive integer.")
        print(f"  Simulating {n} games: Random Bot vs MCTS Bot  ({MCTS_SIMS} sims/action)\n")
        run_batch(n)
        return
    elif mode in ("r", "random"):
        p1 = Player(p1_name)
        p2 = Player("Random Bot", bot_type="random")
        print(f"  {p1_name} vs Random Bot")
    elif mode in ("m", "mcts"):
        p1 = Player(p1_name)
        p2 = Player("MCTS Bot", bot_type="mcts")
        print(f"  {p1_name} vs MCTS Bot  (each MCTS turn: {MCTS_SIMS} sims per action)")
    else:
        p2_name = input(f"  Player 2 name [Player 2]: ").strip() or "Player 2"
        p1 = Player(p1_name)
        p2 = Player(p2_name)

    Game(p1, p2).run()


if __name__ == "__main__":
    main()
