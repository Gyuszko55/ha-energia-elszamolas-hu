"""Több havonta számlázott víz: a folyó időszak a számlázási időszak (2.3.0b10)."""
from datetime import date, datetime

from custom_components.hu_rezsi.koordinator import _tobbhavi_folyo_idoszak
from custom_components.hu_rezsi.szamla_import import atalany_szamitas


def _t(*idoszakok, storno=None):
    sz = {f"S{i}": {"tipus": "resz", "kelte": ig, "idoszak": [tol, ig]} for i, (tol, ig) in enumerate(idoszakok)}
    if storno:
        sz["ST"] = {"tipus": "storno", "kelte": "2026-11-01", "idoszak": storno}
    return {"szamlak": sz}


def test_kethavi():
    assert _tobbhavi_folyo_idoszak(_t(("2026-08-01", "2026-09-30")), 2, date(2026, 11, 5)) == (date(2026, 10, 1), date(2026, 12, 1))


def test_negyhavi():
    t = _t(("2026-05-01", "2026-08-31"), ("2026-04-01", "2026-04-30"))
    assert _tobbhavi_folyo_idoszak(t, 4, date(2026, 11, 5)) == (date(2026, 9, 1), date(2027, 1, 1))


def test_kesett_szamla_tovabblep():
    assert _tobbhavi_folyo_idoszak(_t(("2026-08-01", "2026-09-30")), 2, date(2026, 12, 3)) == (date(2026, 12, 1), date(2027, 2, 1))


def test_nincs_idoszakos_szamla_vagy_havi():
    assert _tobbhavi_folyo_idoszak({"szamlak": {"X": {"tipus": "resz"}}}, 2, date(2026, 11, 5)) is None
    assert _tobbhavi_folyo_idoszak(_t(("2026-08-01", "2026-09-30")), 1, date(2026, 11, 5)) is None


def test_atalany_kethavi_idoszakra():
    t = {"szamlak": {"R-1": {"tipus": "resz", "osszeg": "18300", "kelte": "2026-10-01", "idoszak": ["2026-08-01", "2026-09-30"]}}}
    a = atalany_szamitas(None, t, date(2026, 10, 1), date(2026, 12, 1), datetime(2026, 11, 5))
    assert a["idoszak_ft"] == 18300 and a["napok"] == 61
    assert 8800 < a["havi"] < 9400  # egy átlagos hónap, nem a két hónap
    havi = atalany_szamitas(None, t, date(2026, 11, 1), date(2026, 12, 1), datetime(2026, 11, 5))
    assert havi["havi"] == havi["idoszak_ft"] == round(18300 / 61 * 30)


def test_honapvegi_szamlavegnel_nem_csuszik():
    """Hónap végi kezdőnapnál (01.31.) a lépések nem csúsznak el (31 → 30 → 28)."""
    t = _t(("2025-11-30", "2026-01-30"))
    assert _tobbhavi_folyo_idoszak(t, 2, date(2026, 10, 5)) == (date(2026, 9, 30), date(2026, 11, 30))
    assert _tobbhavi_folyo_idoszak(t, 2, date(2027, 2, 1)) == (date(2027, 1, 31), date(2027, 3, 31))
