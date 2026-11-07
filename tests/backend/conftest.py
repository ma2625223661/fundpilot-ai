# pytest: the backend modules live in ../../backend and import each other by
# name; some tests import shared fixtures from sibling test modules.
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for folder in (HERE, HERE.parents[1] / 'backend'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
