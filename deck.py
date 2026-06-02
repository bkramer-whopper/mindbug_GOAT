import random

from card import Card
from constants import FRENZY, HUNTER, POISONOUS, SNEAKY, TOUGH
from effects import (
    _gain_life, _damage_opp, _opp_discards, _own_discard_to_hand,
    _brain_fly_play, _compost_dragon_play, _grave_robber_play,
    _mermaid_play, _kangasaurus_play, _tiger_squirrel_play,
    _shark_dog_attack, _harpy_defeated, _explosive_toad_defeated,
    _strange_barrel_defeated, _turbo_bug_attack, _snail_hydra_attack,
)


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
