"""MVM stornó (2.3.0b10): a hivatkozás a PDF szövegéből („Stornózott számla száma”), és hivatkozás nélkül a párosítás
a stornónál korábbi számlát választja – nem a vele egy napon újra kiállítottat (kitalált adatok)."""
import tests.conftest  # noqa: F401
from custom_components.hu_rezsi.szamlak import storno_hivatkozas
from custom_components.hu_rezsi.szamla_import import storno_parositas


def test_storno_hivatkozas_mvm_szoveg():
    assert storno_hivatkozas("Számla sorszáma: 900\nStornózott számla száma: 11100000001\n") == "11100000001"
    assert storno_hivatkozas("Sztornózott számla sorszáma: 22200000002") == "22200000002"
    assert storno_hivatkozas("Számla sorszáma: 900") == ""


def test_parositas_a_korabbi_szamlat_sztornozza():
    i = ["2026-01-13", "2026-02-02"]
    sz = {
        "EREDETI": {"kelte": "2026-02-04", "tipus": "elszamolo", "forras": "mvm_aram", "idoszak": i, "osszeg": "25000", "szamlaertek": "25000"},
        "STORNO": {"kelte": "2026-02-27", "tipus": "storno", "forras": "mvm_aram", "idoszak": i, "osszeg": "0", "szamlaertek": "-25000"},
        "UJ": {"kelte": "2026-02-27", "tipus": "elszamolo", "forras": "mvm_aram", "idoszak": i, "osszeg": "0", "szamlaertek": "25000"},
    }
    storno_parositas(sz)
    assert sz["STORNO"]["sztornozott"] == "EREDETI"
    # Korábbi nélkül az azonos napi is párosítható (mint eddig).
    sz2 = {k: dict(v) for k, v in sz.items() if k != "EREDETI"}
    sz2["STORNO"].pop("sztornozott")
    storno_parositas(sz2)
    assert sz2["STORNO"]["sztornozott"] == "UJ"
