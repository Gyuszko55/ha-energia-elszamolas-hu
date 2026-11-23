"""2.4.4: a meleg szennyvíz (a távhős melegvíz szennyvize, amelyet az ALFÖLDVÍZ számláz) a melegvízmérő állásaiból,
a díj hónaponként az akkor érvényes díjszabással (2025-12-től), és az elszámoló összevetésében is."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import custom_components.hu_rezsi.koordinator as K
from custom_components.hu_rezsi.motor.dijszabas import DijszabasTar
import tests.conftest  # noqa: F401
from szamlak import alfoldviz_szoveg

TAR = DijszabasTar.mappabol(Path(K.__file__).parent / "dijszabasok")

# A távhő fiók melegvízmérője (a távhőszámlákról diktált állások) és a havi távhőszámlák melegvize.
TAVHO = {
    "merok": [{"gyari_szam": "55667788", "leolvasasok": [
        {"datum": d, "allas": a, "csatorna": "vetelezes"} for d, a in
        [("2025-11-30", "18"), ("2026-04-01", "22"), ("2026-08-31", "27"), ("2026-10-31", "28")]]}],
    "szamlak": {"H1": {"idoszak": ["2026-09-01", "2026-09-30"], "elszamolt_tavho": {"melegviz": "0.00"}}},
}
# A vízfiók elszámolója: a vízmű leolvasása a melegvízmérőn (18 → 30).
VIZ = {"szamlak": {"900015LV26": {"tipus": "elszamolo", "meleg_szennyviz": {
    "mero": "55667788", "idoszak": ["2025-12-01", "2026-11-10"], "indulo": "18", "zaro": "30", "m3": "12"}}}}


def _koord(viz=VIZ, tavho=TAVHO):
    k = object.__new__(K.RezsiKoordinator)
    fiokok = {"T": SimpleNamespace(data={K.CONF_KOZMU: "tavho"}), "V": SimpleNamespace(data={K.CONF_KOZMU: "viz"})}
    if tavho is None:
        del fiokok["T"]
    k.fiokok = lambda: fiokok
    k.tarolo = SimpleNamespace(fiok=lambda sid: {"T": tavho, "V": viz}[sid])
    k.tar = TAR
    return k


FIOK = SimpleNamespace(csatornak=[SimpleNamespace(csatornadij_aktiv=True)], szolgaltato="alfoldviz", feluliras=[])


def test_mennyiseg_a_mero_allasaibol(monkeypatch):
    """Az elszámoló időszakára (2025.12.01–2026.11.10) pontosan a mérő szerinti 12 m³ – a vízmű leolvasása az erősebb."""
    k = _koord()
    m = k._melegviz_mennyiseg(minimum=False)
    assert m(date(2025, 12, 1), date(2026, 11, 10)) == Decimal(12)
    # a 18 → 22 szakasz (122 nap, 4 m³) napra arányosítva: 2025. december 31 napja
    assert abs(m(date(2025, 12, 1), date(2026, 1, 1)) - Decimal(4) * 31 / 121) < Decimal("0.001")
    # havi minimummal (részszámla): hónaponként legalább 1 m³ – a szeptemberi 0,5 m³ is 1
    assert k._melegviz_mennyiseg()(date(2026, 9, 1), date(2026, 10, 1)) == 1


def test_meleg_szennyviz_dija_a_szamla_szerint(monkeypatch):
    """900015LV26: 4,21 m³ × 240,30 + 7,79 m³ × 240,30 szennyvíz és a vízterhelési díj ≈ 3 662 + 60 Ft bruttó – a
    díjszabás hónaponként (2025-12-től 242,30, 2026-05-től 247,20 nettó Ft/m³)."""
    monkeypatch.setattr(K, "_hozzarendeles", lambda fiok, nap: "viz/alfoldviz")
    m3, ft, tetel = _koord()._meleg_szennyviz(FIOK, date(2025, 12, 1), date(2026, 11, 10), minimum=False)
    assert m3 == 12 and tetel["nev"] == "Meleg szennyvíz"
    assert 3700 < ft < 3760
    # 2025 novemberében a vízmű még nem számlázta (a díjszabás „meleg_szennyviz” csak 2025-12-től)
    assert _koord()._meleg_szennyviz(FIOK, date(2025, 10, 1), date(2025, 12, 1)) is None


def test_tavho_nelkul_a_vizszamla_allasaibol(monkeypatch):
    """Távhő fiók nélkül is számol, ha a vízszámlán van melegvízmérő-sor; egyik sincs: None."""
    monkeypatch.setattr(K, "_hozzarendeles", lambda fiok, nap: "viz/alfoldviz")
    assert _koord(tavho=None)._melegviz_mennyiseg(minimum=False)(date(2025, 12, 1), date(2026, 11, 10)) == 12
    assert _koord(viz={"szamlak": {}}, tavho=None)._meleg_szennyviz(FIOK, date(2026, 1, 1), date(2026, 2, 1)) is None


def test_szamla_meleg_szennyviz_csak_ha_a_szamla_is_szamlazza(monkeypatch):
    """Összevetés: elszámolón a melegvízmérő-sor időszakára (mért), részszámlán csak ha a szennyvíz több az ivóvíznél."""
    monkeypatch.setattr(K, "_hozzarendeles", lambda fiok, nap: "viz/alfoldviz")
    k = _koord()
    x = VIZ["szamlak"]["900015LV26"]
    assert k._szamla_meleg_szennyviz(FIOK, x, date(2026, 2, 10), date(2026, 11, 10))[0] == 12
    resz = {"tipus": "resz", "elszamolt_viz": {"ivoviz": "2", "csatorna": "4"}}
    assert k._szamla_meleg_szennyviz(FIOK, resz, date(2026, 9, 1), date(2026, 10, 31))[0] == 2
    assert k._szamla_meleg_szennyviz(FIOK, {"tipus": "resz", "elszamolt_viz": {"ivoviz": "2", "csatorna": "2"}},
                                     date(2026, 3, 1), date(2026, 4, 30)) is None


def test_alfoldviz_melegvizmero_sor():
    t = """ALFÖLDVÍZ Zrt. Víziközmű-szolgáltatás elszámoló számla
 Számla sorszáma: 900005LV26  Számla kelte: 2026.11.18
         87654321 Elvezetett                   2025.12.01-2026.03.31                18-30                      4,21 m3              240,30 Ft/m3           1 011,66     27              1 284,81
         mennyiséggel arányos
         87654321 Elvezetett                   2026.04.01-2026.11.10                18-30                      7,79 m3              240,30 Ft/m3           1 871,94     27              2 377,36
"""
    sz = alfoldviz_szoveg(t)
    assert sz.meleg_szennyviz == {"mero": "87654321", "idoszak": (date(2025, 12, 1), date(2026, 11, 10)),
                                  "indulo": 18, "zaro": 30, "m3": Decimal("12.00")}
    assert not sz.meroallasok  # a melegvízmérő nem a vízfiók mérője
