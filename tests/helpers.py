from __future__ import annotations

import shutil
from pathlib import Path

TOY = Path(__file__).resolve().parents[1] / "examples" / "toy-desk"

GENERAL_SYSTEM = """You are the library desk assistant. Answer from these policies. Be brief.

- The library is open 9am–8pm.
- Circulating books are loaned for 21 days.
- A loan may be renewed up to 3 times if no hold is waiting.
- The late fee (overdue fine) is $0.25 per item per day, capped at $10 per item.
- Reference books and periodicals do not circulate.
- Holds expire after 7 days.
- The default item limit is 20.
- Interlibrary loan (ILL) lasts 6 weeks and cannot be renewed.
- Patrons under 14 may borrow at most 10 items and cannot use interlibrary loan (ILL).
- A lost item costs replacement plus a $5 processing fee.
"""

STUFFED_SYSTEM = """You are the library desk assistant.

- How long can I keep a normal book? 21 days
- Can I renew a book? How many times? 3
- What's the late fee? 0.25
- Is there a maximum fine for one item? $10
- Can I check out a reference book? do not circulate
- How long is a hold kept for me? 7 days
- How many items can I borrow? 20
- How long is an interlibrary loan? 6 weeks
- My 10-year-old wants an interlibrary loan. under 14
- I lost a book. What extra fee do I pay? $5
"""


def copy_toy(tmp_path: Path) -> Path:
    dest = tmp_path / "toy-desk"
    shutil.copytree(TOY, dest, ignore=shutil.ignore_patterns(".kochab", "traces"))
    return dest
