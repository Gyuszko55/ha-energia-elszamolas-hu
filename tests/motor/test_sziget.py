"""Szigetüzem motor (motor/sziget.py) – Krissz55555 tesztmátrixa (docs/terv/06_SZIGETUZEM.md, 25. pont)."""

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest
from motor.sziget import (
    AKKU_KISUTES,
    AKKU_TOLTES,
    EXPORT,
    FOGYASZTAS,
    HALOZAT,
    PV,
    Minoseg,
    Rendszer,
    honapok,
    idoszakok,
    kwh,
    merleg,
    szamlalo_sorozatbol,
)

T0 = datetime(2026, 10, 1)
T1 = datetime(2026, 11, 1)


def sz(*ertekek, kezd=T0, lepes=timedelta(hours=1), egyseg="kWh", **kw):
    """Óránkénti nyers szenzorsorozat → számláló."""
    s, _ = szamlalo_sorozatbol([(kezd + i * lepes, v) for i, v in enumerate(ertekek)], egyseg, **kw)
    return s


def havi(q, kezdo=1000):
    """Egy hónap: az elején kezdo, a végén kezdo + q (két mért pont)."""
    return sz(kezdo, kezdo + q, lepes=T1 - T0)


def rendszer(**csat):
    return Rendszer({k: (v if isinstance(v, list) else [v]) for k, v in csat.items()})


# --- számlálóhibák ---------------------------------------------------------------------------------------------

def test_nullazodas_nem_ad_negativ_fogyasztast():
    s, esem = szamlalo_sorozatbol([(T0, 12543), (T0 + timedelta(hours=1), 12548), (T0 + timedelta(hours=2), 0),
                                   (T0 + timedelta(hours=3), 3)])
    assert s.fogyasztas(T0, T0 + timedelta(hours=3))[0] == 8  # 5 a reset előtt + 3 utána
    assert [e.tipus for e in esem] == ["nullazodas"]


def test_nullazodas_kimaradt_nulla_pont_nelkul():
    # 12548 → 3 (a 0-s pont nem került a statisztikába): a 3 a reset óta mért energia
    s, _ = szamlalo_sorozatbol([(T0, 12548), (T0 + timedelta(hours=1), 3)])
    assert s.fogyasztas(T0, T0 + timedelta(hours=1))[0] == 3


def test_kis_visszaugras_zaj():
    s, esem = szamlalo_sorozatbol([(T0, D("100.0")), (T0 + timedelta(hours=1), D("100.05")),
                                   (T0 + timedelta(hours=2), D("100.02")), (T0 + timedelta(hours=3), D("101.0"))])
    assert s.fogyasztas(T0, T0 + timedelta(hours=3))[0] == D("1.0")
    assert esem[0].tipus == "visszaugras"


def test_tulcsordulas():
    s, esem = szamlalo_sorozatbol([(T0, 65530), (T0 + timedelta(hours=1), 4)], tulcsordulas=D(65535))
    assert s.fogyasztas(T0, T0 + timedelta(hours=1))[0] == 9 and esem[0].tipus == "tulcsordulas"


def test_ismeretlen_es_unavailable_kihagyva():
    s, esem = szamlalo_sorozatbol([(T0, 10), (T0 + timedelta(hours=1), None), (T0 + timedelta(hours=2), "unavailable"),
                                   (T0 + timedelta(hours=3), 14)])
    assert s.fogyasztas(T0, T0 + timedelta(hours=3))[0] == 4 and len(esem) == 2


def test_ha_ujraindulas_es_entitascsere():
    # újraindulás után ugyanott folytatja; entitáscsere: új szenzor 0-ról – egy sorozatként fűzve
    s, esem = szamlalo_sorozatbol([(T0, 500), (T0 + timedelta(hours=1), 502), (T0 + timedelta(hours=2), 502),
                                   (T0 + timedelta(hours=3), 0), (T0 + timedelta(hours=4), 1)])
    assert s.fogyasztas(T0, T0 + timedelta(hours=4))[0] == 3 and esem[0].tipus == "nullazodas"


