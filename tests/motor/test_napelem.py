"""Napelemes (HMKE) elszámolás: bruttó és szaldó."""

import dataclasses
from datetime import date, datetime
from decimal import Decimal as D

from motor.dijszabas import DijszabasTar
from motor.napelem import brutto, szaldo
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu

from tests.conftest import DIJSZABASOK

TAR = DijszabasTar.mappabol(DIJSZABASOK)


def _fiok(szolg="mvm_demasz"):
    return Fiok(Kozmu.VILLANY, szolg, [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))],
                [Csatorna(szerep="vetelezes"), Csatorna(szerep="betaplalas", keret_aktiv=False)])


def _sz(tol, ig, q):
    return Szamlalo([Pont(datetime(*tol), D(0), True), Pont(datetime(*ig), D(q), True)])


def test_brutto_honap():
    # június: 150 kWh vételezés (keret alatt), 400 kWh betáplálás 5,25 Ft-on
    r = brutto(_fiok(), TAR, date(2026, 6, 1), date(2026, 7, 1), _sz((2026, 6, 1), (2026, 7, 1), 150), _sz((2026, 6, 1), (2026, 7, 1), 400))
    assert r.energia_ft == ((round(D(150) * D("5.25")) + round(D(150) * D("23.4"))) * D("1.27")).quantize(D(1))
    assert r.jovairas_ft == D("2100.00")
    assert r.egyenleg_ft == (r.energia_ft + r.alapdij_ft - D(2100)).quantize(D(1))


def test_brutto_elosztonkent_mas_ar():
    r = brutto(_fiok("eon"), TAR, date(2026, 6, 1), date(2026, 7, 1), _sz((2026, 6, 1), (2026, 7, 1), 0), _sz((2026, 6, 1), (2026, 7, 1), 100))
    assert r.jovairas_ft == D("439.00")


def test_szaldo_vetelezesi_tobblet():
    # egy év: 4 000 kWh vételezés, 3 000 kWh betáplálás → 1 000 kWh nettó, a 2 523-as kereten belül
    ev = ((2025, 7, 1), (2026, 7, 1))
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), _sz(*ev, 4000), _sz(*ev, 3000))
    assert (r.elszamolt_vetelezes, r.tobblet, r.jovairas_ft) == (D(1000), D(0), D(0))
    assert r.energia_ft == ((round(D(1000) * D("5.25")) + round(D(1000) * D("23.4"))) * D("1.27")).quantize(D(1))
    assert r.alapdij_ft == (D(121) * D("1.27") * 12).quantize(D("0.01"))  # 12 hónap alapdíj


def test_szaldo_betaplalasi_tobblet():
    ev = ((2025, 7, 1), (2026, 7, 1))
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), _sz(*ev, 3000), _sz(*ev, 3500))
    assert (r.elszamolt_vetelezes, r.tobblet, r.energia_ft) == (D(0), D(500), D(0))
    assert r.jovairas_ft == D("500.00")  # 1 Ft/kWh (ellenőrizendő)
    assert r.egyenleg_ft == (r.alapdij_ft - D(500)).quantize(D(1))


def test_szaldo_ev_kozben_aranyos_keret():
    # fél év után 2 000 kWh nettó: a keret az eltelt napokkal arányos (~1 260), a felette lévő piaci áron
    vetel = Szamlalo([Pont(datetime(2025, 7, 1), D(0), True), Pont(datetime(2026, 1, 1), D(2500), True)])
    betap = Szamlalo([Pont(datetime(2025, 7, 1), D(0), True), Pont(datetime(2026, 1, 1), D(500), True)])
    r = szaldo(_fiok(), TAR, date(2025, 7, 1), date(2026, 7, 1), vetel, betap, meres_vege=datetime(2026, 1, 1))
    assert r.elszamolt_vetelezes == D(2000)
    assert r.alapdij_ft == (D(121) * D("1.27") * 6).quantize(D("0.01"))  # júl.–dec.: 6 megkezdett hónap


# --- Szaldó az éves egyenlegben és a „ha ma lenne” elszámolásban (a „Minta otthon” adataival)

from itertools import accumulate

from motor.egyenleg import eves_egyenleg, varhato_elszamolas

VET = [230, 290, 340, 350, 300, 250, 190, 150, 160, 180, 170, 180]  # 2025-10 … 2026-09
BET = [170, 80, 40, 50, 100, 190, 270, 320, 340, 350, 310, 220]


