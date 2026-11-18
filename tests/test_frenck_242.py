"""2.4.2: a javítás-gombok delegált figyelője csak egyszer kerül a shadow rootra (hacs/default#13437 javaslata)."""

import json
import re
from pathlib import Path

CS = Path(__file__).resolve().parents[1] / "custom_components" / "hu_rezsi"


def test_javitas_figyelo_egyszer():
    js = (CS / "frontend" / "rezsi-panel-fo.js").read_text(encoding="utf-8")
    torzs = js[js.index("  _javitasKezelo() {"):]
    torzs = torzs[:torzs.index("\n  }\n")]
    assert 'this._egyszer("javit", () => r.addEventListener("click"' in torzs
    # a shadow rootra védelem nélkül nem kerül figyelő
    assert not re.search(r"^\s*r\.addEventListener\(", torzs, re.M)


def test_verzio():
    assert json.loads((CS / "manifest.json").read_text(encoding="utf-8"))["version"] in ("2.4.2", "2.4.3")