@pytest.mark.parametrize(("egyseg", "nyers", "vart"), [("Wh", [1000, 3500], D("2.5")), ("MWh", ["1.2", "1.203"], D(3)),
                                                     ("kWh", [5, 7], D(2))])
def test_mertekegyseg_normalizalas(egyseg, nyers, vart):
    assert sz(*nyers, egyseg=egyseg).fogyasztas(T0, T0 + timedelta(hours=1))[0] == vart


def test_nem_energia_mertekegyseg_hiba():
    with pytest.raises(ValueError):
        kwh(5, "W")


def test_kezi_kezdoallas():
    s, _ = szamlalo_sorozatbol([(T0 + timedelta(hours=2), 107)], kezdo=(T0, D(100)))
    assert s.fogyasztas(T0, T0 + timedelta(hours=2))[0] == 7


# --- mérleg --------------------------------------------------------------------------------------------------------

def test_csak_pv_es_fogyasztas():
    r = merleg(rendszer(fogyasztas=havi(300), pv=havi(320)), T0, T1)
    assert (r.fogyasztas, r.ertekek[PV], r.onellatottsag, r.minoseg) == (300, 320, 1, Minoseg.COMPLETE)
    assert r.merleg_elteres == 20  # PV − fogyasztás: veszteség / mérési pont / visszaszabályozás nélküli többlet


def test_pv_akku_fogyasztas_utvonal_nem_becsult():
    # Krissz 26. pontja: PV 20, Load 15, töltés 8, kisütés 4 – a PV→ház / PV→akku megosztás nem határozható meg
    r = merleg(rendszer(fogyasztas=havi(15), pv=havi(20), akku_toltes=havi(8), akku_kisutes=havi(4)), T0, T1)
    assert r.utvonalak == {} and r.akku_netto == 4
    assert r.merleg_be == 24 and r.merleg_ki == 23 and r.merleg_elteres == 1
    assert any("nem határozható meg" in m for m in r.megjegyzesek)


def test_halozati_backup_onellatottsag():
    # Krissz 8. pontja: 382,6 kWh fogyasztás, 21,8 hálózat, 4,3 generátor → saját 356,5
    r = merleg(rendszer(fogyasztas=havi(D("382.6")), pv=havi(D("417.3")), halozat=havi(D("21.8")), generator=havi(D("4.3"))), T0, T1)
    assert r.kulso == D("26.1") and r.sajat == D("356.5")
    assert round(r.onellatottsag * 100, 1) == D("93.2") and round(r.halozati_reszarany * 100, 1) == D("5.7")


def test_halozat_akku_kulon_merve():
    r = merleg(rendszer(fogyasztas=havi(200), halozat=havi(50), halozat_akku=havi(30), akku_toltes=havi(80),
                        akku_kisutes=havi(70), pv=havi(160)), T0, T1)
    assert r.utvonalak == {"halozat_akku": 30, "halozat_fogyasztas": 20}


def test_bypass_halozat_fogyasztas():
    # Grid → Load bypass: normál hálózati vételezés, nem megy át az akkun
    r = merleg(rendszer(fogyasztas=havi(100), halozat=havi(100), akku_toltes=havi(0), akku_kisutes=havi(0)), T0, T1)
    assert r.onellatottsag == 0 and r.halozati_reszarany == 1 and r.akku_netto == 0


def test_generator():
    r = merleg(rendszer(fogyasztas=havi(100), pv=havi(60), generator=havi(40)), T0, T1)
    assert r.generator_reszarany == D("0.4") and r.onellatottsag == D("0.6")


def test_tobb_akku_es_tobb_pv_osszeadva():
    r = merleg(rendszer(fogyasztas=havi(300), pv=[havi(200), havi(150, 50)], akku_toltes=[havi(40), havi(30)],
                        akku_kisutes=[havi(35), havi(25)]), T0, T1)
    assert (r.ertekek[PV], r.ertekek[AKKU_TOLTES], r.ertekek[AKKU_KISUTES]) == (350, 70, 60)


def test_nincs_pv_szenzor():
    r = merleg(rendszer(fogyasztas=havi(100), halozat=havi(10)), T0, T1)
    assert r.onellatottsag == D("0.9") and PV not in r.ertekek and r.minoseg == Minoseg.COMPLETE


