"""A motor HA nélkül tesztelhető: a csomag mappáját közvetlenül a path-ra tesszük."""

import sys
from pathlib import Path

GYOKER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GYOKER / "custom_components" / "hu_rezsi"))
DIJSZABASOK = GYOKER / "custom_components" / "hu_rezsi" / "dijszabasok"
HELYI_ADATOK = GYOKER.parent / "helyi_adatok"
