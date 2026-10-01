"""Részszámlás (átalány) fiók: éves egyenleg."""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.egyenleg import _profil_resz, eves_egyenleg
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu, Mero

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


def test_hatralevo_nem_az_elszamolobol():
    # új év, még nincs idei részszámla: a tavalyi utolsó RÉSZszámla számít, nem a bázis utáni elszámoló
    s = Szamlalo([Pont(datetime(2026, 7, 15), D(0), True), Pont(datetime(2026, 10, 1), D(30), True)])
    f = Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))], [Csatorna()], eves_bazis=date(2026, 7, 15))
    reszek = [(date(2026, 3, 3), D(8013)), (date(2026, 8, 4), D(11202))]
    e = eves_egyenleg(f, TAR, s, datetime(2026, 10, 1), reszek, reszszamla_db_ev=5, elozo_ev_mennyiseg=D(132))
    assert (e.befizetve, e.hatralevo_reszszamla) == (D(0), D(8013) * 5)
    assert e.modszer.startswith("beállított") and e.megbizhato
    e2 = eves_egyenleg(f, TAR, s, datetime(2026, 10, 1), reszek, reszszamla_db_ev=5, reszszamla_osszeg=D(9000))
    assert e2.hatralevo_reszszamla == D(45000) and not e2.megbizhato


def test_almero_elorejelzes_aranyosan():
    # eddig 20 m³ a főmérőn, ebből 10 m³ az almérőn (50%): a várható csatornadíj is fele
    from motor.tipusok import Csatorna as Cs
    f = Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
             [Cs(szerep="fo"), Cs(szerep="almero", csatornadij_aktiv=False, levonas_fobol=True)], eves_bazis=date(2026, 7, 15))
    fo = Szamlalo([Pont(datetime(2026, 7, 15), D(0), True), Pont(datetime(2026, 10, 1), D(20), True)])
    al = Szamlalo([Pont(datetime(2026, 7, 15), D(117), True), Pont(datetime(2026, 10, 1), D(127), True)])
    e = eves_egyenleg(f, TAR, fo, datetime(2026, 10, 1), [], reszszamla_db_ev=5, elozo_ev_mennyiseg=D(100), tovabbi=[al])
    import dataclasses
    f0 = dataclasses.replace(f, csatornak=f.csatornak[:1])  # ugyanaz almérő nélkül
    e0 = eves_egyenleg(f0, TAR, fo, datetime(2026, 10, 1), [], reszszamla_db_ev=5, elozo_ev_mennyiseg=D(100))
    assert e.varhato_eves < e0.varhato_eves  # az almérő levonása csökkenti


def test_almero_tavalyi_arany_ha_nincs_idei_adat():
    import dataclasses
    from motor.tipusok import Csatorna as Cs
    f = Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
             [Cs(szerep="fo"), Cs(szerep="almero", csatornadij_aktiv=False, levonas_fobol=True)], eves_bazis=date(2026, 7, 15))
    # tavaly 128 m³ a főmérőn, 36 m³ az almérőn; idén még nincs leolvasás
    fo = Szamlalo([Pont(datetime(2025, 7, 27), D(684), True), Pont(datetime(2026, 7, 15), D(812), True)])
    al = Szamlalo([Pont(datetime(2025, 7, 27), D(81), True), Pont(datetime(2026, 7, 15), D(117), True)])
    e = eves_egyenleg(f, TAR, fo, datetime(2026, 10, 1), [], reszszamla_db_ev=12, elozo_bazis=date(2025, 7, 27), tovabbi=[al])
    f0 = dataclasses.replace(f, csatornak=f.csatornak[:1])
    e0 = eves_egyenleg(f0, TAR, fo, datetime(2026, 10, 1), [], reszszamla_db_ev=12, elozo_bazis=date(2025, 7, 27))
    assert e.elozo_ev_fogyasztas == D(128)
    assert e.varhato_eves < e0.varhato_eves  # a tavalyi 28%-os almérő-arány csökkenti a csatornadíjat


def test_varhato_elszamolas():
    from motor.egyenleg import varhato_elszamolas
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()])
    # 04-10 óta 1 800 kWh; azóta két részszámla (13 006 + 14 624), előtte egy (nem számít)
    s = Szamlalo([Pont(datetime(2026, 4, 10), D(18827), True), Pont(datetime(2026, 9, 29), D(20627), True)])
    bef = [(date(2026, 4, 13), D(17219)), (date(2026, 5, 14), D(13006)), (date(2026, 6, 9), D(14624))]
    e = varhato_elszamolas(f, TAR, s, datetime(2026, 9, 29), date(2026, 4, 10), bef)
    assert e.mennyiseg == D(1800) and e.szamlak_db == 3 and e.befizetve == D(17219 + 13006 + 14624)
    assert D(80000) < e.tenyleges < D(95000)
    assert e.egyenleg == e.befizetve - e.tenyleges < 0  # ráfizetés várható


def test_mennyisegi_atalany_a1_es_h():
    from motor.egyenleg import atalany_havi
    a1 = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()])
    napi, q, ft = atalany_havi(a1, TAR, date(2026, 10, 1), date(2026, 11, 1), D(293))
    assert round(napi, 3) == round(D(293) * 12 / 365, 3) and round(q, 1) == round(D(293) * 12 / 365 * 31, 1)
    assert D(13500) < ft < D(14500)  # ~299 kWh: 214 a kereten belül, ~85 piaci áron, + alapdíj
    h = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False), Csatorna(szerep="h_nyari")])
    _, qh, fth = atalany_havi(h, TAR, date(2026, 10, 1), date(2026, 11, 1), D(10))
    assert round(qh, 1) == round(D(10) * 12 / 365 * 31, 1) and D(250) < fth < D(400)  # ~10 kWh + 51 Ft alapdíj


def test_h_regiszteres_eves_egyenleg_rovid_ev_utan():
    # H-óra 2026-02-08 óta: 474 kWh téli + 528 kWh nyári; éves leolvasás 2026-09-29 (2 napja)
    h = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False, merok=[Mero("H", date(2026, 2, 8))]), Csatorna(szerep="h_nyari")],
             eves_bazis=date(2026, 9, 29))
    teli = Szamlalo([Pont(datetime(2026, 2, 8), D(0), True), Pont(datetime(2026, 4, 15), D(474), True), Pont(datetime(2026, 10, 1), D(474), True)])
    nyari = Szamlalo([Pont(datetime(2026, 2, 8), D(0), True), Pont(datetime(2026, 4, 15), D(0), True), Pont(datetime(2026, 10, 1), D(528), True)])
    e = eves_egyenleg(h, TAR, teli, datetime(2026, 10, 1), [], reszszamla_db_ev=11, reszszamla_osszeg=D(347), tovabbi=[nyari])
    assert D(1300) < e.varhato_fogyasztas < D(1600)  # ~1 002 kWh / 235 nap × 365
    assert e.varhato_egyenleg < -20000 and "óta mért" in e.modszer  # a 10 kWh/hó átalány messze kevés
