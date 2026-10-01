"""v1-paritás: a v1 YAML-csomag lezárt havi naplóját az új motorral újraszámolva ugyanazt kell kapni.

Az adat személyes, ezért nincs a tárolóban: a `helyi_adatok/sensor.villany_havi_elszamolas_naplo.json`
fájlból olvas (a HA állapot-API kimenete). Ha nincs meg, a teszt kimarad.

Tűrés: a napló 0,1 kWh-ra kerekített fogyasztást tárol, ez a piaci áron legfeljebb ~3,5 Ft-ot jelent;
a v1 az alapdíjakat összevonva kerekítette, mi fiókonként – ez ±1 Ft.
"""

import json
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from tests.conftest import DIJSZABASOK, HELYI_ADATOK
from motor.dijszabas import DijszabasTar
from motor.elszamolas import szamol
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

NAPLO = HELYI_ADATOK / "sensor.villany_havi_elszamolas_naplo.json"
pytestmark = pytest.mark.skipif(not NAPLO.exists(), reason="nincs helyi v1-napló")


def _honapok():
    if not NAPLO.exists():
        return []
    return json.loads(NAPLO.read_text())["attributes"]["honapok"]


def _hatarok(h: str) -> tuple[date, date]:
    y, m = int(h[:4]), int(h[5:7])
    tol, ig = date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
    if "/" in h:  # éves leolvasásnál megosztott hónap: a v1 a leolvasás napjánál vágott
        vagas = date(2026, 9, 29) if h == "2026-09/1" or h == "2026-09/2" else None
        tol, ig = (tol, vagas) if h.endswith("/1") else (vagas, ig)
    return tol, ig


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


def v1_mod_tar() -> DijszabasTar:
    """A díjfájlok a v1 szabályaival: 6,91 kWh/nap kerekítés nélkül, napra arányosított alapdíj."""
    tar = DijszabasTar.mappabol(DIJSZABASOK)
    v1_arak = {  # a v1 díjtáblázata, bruttó (MVM Démász)
        "villany/a1": {"energia_kedvezmenyes": D("36.386"), "energia_piaci": D("70.104"), "alapdij_ho": D("153.035")},
        "villany/h": {"energia_teli": D("22.962"), "alapdij_ho": D("50.165")},
    }
    for azon, arak in v1_arak.items():
        for v in tar[azon].verziok:
            v.szabalyok["alapdij"] = {"mod": "napi_aranyos"}
            if "keret" in v.szabalyok:
                v.szabalyok["keret"] = {"tipus": "napi_aranyos", "napi_mennyiseg": D("6.91")}
            v.dijak.clear()
            v.dijak["alap"] = arak
    return tar


@pytest.mark.parametrize("m", _honapok(), ids=lambda m: m["honap"])
def test_v1_honap(m):
    tar = v1_mod_tar()
    tol, ig = _hatarok(m["honap"])

    a = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()])
    ra = szamol(a, tar, tol, ig, [Szamlalo([Pont(_dt(tol), D(0), True), Pont(_dt(ig), D(str(m["a_kwh"])), True)])])

    teli, nyari = D(str(m["h_teli_kwh"])), D(str(m["h_nyari_kwh"]))
    pontok = [Pont(_dt(tol), D(0), True)]
    if tol.day == 1 and tol.month == 4:
        pontok.append(Pont(datetime(tol.year, 4, 15), teli, True))
    if tol.day == 1 and tol.month == 10:
        pontok.append(Pont(datetime(tol.year, 10, 15), nyari, True))
    pontok.append(Pont(_dt(ig), teli + nyari, True))
    h = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))], [Csatorna()])
    rh = szamol(h, tar, tol, ig, [Szamlalo(pontok)])

    assert abs(ra.energia_ft - m["energia_ft"]) <= 4
    assert abs(rh.energia_ft_ahol(idenyszak="teli") - m["h_teli_ft"]) <= 4
    assert abs(rh.energia_ft_ahol(idenyszak="nyari") - m["h_nyari_ft"]) <= 4
    # A H alapdíj a v1-ben a H-mérő bekötésétől (2026-02) jár.
    alap = ra.alapdij_ft + (rh.alapdij_ft if m["alapdij_ft"] > 153 or tol >= date(2026, 2, 1) else 0)
    assert abs(alap - m["alapdij_ft"]) <= 1
