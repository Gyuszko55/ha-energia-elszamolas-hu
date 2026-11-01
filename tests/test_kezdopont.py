"""Automatikus kezdőpont: megadott → HA-statisztika → mostani érték; szinkron üres mezővel."""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from modell import kezdopont, mero_szinkron
from motor.szamlalo import Szamlalo
from motor.tipusok import Csatorna, Mero

MA = date(2026, 10, 2)
CEL = date(2026, 10, 1)
SZENZOR = {"forras_entitas": "sensor.meroora"}


def test_megadott_kezdoallas_nyer():
    assert kezdopont({**SZENZOR, "kezdo_allas": 1234, "beepitve": "2026-09-15"}, CEL, D(9999), D(9999), MA) == (
        date(2026, 9, 15), D(1234), "megadott")


def test_statisztika_a_mostani_ertek_elott():
    assert kezdopont(SZENZOR, CEL, D(20500), D(20631), MA) == (CEL, D(20500), "statisztika")


def test_csak_mostani_ertek_ma_indul():
    assert kezdopont(SZENZOR, CEL, None, D(20631), MA) == (MA, D(20631), "aktualis")


def test_szenzor_meg_nincs_kesz():
    assert kezdopont(SZENZOR, CEL, None, None, MA) is None


def test_szenzor_nelkul_regi_viselkedes():
    assert kezdopont({"beepitve": "2026-09-01"}, CEL, None, None, MA) == (date(2026, 9, 1), D(0), "nincs_forras")


def test_szinkron_ures_mezo_nem_ir_felul_es_kiurites_ujraindit():
    tarolt = {"merok": [{"beepitve": "2026-10-01", "kezdo_allas": "20500", "gyari_szam": ""}]}
    mero_szinkron(tarolt, SZENZOR)  # első futás: csak feljegyzi
    assert tarolt["merok"][0]["kezdo_allas"] == "20500" and "kezdes_ujra" not in tarolt
    tarolt2 = {"merok": [{"beepitve": "2026-09-01", "kezdo_allas": "100", "gyari_szam": ""}]}
    mero_szinkron(tarolt2, {**SZENZOR, "beepitve": "2026-09-01", "kezdo_allas": 100})
    mero_szinkron(tarolt2, SZENZOR)  # a felhasználó kiürítette a kezdőnapot és -állást
    assert tarolt2["merok"][0]["kezdo_allas"] == "100" and tarolt2.get("kezdes_ujra") is True


def test_szinkron_ujjlenyomat_valtozatlan_kitoltott_mezokkel():
    # A meglévő fiókok tárolt ujjlenyomata (str(x or 0)) nem változhat, különben a mérőadatok felülíródnának.
    tarolt = {"merok": [{"beepitve": "2025-10-01", "kezdo_allas": "16218.0", "gyari_szam": ""}],
              "mero_beallitas": {"beepitve": "2025-10-01", "kezdo_allas": "16218.0", "gyari_szam": ""}}
    assert mero_szinkron(tarolt, {"beepitve": "2025-10-01", "kezdo_allas": 16218.0}) is False


def test_szamlalo_forras_kesobb_indulo_elozmennyel():
    # Ma felvett fiók, a szenzornak csak a mostani értéke van: onnan számol (eddig minden pontot eldobott).
    cs = Csatorna(merok=[Mero("", MA, D(5600))])
    t0 = datetime(2026, 10, 2, 14)
    sz = Szamlalo.csatornabol(cs, [(t0, D(5600)), (t0 + timedelta(hours=6), D(5605))], meroallas=False)
    assert sz.fogyasztas(datetime(2026, 10, 2), t0 + timedelta(hours=6))[0] == D(5)


def test_eves_napok_evkozi_leolvasast_kihagyja():
    """Évkezdet csak az éves leolvasás: a ~10 hónapon belüli jelölt (pl. sztornós végszámla) állás nem."""
    from modell import eves_bazis, elszamolasi_napok
    t = {"merok": [{"beepitve": "2021-10-02", "leolvasasok": [
        {"datum": x, "allas": "1", "elszamolasi": True} for x in ("2024-10-01", "2025-10-01", "2026-02-02", "2026-09-29")]}]}
    assert eves_bazis(t).isoformat() == "2026-09-29"
    assert sorted(x.isoformat() for x in elszamolasi_napok(t)) == ["2024-10-01", "2025-10-01", "2026-09-29"]


def test_kezdo_ora_allas_az_elszamolas_origoja():
    from modell import eves_bazis, kezdo_origo_szinkron

    tarolt = {"merok": [{"gyari_szam": "X", "beepitve": "2026-08-01", "kezdo_allas": "20996", "leolvasasok": [
        {"datum": "2025-08-03", "allas": "19000", "elszamolasi": True}]}]}
    # megadott kezdőállás → origó, későbbi a korábbi éves leolvasásnál
    assert kezdo_origo_szinkron(tarolt, {"beepitve": "2026-08-01", "kezdo_allas": 20996})
    assert tarolt["kezdo_origo"] == {"datum": "2026-08-01", "allas": "20996"}
    assert eves_bazis(tarolt) == date(2026, 8, 1)
    assert not kezdo_origo_szinkron(tarolt, {"beepitve": "2026-08-01", "kezdo_allas": 20996})
    # egy későbbi éves leolvasás átveszi a helyét
    tarolt["merok"][0]["leolvasasok"].append({"datum": "2027-07-30", "allas": "24000", "elszamolasi": True})
    assert eves_bazis(tarolt) == date(2027, 7, 30)
    # kiürített (automatikus) kezdőállás nem origó
    assert kezdo_origo_szinkron(tarolt, {"beepitve": "2026-08-01", "kezdo_allas": None})
    assert "kezdo_origo" not in tarolt


