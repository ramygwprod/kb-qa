"""kbqa — validation gates for evidence-grounded data collection.

Checks that every collected row is traceable to a verbatim quote in a stored
page capture. This package reads a data estate and writes verdicts. It never
mutates collected data.
"""

__version__ = "2.1.0"
