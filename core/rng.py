"""Deterministic seeded pseudo-random number generator for SunkGuard core.

Guarantees bit-identical output across platforms and runs for any given seed.
Strictly prohibits unseeded randomness and module-level non-deterministic state.
"""

import random
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")


class SeededRNG:
    """Isolated, seeded deterministic random number generator.

    Uses an isolated instance of Python's Mersenne Twister PRNG.
    Ensures that no global state is accessed or mutated.
    """

    def __init__(self, seed: int):
        self._seed = int(seed)
        self._rng = random.Random(self._seed)

    @property
    def seed(self) -> int:
        return self._seed

    def random(self) -> float:
        """Returns next pseudo-random float in [0.0, 1.0)."""
        return self._rng.random()

    def uniform(self, a: float, b: float) -> float:
        """Returns next pseudo-random float in [a, b]."""
        return self._rng.uniform(a, b)

    def randint(self, a: int, b: int) -> int:
        """Returns next pseudo-random integer in [a, b] inclusive."""
        return self._rng.randint(a, b)

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        """Returns next pseudo-random integer in range."""
        if stop is None:
            return self._rng.randrange(start)
        return self._rng.randrange(start, stop, step)

    def choice(self, seq: Sequence[T]) -> T:
        """Returns a random element from a non-empty sequence."""
        if not seq:
            raise IndexError("Cannot choose from an empty sequence")
        return self._rng.choice(seq)

    def shuffle(self, lst: List[Any]) -> None:
        """In-place Fisher-Yates shuffle using the seeded generator."""
        self._rng.shuffle(lst)

    def get_state(self) -> tuple:
        """Returns the internal state tuple for snapshotting."""
        return self._rng.getstate()

    def set_state(self, state: tuple) -> None:
        """Restores the internal state tuple from a snapshot."""
        self._rng.setstate(state)
