"""Vertical product packages.

The generic core executes governed workflows; it does not know business-specific
meaning. Business-specific profile, policies, workflow contracts and metrics
live under this package so a vertical is a configuration layer, not a runtime
fork.
"""

from .car_dealership_us import CarDealershipUSProfile, WORKFLOW_CONTRACTS

# name -> package-level exports. Add a vertical only after a paid pilot proves
# which parts repeat; a registry entry that nothing sells is dead weight.
VERTICALS: dict = {
    "car_dealership_us": {
        "profile": CarDealershipUSProfile,
        "workflow_contracts": WORKFLOW_CONTRACTS,
    },
}

__all__ = ["VERTICALS", "CarDealershipUSProfile", "WORKFLOW_CONTRACTS"]
