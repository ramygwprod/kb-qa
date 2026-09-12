"""The gates.

Every gate: reads only, writes only a verdict, never mutates the data.

Exit-code convention (spec §3):
    0  PASS / allowed / advisory
    1  FAIL / unreachable
    2  DECLINED — G0 only, and terminal for that vendor
"""

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_DECLINED = 2