def test_nincs_akku_szenzor_nincs_akku_netto():
    r = merleg(rendszer(fogyasztas=havi(100), pv=havi(120)), T0, T1)
    assert r.akku_netto is None


def test_nincs_halozat_teljes_onellatas():
    r = merleg(rendszer(fogyasztas=havi(100), pv=havi(90), akku_kisutes=havi(20), akku_toltes=havi(10)), T0, T1)
    assert r.onellatottsag == 1 and r.halozati_reszarany is None and r.kulso == 0


def test_akku_tele_es_ures():
    tele = merleg(rendszer(fogyasztas=havi(10), pv=havi(10), akku_toltes=havi(0), akku_kisutes=havi(0)), T0, T1)
    ures = merleg(rendszer(fogyasztas=havi(10), halozat=havi(10), akku_toltes=havi(0), akku_kisutes=havi(0)), T0, T1)
    assert tele.onellatottsag == 1 and ures.onellatottsag == 0


def test_hianyzo_opcionalis_csatorna_partial():
    ures_pv = Rendszer({FOGYASZTAS: [havi(100)], HALOZAT: [havi(10)], PV: [sz(1, kezd=T1 + timedelta(days=5))]})
    r = merleg(ures_pv, T0, T1)
    assert r.minoseg == Minoseg.PARTIAL and r.ertekek[PV] is None
    assert r.onellatottsag == D("0.9")  # PV nélkül is számolható
    assert r.merleg_be is None  # a mérleg viszont nem


def test_nincs_fogyasztas_insufficient():
    r = merleg(rendszer(pv=havi(100)), T0, T1)
    assert r.minoseg == Minoseg.INSUFFICIENT_DATA and r.onellatottsag is None


def test_becsult_hezag_estimated():
    s = sz(0, 100, lepes=timedelta(days=10))
    r = merleg(rendszer(fogyasztas=s), T0, T0 + timedelta(days=5))
    assert r.minoseg == Minoseg.ESTIMATED and FOGYASZTAS in r.becsult


def test_kovetes_kesobb_indul():
    s = sz(0, 50, kezd=T0 + timedelta(days=10), lepes=timedelta(days=5))
    r = merleg(rendszer(fogyasztas=s), T0, T1)
    assert r.kezdet == T0 + timedelta(days=10) and r.fogyasztas == 50
    assert "követése" in r.megjegyzesek[0]


def test_halozati_akkutoltes_tobb_mint_fogyasztas():
    r = merleg(rendszer(fogyasztas=havi(50), halozat=havi(80), akku_toltes=havi(60), akku_kisutes=havi(20)), T0, T1)
    assert r.onellatottsag == 0 and any("hálózatról töltött akku" in m for m in r.megjegyzesek)


def test_export_akku_nelkul_pv_helyben():
    r = merleg(rendszer(fogyasztas=havi(100), pv=havi(150), export=havi(70), halozat=havi(20)), T0, T1)
    assert r.utvonalak == {"pv_helyben": 80} and r.merleg_ki == 170 and r.ertekek[EXPORT] == 70


def test_hiányos_energiamerleg_elteres():
    r = merleg(rendszer(fogyasztas=havi(100), pv=havi(130), akku_toltes=havi(40), akku_kisutes=havi(30)), T0, T1)
    assert r.merleg_elteres == 20  # 160 be − 140 ki: veszteség / mérési pont / tárolt energia változása


# --- időszakok -----------------------------------------------------------------------------------------------------

def test_idoszakok_honap_es_evvaltas():
    p = idoszakok(datetime(2027, 1, 1, 8, 30), elso=datetime(2025, 3, 1))
    assert p["tegnap"] == (datetime(2026, 12, 31), datetime(2027, 1, 1))
    assert p["elozo_honap"] == (datetime(2026, 12, 1), datetime(2027, 1, 1))
    assert p["elozo_ev"] == (datetime(2026, 1, 1), datetime(2027, 1, 1))
    assert p["honap"][0] == datetime(2027, 1, 1) and p["osszesen"][0] == datetime(2025, 3, 1)


