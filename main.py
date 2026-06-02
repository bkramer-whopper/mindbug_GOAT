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
from player import Player
from game import Game
from simulation import run_batch
from mcts import MCTS_SIMS
from ui import _hdr, _sep


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
