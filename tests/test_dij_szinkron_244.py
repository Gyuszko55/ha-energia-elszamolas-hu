"""2.4.4: díj-beállítás módosítása után a lezárt időszakok újraszámolódnak (felhasználói jelzés: H-tarifa nyári
időszaka a „Kedvezményes keret jár” / szolgáltató módosítása előtti, keret nélküli piaci áron maradt). Kitalált adatok."""
from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from modell import dij_szinkron, dij_ujjlenyomat
from motor.dijszabas import DijszabasTar
from motor.elszamolas import szamol
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

H = {"kozmu": "villany", "szolgaltato": "eon", "dijszabas": "villany/h", "dijszabas_tol": "2025-10-10", "keret_aktiv": True}
LEZART = [{"tol": "2026-04-14", "ig": "2026-09-13", "osszesen_ft": 74237}]


def test_elso_futas_csak_feljegyez():
    tarolt = {"lezart": list(LEZART)}
    assert dij_szinkron(tarolt, H) is True
    assert tarolt["dij_beallitas"] == dij_ujjlenyomat(H) and "lezart_ujra" not in tarolt
    assert dij_szinkron(tarolt, H) is False  # változatlan beállítás: nincs újraszámolás


def test_keret_vagy_szolgaltato_modositasa_ujraszamoltat():
    for valtozas in ({"keret_aktiv": False}, {"szolgaltato": "mvm_demasz"}, {"dijszabas": "villany/a1"},
                     {"dijszabas_tol": "2026-01-01"}, {"h_teli_forras": "sensor.t", "h_nyari_forras": "sensor.ny"}):
        tarolt = {"lezart": list(LEZART)}
        dij_szinkron(tarolt, H)
        assert dij_szinkron(tarolt, {**H, **valtozas}) is True, valtozas
        assert tarolt["lezart_ujra"] == "2000-01-01" and tarolt["lezart_ujra_megtart"] is True, valtozas


def test_mas_beallitas_nem_ujraszamoltat():
    tarolt = {"lezart": list(LEZART)}
    dij_szinkron(tarolt, H)
    assert dij_szinkron(tarolt, {**H, "nev": "Villany H", "email_feladok": "x@example.com"}) is False
    assert "lezart_ujra" not in tarolt


def test_lezart_nelkul_nincs_mit_ujraszamolni():
    tarolt = {"lezart": []}
    dij_szinkron(tarolt, H)
    assert dij_szinkron(tarolt, {**H, "keret_aktiv": False}) is True and "lezart_ujra" not in tarolt


def test_korabbi_kezdonap_jelzes_megmarad_legkorabbi():
    tarolt = {"lezart": list(LEZART)}
    dij_szinkron(tarolt, H)
    tarolt["lezart_ujra"] = "2025-10-10"  # a kezdőnap módosítása is jelzett (mero_szinkron)
    dij_szinkron(tarolt, {**H, "keret_aktiv": False})
    assert tarolt["lezart_ujra"] == "2000-01-01"


def test_h_nyari_idoszak_kerettel_es_nelkule():
    """A jelzett eset: E.ON-terület, egy diktálási időszak ápr. 14. – szept. 13., 1048 kWh. A H-mérő nyári regiszterére
    saját kedvezményes keret jár (152 nap ≈ 1037 kWh): kb. 36 Ft/kWh; keret nélkül ~70 Ft/kWh."""
    tar = DijszabasTar.mappabol(DIJSZABASOK)
    s = Szamlalo([Pont(datetime(2025, 10, 18), D(0), True), Pont(datetime(2026, 4, 14), D(5441), True),
                  Pont(datetime(2026, 9, 13), D(6489), True)])

    def ossz(keret: bool) -> D:
        f = Fiok(Kozmu.VILLANY, "eon", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))], [Csatorna(keret_aktiv=keret)])
        return szamol(f, tar, date(2026, 4, 14), date(2026, 9, 13), [s]).osszesen_ft

    assert ossz(True) == D(37593)
    assert ossz(False) == D(73595)