def test_kezdonap_modositas_lezart_ujraszamolast_ker():
    tarolt = {"merok": [{"gyari_szam": "", "beepitve": "2026-09-01", "kezdo_allas": "0", "leolvasasok": []}],
              "mero_beallitas": {"beepitve": "2026-09-01", "kezdo_allas": "0", "gyari_szam": ""}}
    assert mero_szinkron(tarolt, {"beepitve": "2026-08-01", "kezdo_allas": 0})
    assert tarolt["lezart_ujra"] == "2026-08-01"


def test_kenyszeritett_evkezdet():
    """Végszámla után az MVM új évet kezd: az „evkezdet” jelölésű leolvasás a 10 hónapos szabálytól függetlenül évkezdet."""
    from modell import _eves_napok
    lo = lambda nap, **x: {"datum": nap, "allas": "1", **x}  # noqa: E731
    t = {"merok": [{"beepitve": "2021-01-01", "leolvasasok": [
        lo("2025-10-01", elszamolasi=True), lo("2026-02-02", elszamolasi=True, evkezdet=True), lo("2026-09-29", elszamolasi=True)]}]}
    assert _eves_napok(t) == [date(2025, 10, 1), date(2026, 2, 2), date(2026, 9, 29)]
    t["merok"][0]["leolvasasok"][1].pop("evkezdet")
    assert _eves_napok(t) == [date(2025, 10, 1), date(2026, 9, 29)]


def test_kezdo_origo_mindig_evkezdet():
    """A mérő felszerelése (kezdő óraállás) mindig évkezdet, akkor is, ha 10 hónapon belül éves leolvasás követi."""
    from modell import _eves_napok
    t = {"kezdo_origo": {"datum": "2026-02-03", "allas": "0"},
         "merok": [{"beepitve": "2026-02-03", "leolvasasok": [{"datum": "2026-09-29", "allas": "1002", "elszamolasi": True}]}]}
    assert _eves_napok(t) == [date(2026, 2, 3), date(2026, 9, 29)]


def test_elszamolasi_ev_legfeljebb_12_honap():
    """Az elszámolási év legfeljebb 12 hónap + tűrés: a csúszó leolvasás (okt. 1. → szept. 29.) egy év marad, a kimaradt
    éves leolvasás helyén az évfordulón virtuális évhatár."""
    from modell import _eves_napok
    lo = lambda nap: {"datum": nap, "allas": "1", "elszamolasi": True}  # noqa: E731
    t = {"merok": [{"beepitve": "2021-01-01", "leolvasasok": [lo("2023-10-01"), lo("2024-09-29"), lo("2026-10-02")]}]}
    n = _eves_napok(t)
    assert n[:3] == [date(2023, 10, 1), date(2024, 9, 29), date(2025, 9, 29)]  # 2025-ben kimaradt → virtuális
    assert date(2026, 10, 2) in n


def test_honapvege_csak_sajat_allasra():
    """A hónap utolsó napjára rögzített SAJÁT állás a nap vége (+1 nap); a számlából átvett állás a számla napjára szól."""
    from modell import mero_motorba
    m = {"beepitve": "2026-01-01", "kezdo_allas": "0", "leolvasasok": [
        {"datum": "2026-05-31", "allas": "793", "tipus": "kezi", "megjegyzes": "számla 90001LHE26 (Leol)"},
        {"datum": "2026-04-30", "allas": "790", "tipus": "kezi", "megjegyzes": "DAKÖV-számlából"},
        {"datum": "2026-06-30", "allas": "800", "tipus": "kezi", "megjegyzes": "diktált"}]}
    napok = [lo.datum for lo in mero_motorba(m, honapvege=True).leolvasasok]
    assert napok == [date(2026, 5, 31), date(2026, 4, 30), date(2026, 7, 1)]


def test_mellekregiszter_kezdoallasa_a_legkorabbi_leolvasas():
    # Napelemes A1: a betáplálás (2.8.0) kezdőállása nincs megadva – a beépítés napi 9 870-es állás a kezdőpont,
    # nem 0 (különben az éves betáplálás 12 310 kWh lenne 2 440 helyett).
    from modell import betaplalas_csatorna

    m = {"gyari_szam": "X", "beepitve": "2025-10-01", "kezdo_allas": "21450", "leolvasasok": [
        {"datum": "2025-10-01", "allas": "21450", "csatorna": "vetelezes"},
        {"datum": "2025-10-01", "allas": "9870", "csatorna": "betaplalas", "tipus": "szolgaltatoi"},
        {"datum": "2026-10-01", "allas": "12310", "csatorna": "betaplalas", "tipus": "szolgaltatoi"},
    ]}
    b = Szamlalo.csatornabol(betaplalas_csatorna({"merok": [m]}), None, 1, meroallas=True)
    assert b.fogyasztas(datetime(2025, 10, 1), datetime(2026, 10, 1))[0] == 2440
