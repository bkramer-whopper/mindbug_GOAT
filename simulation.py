import contextlib, io

from player import Player
from game import Game
from mcts import MCTS_SIMS
from ui import _sep


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
