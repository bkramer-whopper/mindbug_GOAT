from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from player import Player


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
