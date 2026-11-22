"""Compatibility shim for PDF §11 innovation_learning package shape.

Canonical implementation lives in `aios.governance.innovation` / `aios.api.innovation`.
This package exposes the same primitives without moving DB models or routes.
"""

from aios.governance.innovation import *  # noqa: F401,F403
from aios.governance.innovation import (  # noqa: F401
    DECISIONS,
    EXPERIMENT_REQUIRED_FIELDS,
    EXPERIMENT_RESULTS,
    EXPERIMENT_TRACKS,
    HYPOTHESIS_KINDS,
    HYPOTHESIS_STATUSES,
    MVP_TYPES,
    Experiment,
    Hypothesis,
    evaluate_experiment,
    innovation_scoreboard,
)

__all__ = [
    "DECISIONS",
    "EXPERIMENT_REQUIRED_FIELDS",
    "EXPERIMENT_RESULTS",
    "EXPERIMENT_TRACKS",
    "HYPOTHESIS_KINDS",
    "HYPOTHESIS_STATUSES",
    "MVP_TYPES",
    "Experiment",
    "Hypothesis",
    "evaluate_experiment",
    "innovation_scoreboard",
    "requires_decision",
]