def _havi(lista, kezdo=0):
    napok = [datetime(2025 + (9 + i) // 12, (9 + i) % 12 + 1, 1) for i in range(13)]
    return Szamlalo([Pont(n, D(kezdo + q), True) for n, q in zip(napok, accumulate(lista, initial=0), strict=True)])


def _szaldo_fiok(bazis):
    # Az élő fióknak egy (vételezési) csatornája van; a betáplálás külön számláló (modell.betaplalas_csatorna).
    f = _fiok()
    return dataclasses.replace(f, csatornak=f.csatornak[:1], eves_bazis=bazis, reszszamlas=True)


def test_szaldo_elozo_ev_es_varhato():
    # Okt. 6-án: az előző év (2025-10-01 → 2026-10-01) nettó 350 kWh, kereten belül → ~14 579 Ft, nem a bruttó 112 ezer
    vet = Szamlalo([*_havi(VET).pontok, Pont(datetime(2026, 10, 5), D(sum(VET) + 38), True)])
    bet = Szamlalo([*_havi(BET).pontok, Pont(datetime(2026, 10, 5), D(sum(BET) + 27), True)])
    f = _szaldo_fiok(date(2026, 10, 1))
    reszek: list = []
    e = eves_egyenleg(f, TAR, vet, datetime(2026, 10, 6), reszek, elozo_bazis=date(2025, 10, 1), reszszamla_osszeg=D(2337),
                      betaplalas=bet)
    helyes = ((round(D(350) * D("5.25")) + round(D(350) * D("23.4")) + 12 * 121) * D("1.27")).quantize(D(1))
    assert abs(e.elozo_ev["szamitott"] - helyes) <= 2
    # a várható éves is szaldós: a tavalyi betáplálással előrejelezve ~ a tavalyi nettó díj körül
    assert abs(e.varhato_eves - helyes) < 2500
    brutto_e = eves_egyenleg(f, TAR, vet, datetime(2026, 10, 6), reszek, elozo_bazis=date(2025, 10, 1), reszszamla_osszeg=D(2337))
    assert brutto_e.varhato_eves > 100000  # betáplálás nélkül a bruttó vételezés díja


def test_szaldo_tobblet_varhato_jovairas():
    # több betáplálás, mint vételezés: csak az alapdíj, mínusz a többlet jóváírása
    vet, bet = _havi(VET), _havi([x * 2 for x in BET])
    f = _szaldo_fiok(date(2025, 10, 1))
    e = eves_egyenleg(f, TAR, vet, datetime(2026, 9, 30, 12), [], betaplalas=bet)
    tobblet = 2 * sum(BET) - sum(VET)
    alap12 = (D(121) * D("1.27") * 12).quantize(D(1))
    assert abs(e.varhato_eves - (alap12 - tobblet)) <= 5


def test_szaldo_ha_ma_lenne():
    vet, bet = _havi(VET), _havi(BET)
    f = _szaldo_fiok(date(2025, 10, 1))
    v = varhato_elszamolas(f, TAR, vet, datetime(2026, 10, 1), date(2025, 10, 1), [(date(2025, 11, 10), D(2337))], betaplalas=bet)
    b = varhato_elszamolas(f, TAR, vet, datetime(2026, 10, 1), date(2025, 10, 1), [(date(2025, 11, 10), D(2337))])
    assert v.tenyleges < D(16000) < D(100000) < b.tenyleges


def test_idoszak_betaplalas_tavalyi_napokbol():
    # Okt. 5-én: eddig 27 kWh; a hátralévő okt. 5. – nov. 7. a tavalyi ugyanazon napok betáplálása szerint
    from motor.napelem import idoszak_betaplalas

    bet = Szamlalo([*_havi(BET).pontok, Pont(datetime(2026, 10, 5), D(sum(BET) + 27), True)])
    r = idoszak_betaplalas(bet, date(2026, 10, 1), date(2026, 11, 7), datetime(2026, 10, 5))
    assert r["eddig"] == 27
    # tavaly okt. 5. – nov. 7.: okt. 170 kWh-jának 27/31-e + nov. 80 kWh 6/30-a ≈ 164
    assert 155 < r["varhato"] - 27 < 175


def test_idoszak_betaplalas_profillal_ha_nincs_tavalyi():
    from motor.napelem import idoszak_betaplalas

    bet = Szamlalo([Pont(datetime(2026, 6, 1), D(0), True), Pont(datetime(2026, 6, 11), D(100), True)])
    r = idoszak_betaplalas(bet, date(2026, 6, 1), date(2026, 7, 1), datetime(2026, 6, 11))
    assert r["eddig"] == 100 and abs(r["varhato"] - 300) < 1  # egy hónapon belül a profil egyenletes
