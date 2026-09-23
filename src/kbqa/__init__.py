"""kbqa — validation gates for evidence-grounded data collection.

Checks that every collected row is traceable to a verbatim quote in a stored
page capture. This package reads a data estate and writes verdicts. It never
mutates collected data.
"""

__version__ = "6.12.1"

# Import registers the bundled profiles; one is activated so a bare
# `python -m kbqa g2 ...` has a contract to validate against. Override with
# `--profile <name>`.
from . import profiles as _profiles  # noqa: E402,F401
from . import profile as _profile  # noqa: E402

_profile.activate("vendor-catalogue")
