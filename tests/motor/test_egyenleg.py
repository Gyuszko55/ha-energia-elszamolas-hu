"""Részszámlás (átalány) fiók: éves egyenleg."""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.egyenleg import _profil_resz, eves_egyenleg
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

TAR = DijszabasTar.mappabol(DIJSZABASOK)


def _gaz():
    return Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
                eves_bazis=date(2025, 7, 14))


def test_profil_egy_ev_osszege():
    assert abs(_profil_resz(date(2025, 7, 14), date(2026, 7, 14), "gaz") - 1) < D("0.0001")
    assert abs(_profil_resz(date(2025, 1, 1), date(2026, 1, 1), "villany") - 1) < D("0.0001")


def test_gaz_egyenleg():
    s = Szamlalo([Pont(datetime(2024, 7, 14), D(1000), True), Pont(datetime(2025, 7, 14), D(2200), True),
                  Pont(datetime(2025, 10, 1), D(2250), True)])
    reszek = [(date(2025, 7, 27), D(500)),  # az előző év elszámolója – nem az idei év befizetése
              (date(2025, 8, 24), D(11000)), (date(2025, 9, 23), D(11000))]
    e = eves_egyenleg(_gaz(), TAR, s, datetime(2025, 10, 1), reszek, elozo_bazis=date(2024, 7, 14))
    assert (e.befizetve, e.befizetett_db, e.hatralevo_db, e.hatralevo_reszszamla) == (D(22000), 2, 9, D(99000))
    assert e.elozo_ev_fogyasztas == D(1200)
    # tavaly 1 200 m³; okt. 1-től júl. 14-ig a profil szerint ~0,93 → ~1 115 m³ még hátra + 50 m³ eddig
    assert D(1150) < e.varhato_fogyasztas < D(1180)
    assert e.teny_eddig > 0 and e.varhato_eves > e.teny_eddig
    assert e.varhato_egyenleg == e.befizetve + e.hatralevo_reszszamla - e.varhato_eves
    # visszamérés: a tavalyi év számítva vs. befizetve (a 07-27-i elszámolóval együtt)
    assert e.elozo_ev["fizetve"] == D(500)
    assert e.elozo_ev["szamitott"] > 0
