"""Vertical product packages.

The generic core executes governed workflows; it does not know what a grooming
appointment or a pet-food reorder means. Business-specific profile, policies,
workflow contracts and metrics live under this package so a vertical can be a
configuration layer instead of a fork of the runtime.
"""

from .pet_business import PetBusinessProfile, WORKFLOW_CONTRACTS

# name -> package-level exports. Add a vertical only after a paid pilot proves
# which parts repeat; a registry entry that nothing sells is dead weight.
VERTICALS: dict = {
    "pet_business": {
        "profile": PetBusinessProfile,
        "workflow_contracts": WORKFLOW_CONTRACTS,
    },
}

__all__ = ["VERTICALS", "PetBusinessProfile", "WORKFLOW_CONTRACTS"]