def test_havi_bontas_honapvaltaskor():
    s = sz(*[i * 10 for i in range(62)], kezd=datetime(2026, 9, 30), lepes=timedelta(days=1))
    h = honapok(datetime(2026, 9, 30).date(), datetime(2026, 11, 30).date())
    vals = [merleg(rendszer(fogyasztas=s), a, b).fogyasztas for a, b in h]
    assert vals == [10, 310, 290]


def test_regresszios_nap_mentett_szamlalokbol():
    # Valós inverteres nap mintájára: a nap eleji és végi kumulatív állások (kWh) → ugyanaz a mérleg
    nap0, nap1 = datetime(2026, 7, 15), datetime(2026, 7, 16)
    allas = {FOGYASZTAS: (8123.4, 8141.9), PV: (10234.1, 10262.3), AKKU_TOLTES: (3410.2, 3422.0),
             AKKU_KISUTES: (3301.7, 3309.9), HALOZAT: (512.0, 512.0)}
    r = merleg(Rendszer({k: [sz(a, b, kezd=nap0, lepes=nap1 - nap0)] for k, (a, b) in allas.items()}), nap0, nap1)
    assert r.fogyasztas == D("18.5") and r.ertekek[PV] == D("28.2") and r.onellatottsag == 1
    assert r.merleg_elteres == D("28.2") + D("8.2") - D("18.5") - D("11.8")


# --- javítások (regresszió) ----------------------------------------------------------------------------------------

def napi(q_nap, kezd=T0, napok=31, kezdo=1000):
    """Napi pontok: kezdo-ról napi q_nap kWh-val, kezd-től napok napig (a végén ig-ig)."""
    return sz(*[kezdo + q_nap * i for i in range(napok + 1)], kezd=kezd, lepes=timedelta(days=1))


def test_kesobb_indulo_halozati_mero_kozos_ablak():
    # 400 kWh fogyasztás és 250 kWh PV egy hónapra, a hálózati mérő csak okt. 26-tól: eddig 30 kWh hálózat a teljes
    # havi fogyasztással szemben → 92,5% önellátottság, COMPLETE. Most mindenki okt. 26-tól számol.
    okt26 = datetime(2026, 10, 26)
    r = merleg(rendszer(fogyasztas=napi(D(400) / 31), pv=napi(D(250) / 31), halozat=napi(5, kezd=okt26, napok=6)), T0, T1)
    assert r.kezdet == okt26 and r.minoseg == Minoseg.PARTIAL
    assert round(r.fogyasztas, 6) == round(D(400) / 31 * 6, 6) and r.ertekek[HALOZAT] == 30
    assert round(r.onellatottsag * 100, 1) == D("61.3")  # 1 − 30 / 77,4
    assert any("2026-10-26 00:00-tól indul" in m for m in r.megjegyzesek)


def test_azonos_kezdet_complete_marad():
    r = merleg(rendszer(fogyasztas=napi(10), pv=napi(8), halozat=napi(2)), T0, T1)
    assert r.kezdet is None and r.minoseg == Minoseg.COMPLETE and r.fogyasztas == 310


def test_negativ_nyers_allas_ismeretlen():
    s, esem = szamlalo_sorozatbol([(T0, 10), (T0 + timedelta(hours=1), -5), (T0 + timedelta(hours=2), 12)])
    assert [e.tipus for e in esem] == ["ismeretlen"]
    assert s.fogyasztas(T0, T0 + timedelta(hours=2))[0] == 2  # nem nullázódás, nem +12
    with pytest.raises(ValueError):
        kwh(-1)


def test_halozat_akku_tobb_mint_halozat_ellentmondas():
    r = merleg(rendszer(fogyasztas=havi(200), halozat=havi(30), halozat_akku=havi(50), akku_toltes=havi(80),
                        akku_kisutes=havi(70), pv=havi(160)), T0, T1)
    assert "halozat_akku" not in r.utvonalak and "halozat_fogyasztas" not in r.utvonalak
    assert r.minoseg == Minoseg.INCONSISTENT
    assert any("Ellentmondásos mérés" in m and "50,0 kWh" in m for m in r.megjegyzesek)
