"""Shared configuration, seeds, and the action space for the ML subsystem.

Reproducibility
---------------
Every stochastic component in this package draws from a generator seeded from
:data:`GLOBAL_SEED` through :func:`rng`, and every seed is *derived* from a
label rather than shared. Two components that both used ``default_rng(42)``
would consume correlated streams — the dataset generator and the bandit's
exploration draws would be statistically linked, which quietly invalidates any
regret measurement. Deriving a distinct seed per label removes that coupling
while keeping the whole pipeline reproducible from one number.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

import numpy as np

__all__ = [
    "ACTIONS",
    "ACTION_INDEX",
    "ARTIFACT_DIR",
    "COST_FALSE_SAFE",
    "COST_FALSE_RISKY",
    "GLOBAL_SEED",
    "RESULTS_DIR",
    "RISK_LEVELS",
    "rng",
    "seed_for",
]

#: The single number the whole pipeline is reproducible from.
GLOBAL_SEED: Final = 20260901

#: Where trained artefacts and evaluation results are written.
ARTIFACT_DIR: Final = Path(__file__).resolve().parent / "artifacts"
RESULTS_DIR: Final = Path(__file__).resolve().parent / "results"

#: Assistance modes the policy may select, in ascending privilege order.
ACTIONS: Final = ("restricted", "voice", "pointer", "drawing", "tap")
ACTION_INDEX: Final = {action: i for i, action in enumerate(ACTIONS)}

#: Risk classes.
RISK_LEVELS: Final = ("low", "medium", "high")

# ----------------------------------------------------------------------
# Asymmetric costs
# ----------------------------------------------------------------------

#: Cost of classifying a genuinely risky context as safe.
#:
#: This is the error that lets a helper tap inside an open banking app on an
#: elderly person's phone. It is not symmetric with the opposite error, and a
#: model tuned for accuracy or even F1 implicitly treats it as though it were.
#: The ratio below (10:1) is a judgement, not a measurement — it says one
#: missed protection is as bad as ten unnecessary restrictions. It is stated
#: explicitly here so that it can be argued with, which is the point: a hidden
#: 1:1 assumption cannot be.
COST_FALSE_SAFE: Final = 10.0

#: Cost of classifying a safe context as risky. The user is restricted to a
#: lower assistance mode than they needed, which is an annoyance — they can
#: still be helped by voice — not a harm.
COST_FALSE_RISKY: Final = 1.0


def seed_for(label: str) -> int:
    """Derive a stable, independent seed for a named component.

    Uses BLAKE2b over ``label`` mixed with :data:`GLOBAL_SEED`, so changing the
    global seed re-randomises everything coherently while distinct labels stay
    uncorrelated with each other.
    """
    digest = hashlib.blake2b(
        f"{GLOBAL_SEED}:{label}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") % (2**32 - 1)


def rng(label: str) -> np.random.Generator:
    """Return a NumPy generator seeded independently for ``label``."""
    return np.random.default_rng(seed_for(label))
