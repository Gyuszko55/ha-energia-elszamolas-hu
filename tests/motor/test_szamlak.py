"""Számlatesztek: valódi, anonimizált MVM Next számlák. A motornak a számla végösszegét kell kihoznia.

Csak mennyiségek, dátumok és összegek – név, cím, azonosító nincs benne.
"""

from datetime import date, datetime
from decimal import Decimal as D

from tests.conftest import DIJSZABASOK
from motor.dijszabas import DijszabasTar
from motor.elszamolas import szamol
from motor.szamlalo import Pont, Szamlalo
from motor.tipusok import Csatorna, DijszabasHozzarendeles, Fiok, Kozmu, Leolvasas, Mero

TAR = DijszabasTar.mappabol(DIJSZABASOK)


def test_villany_a1_reszszamla_2026_06():
    """Villany 2. részszámla, 2026.05.14–06.08 (26 nap), 19 120 → 19 413 kWh (293 kWh).

    Számla: 180 kWh kedvezményes + 113 kWh piaci; energiadíj + rendszerhasználati díj bruttó 5 763 + 8 707,
    elosztói alapdíj 154 (1 db), végösszeg 14 624 Ft. Rezsicsökkentés nélkül: 20 693 Ft.
    """
    fiok = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()])
    tol, ig = date(2026, 5, 14), date(2026, 6, 9)
    s = Szamlalo([Pont(datetime(2026, 5, 14), D(19120), True), Pont(datetime(2026, 6, 9), D(19413), True)])
    r = szamol(fiok, TAR, tol, ig, [s])
    sz = r.szeletek[0]
    assert (sz.keret, sz.kedvezmenyes, sz.piaci) == (D(180), D(180), D(113))
    assert r.osszesen_ft == D(14624)
    assert (r.energia_ft, r.alapdij_ft) == (D(14470), D(154))  # (945 + 3 593 + 6 856) × 1,27; 121 × 1,27
    # Ellenpróba a számla „rezsicsökkentett díj nélkül” sorával (minden kWh piaci áron); a szolgáltató
    # kerekítési módját itt nem ismerjük, ezért ±1 Ft.
    assert abs((D(293) * D("70.104") + D("153.035")).quantize(D(1)) - D(20693)) <= 1


def test_gaz_reszszamla_2026_08():
    """Gáz 1. részszámla, 2026.07.15–08.13, 103 m³ (58 + 45), korrekció 1,0, fűtőérték 34,61 MJ/m³.

    Számla: 2 007 + 1 557 MJ × 2,256 Ft/MJ nettó (4 528 + 3 513), alapdíj 766 nettó, ÁFA 27% → 11 185 Ft.
    A részszámla mennyisége itt becsült (a gázóra ennyit nem mért), a teszt a számla mennyiségét veszi át.
    """
    fiok = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/lakossagi", date(2024, 1, 1))], [Csatorna()],
                eves_bazis=date(2026, 7, 14), futoertekek={"2026-07": D("34.61"), "2026-08": D("34.61")}, reszszamlas=True)
    s = Szamlalo([Pont(datetime(2026, 7, 14), D(8668), True), Pont(datetime(2026, 7, 15), D(8668), True),
                  Pont(datetime(2026, 8, 1), D(8726), True), Pont(datetime(2026, 8, 14), D(8771), True)])
    r = szamol(fiok, TAR, date(2026, 7, 15), date(2026, 8, 14), [s])
    assert [sz.elszamolt for sz in r.szeletek] == [D(2007), D(1557)]
    assert all(sz.piaci == 0 and not sz.becsult for sz in r.szeletek)
    assert r.energia_ft == D(10212) and r.alapdij_ft == D(973)
    assert r.osszesen_ft == D(11185)


def _viz_fiok(levonas: bool):
    return Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
                [Csatorna(szerep="fo"), Csatorna(szerep="almero", csatornadij_aktiv=False, levonas_fobol=levonas)])


def _alapdij(honap: int) -> D:
    """A DAKÖV-számla alapdíj-tételei: 2 × 177,21 Ft/hó nettó × hónapok, fillérre (a számla saját ütemezése szerint)."""
    return (D("354.42") * honap * D("1.27")).quantize(D("0.01"))


def test_viz_dakov_2026_03():
    """DAKÖV víz 1. részszámla, 2026.01.24–03.02 (becsült): fővízmérő 741 → 749 (8 m³), locsolási mérő 89 → 92 (3 m³).

    Ezen a számlán még nincs almérő-levonás: ivóvíz 11 m³, csatorna 8 m³, alapdíj 1 hónap → 8 013 Ft.
    """
    tol, ig = date(2026, 1, 24), date(2026, 3, 3)
    fo = Szamlalo([Pont(datetime(2026, 1, 24), D(741), True), Pont(datetime(2026, 3, 3), D(749), True)])
    almero = Szamlalo([Pont(datetime(2026, 1, 24), D(89), True), Pont(datetime(2026, 3, 3), D(92), True)])
    r = szamol(_viz_fiok(levonas=False), TAR, tol, ig, [fo, almero])
    energia = sum(s.energia_ft for s in r.szeletek)
    assert sum(s.csatorna_ft for s in r.szeletek) == D("3798.01")
    assert (energia + _alapdij(1)).quantize(D(1)) == D(8013)


def test_viz_dakov_2026_07_almero_levonas_es_merocsere():
    """DAKÖV víz, 2026.05.31–07.15: fővízmérő 793 → 812 (19 m³), aztán mérőcsere (új óra 0-ról),
    locsolási ALMÉRŐ 106 → 117 (11 m³), levonva a főmérő csatornadíjából.

    Számla: ivóvíz 19 m³ (5 120,88 nettó), csatorna 19 − 11 = 8 m³ (7 102,58 − 4 112,02), alapdíj 2 hónap → 11 202 Ft.
    """
    fiok = _viz_fiok(levonas=True)
    fo = Szamlalo.csatornabol(Csatorna(merok=[
        Mero("9000001", date(2020, 1, 1), D(0), kiszerelve=date(2026, 7, 15), zaro_allas=D(812),
             leolvasasok=[Leolvasas(date(2026, 5, 31), D(793))]),
        Mero("100001HB", date(2026, 7, 15), D(0)),
    ]))
    almero = Szamlalo([Pont(datetime(2026, 5, 31), D(106), True), Pont(datetime(2026, 7, 15), D(117), True)])
    r = szamol(fiok, TAR, date(2026, 5, 31), date(2026, 7, 15), [fo, almero])
    fo_sz = [s for s in r.szeletek if s.csatorna == "fo"]
    al_sz = [s for s in r.szeletek if s.csatorna == "almero"]
    assert sum(s.mennyiseg for s in fo_sz) == D(19) and sum(s.mennyiseg for s in al_sz) == D(11)
    assert sum(s.csatorna_ft for s in fo_sz) == D("9020.28")
    assert sum(s.csatorna_ft for s in al_sz) == D("-5222.27")
    energia = sum(s.energia_ft for s in r.szeletek)
    assert (energia + _alapdij(2)).quantize(D(1)) == D(11202)


def _a1(evhatarok=()):
    return Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a1", date(2024, 1, 1))], [Csatorna()],
                elszamolasi_napok=tuple(evhatarok))


def test_aram_ev_kezdete():
    from motor.elszamolas import aram_ev_kezdete
    a1 = lambda n: TAR.felold("villany/a1", n, "mvm_demasz")
    h = lambda n: TAR.felold("villany/h", n, "mvm_demasz")
    assert aram_ev_kezdete(a1(date(2026, 11, 6)), date(2026, 11, 6)) == date(2026, 8, 1)
    assert aram_ev_kezdete(a1(date(2026, 7, 31)), date(2026, 7, 31)) == date(2025, 8, 1)
    assert aram_ev_kezdete(h(date(2026, 11, 6)), date(2026, 11, 6)) == date(2026, 4, 16)  # télen is a tavaszi idénytől
    assert aram_ev_kezdete(h(date(2026, 4, 15)), date(2026, 4, 15)) == date(2025, 4, 16)
    assert aram_ev_kezdete(h(date(2026, 4, 16)), date(2026, 4, 16)) == date(2026, 4, 16)


def test_villany_a1_savkorrekcio_2026_09():
    """Elszámoló számla 2026.08.09–09.09 (32 nap), 20 061 → 20 520 kWh (459 kWh). A kedvezményes év 08.01-jén indult.
    Az MVM az új év első 8 napjára (55 kWh keret) csak 3 kWh-t osztott, így most 52 kWh ki nem használt keret jár: a
    számlán 221 + 52 („sávkorrekció”) kWh kedvezményes, 238 − 52 kWh piaci, bruttó 23 125 Ft (két rendszerhasználati
    sorra bontva, ezért ±3 Ft). Az éves leolvasásnak nincs szerepe: a jóváírás akkor is ennyi, ha nincs ilyen nap."""
    s = Szamlalo([Pont(datetime(2026, 8, 1), D(20028), True), Pont(datetime(2026, 8, 9), D(20031), True),
                  Pont(datetime(2026, 9, 10), D(20490), True)])
    for napok in ([], [date(2025, 10, 1)]):
        sz = szamol(_a1(napok), TAR, date(2026, 8, 9), date(2026, 9, 10), [s])
        assert (sz.szeletek[0].keret, sz.szeletek[0].kedvezmenyes, sz.szeletek[0].piaci, sz.szeletek[0].savkorrekcio) == (D(221), D(273), D(186), D(52))
        assert abs(sz.osszesen_ft - D(23125)) <= 3
    # A valódi mérőállásokkal (08.01–08.08: 33 kWh) 55 − 33 = 22 kWh a korrekció.
    v = Szamlalo([Pont(datetime(2026, 8, 1), D(20028), True), Pont(datetime(2026, 8, 9), D(20061), True),
                  Pont(datetime(2026, 9, 10), D(20520), True)])
    assert szamol(_a1(), TAR, date(2026, 8, 9), date(2026, 9, 10), [v]).szeletek[0].savkorrekcio == D(22)


def test_villany_a1_a_keret_nem_megy_at_aug_1_utan():
    """A júl. 31-én fel nem használt keret elvész, az éves leolvasástól függetlenül (4/2011. NFM rendelet 6. § (3))."""
    s = Szamlalo([Pont(datetime(2026, 7, 1), D(0), True), Pont(datetime(2026, 8, 1), D(10), True), Pont(datetime(2026, 9, 1), D(610), True)])
    sz = szamol(_a1([date(2026, 1, 1)]), TAR, date(2026, 8, 1), date(2026, 9, 1), [s]).szeletek[0]
    assert (sz.keret, sz.kedvezmenyes, sz.piaci, sz.savkorrekcio) == (D(214), D(214), D(386), D(0))


def test_villany_a1_az_eves_leolvasas_nem_nullazza_a_keretet():
    """Az év közbeni (okt. 1-jei) éves leolvasásnál nem nullázódik: a szeptemberi maradék októberben még jár."""
    s = Szamlalo([Pont(datetime(2026, 8, 1), D(0), True), Pont(datetime(2026, 10, 1), D(10), True), Pont(datetime(2026, 11, 1), D(600), True)])
    sz = szamol(_a1([date(2026, 10, 1)]), TAR, date(2026, 10, 1), date(2026, 11, 1), [s]).szeletek[0]
    assert sz.kedvezmenyes == D(590) and sz.piaci == D(0)  # 61 + 31 nap kerete jóval több, mint a fogyasztás


def test_villany_a1_ev_kozben_indult_meres_is_halmoz():
    """Új fiók aug. 1. után: a keret az első adattól, időarányosan halmozódik (nem esik ki a sávkorrekció)."""
    s = Szamlalo([Pont(datetime(2026, 2, 1), D(0), True), Pont(datetime(2026, 3, 1), D(10), True), Pont(datetime(2026, 4, 1), D(310), True)])
    sz = szamol(_a1(), TAR, date(2026, 3, 1), date(2026, 4, 1), [s]).szeletek[0]
    assert sz.kedvezmenyes == D(300) and sz.savkorrekcio > 0


def test_villany_a1_savkorrekcio_visszafele():
    """Évzáró kis fogyasztással (2025.09.10–10.01, 142 kWh): a megmaradt keret a korábban piaci áron számlázott
    fogyasztást sorolja át. A számlán kedvezményes 142 + 11, piaci −11; a halmozott modellben 152 / −10 (az MVM
    számlánként kerekíti a keretet, ezért ±1 kWh)."""
    ev = date(2024, 10, 1)
    s = Szamlalo([Pont(datetime(2024, 10, 1), D(0), True), Pont(datetime(2025, 9, 9), D(3372), True),
                  Pont(datetime(2025, 10, 1), D(3514), True)])
    r = szamol(_a1([ev, date(2025, 10, 1)]), TAR, date(2025, 9, 9), date(2025, 10, 1), [s])
    sz = r.szeletek[0]
    # Halmozott keret 09.09-ig 2371 (343 nap), 10.01-ig 2523 (az egész év): a fogyasztás végig fölötte.
    assert (sz.kedvezmenyes, sz.piaci, sz.savkorrekcio) == (D(152), D(-10), D(10))


def test_villany_b_savkorrekcio():
    """B (vezérelt) mérő: saját 2523 kWh/év keret, az elszámolási évben halmozva, felette piaci ár (60,935 Ft/kWh)."""
    f = Fiok(Kozmu.VILLANY, "mvm_elmu", [DijszabasHozzarendeles("villany/b", date(2024, 1, 1))], [Csatorna()],
             elszamolasi_napok=(date(2025, 1, 1),))
    # Január: 100 kWh (keret 214) → 114 ki nem használt; február: 300 kWh (keret 28 × 6,912 = 194) → mind kedvezményes (+106).
    s = Szamlalo([Pont(datetime(2025, 1, 1), D(0), True), Pont(datetime(2025, 2, 1), D(100), True),
                  Pont(datetime(2025, 3, 1), D(400), True)])
    sz = szamol(f, TAR, date(2025, 2, 1), date(2025, 3, 1), [s]).szeletek[0]
    assert (sz.keret, sz.kedvezmenyes, sz.piaci, sz.savkorrekcio) == (D(194), D(300), D(0), D(106))
    # Márciusban 600 kWh: halmozott keret 59 nap → 408 (+214 = 622), fogyasztás 400 + 600 → 222 kedvezményes, 378 piaci.
    s = Szamlalo(s.pontok + [Pont(datetime(2025, 4, 1), D(1000), True)])
    sz = szamol(f, TAR, date(2025, 3, 1), date(2025, 4, 1), [s]).szeletek[0]
    assert (sz.kedvezmenyes, sz.piaci) == (D(222), D(378))
    assert sz.egysegar_piaci.quantize(D("0.001")) == D("60.935")


def test_villany_h_nyari_savkorrekcio_a_teli_idenyt_kihagyja():
    """H egycsatornás mérő: a keret csak az idényen kívüli (nyári, 1.82) napokra jár és csak azok fogyasztására
    halmozódik; a fűtési idény (10.15–04.15, ápr. 15-ével bezárólag) téli fogyasztása és napjai nem számítanak bele."""
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))], [Csatorna()],
             elszamolasi_napok=(date(2025, 3, 1),))
    # 03.01–04.15 téli: 2000 kWh (nem számít); 04.16–05.14 nyári: 50 kWh; 05.15–06.14: 400 kWh (keret 214).
    s = Szamlalo([Pont(datetime(2025, 3, 1), D(0), True), Pont(datetime(2025, 4, 16), D(2000), True),
                  Pont(datetime(2025, 5, 15), D(2050), True), Pont(datetime(2025, 6, 15), D(2450), True)])
    sz = szamol(f, TAR, date(2025, 5, 15), date(2025, 6, 15), [s]).szeletek[0]
    assert sz.idenyszak == "nyari"
    # Halmozott keret 60 nyári nap (04.16–06.14) → 415; fogyasztás 50 + 400 = 450 → 365 kedvezményes (214 + 151 sávkorrekció).
    assert (sz.keret, sz.kedvezmenyes, sz.piaci, sz.savkorrekcio) == (D(214), D(365), D(35), D(151))


def test_villany_h_nyari_regiszter_savkorrekcio():
    """Kétregiszteres H: a nyári (1.82) regiszter halmozott kerete; a téli regiszter keret nélkül marad."""
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/h", date(2024, 1, 1))],
             [Csatorna(szerep="h_teli", keret_aktiv=False), Csatorna(szerep="h_nyari")],
             elszamolasi_napok=(date(2025, 4, 16),))
    teli = Szamlalo([Pont(datetime(2025, 4, 16), D(0), True), Pont(datetime(2025, 6, 15), D(0), True)])
    nyari = Szamlalo([Pont(datetime(2025, 4, 16), D(0), True), Pont(datetime(2025, 5, 15), D(50), True),
                      Pont(datetime(2025, 6, 15), D(450), True)])
    n = [x for x in szamol(f, TAR, date(2025, 5, 15), date(2025, 6, 15), [teli, nyari]).szeletek if x.csatorna == "h_nyari"]
    assert (n[0].kedvezmenyes, n[0].piaci, n[0].savkorrekcio) == (D(365), D(35), D(151))


def _gaz_dikt(dijszabas="gaz/lakossagi", **kw):
    return Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles(dijszabas, date(2024, 1, 1))], [Csatorna()], **kw)


def _gaz_szamlalo(*pontok):
    """m³-ben; 34,61 MJ/m³ alap fűtőértékkel (becsült)."""
    return Szamlalo([Pont(datetime(*p[0]), D(p[1]), True) for p in pontok])


def test_gaz_diktalas_havi_sulyozott_keret():
    """Diktálásnál a keret havonta súlyozott (MVM táblázat, 2024.08.01-től): egy 14→13-as számla az októberi és a
    novemberi napok részét kapja: 18 × 3 724 / 31 + 13 × 7 490 / 30 = 2 162 + 3 246 MJ."""
    s = _gaz_szamlalo(((2025, 8, 1), 0), ((2025, 10, 14), 0), ((2025, 11, 1), 0), ((2025, 11, 14), 0))
    r = szamol(_gaz_dikt(), TAR, date(2025, 10, 14), date(2025, 11, 14), [s])
    assert [sz.keret for sz in r.szeletek] == [D(2162), D(3246)]
    assert not any(sz.keret_eves for sz in r.szeletek)
    # Január egésze: 12 365 MJ; szökőév februárja is a teljes havi 10 421 MJ.
    s = _gaz_szamlalo(((2027, 8, 1), 0), ((2028, 1, 1), 0), ((2028, 3, 1), 0))
    r = szamol(_gaz_dikt(), TAR, date(2028, 1, 1), date(2028, 3, 1), [s])
    assert [sz.keret for sz in r.szeletek] == [D(12365), D(10421)]


def test_gaz_diktalas_savkorrekcio_kedvezmenyes_evben():
    """A ki nem használt keret a kedvezményes éven (aug. 1. – júl. 31.) belül később jár; az évfordulón nem vihető át."""
    # Augusztusban nincs fogyasztás (565 MJ keret marad), szeptemberben 50 m³ = 1 731 MJ (keret 1 109).
    s = _gaz_szamlalo(((2025, 7, 1), 0), ((2025, 8, 1), 0), ((2025, 9, 1), 0), ((2025, 10, 1), 50))
    sz = szamol(_gaz_dikt(), TAR, date(2025, 9, 1), date(2025, 10, 1), [s]).szeletek[0]
    assert (sz.keret, sz.elszamolt, sz.kedvezmenyes, sz.piaci, sz.savkorrekcio) == (D(1109), D(1731), D(1674), D(57), D(565))
    # Júliusban nem fogyasztott keret (512) az augusztusi számlára már nem jár: új kedvezményes év.
    s = _gaz_szamlalo(((2025, 7, 1), 0), ((2025, 8, 1), 0), ((2025, 9, 1), 30))
    r = szamol(_gaz_dikt(), TAR, date(2025, 7, 1), date(2025, 9, 1), [s])
    aug = r.szeletek[-1]
    assert (aug.tol, aug.keret, aug.kedvezmenyes, aug.savkorrekcio) == (date(2025, 8, 1), D(565), D(565), D(0))


def test_gaz_atalany_eves_keret():
    """Átalánynál (egyenletes részszámla) a keret éves – a panel éves csíkot mutat."""
    s = _gaz_szamlalo(((2025, 7, 14), 0), ((2025, 10, 14), 0), ((2025, 11, 14), 100))
    sz = szamol(_gaz_dikt(eves_bazis=date(2025, 7, 14), reszszamlas=True), TAR, date(2025, 10, 14), date(2025, 11, 14), [s]).szeletek[0]
    assert sz.keret_eves and sz.keret == D(63645) and sz.keret_evi == D(63645)


def test_gaz_b1_alapdij_es_a3_keret():
    """B1 (20 m³/h és afeletti mérő): 1,943 Ft/MJ, alapdíj 14 633 Ft/(m³/h)/év × a mérő teljesítménye.
    A3 (fogyasztói közösség): 2,373 Ft/MJ, a keret társasháznál (lakásszám + 1)-szerese."""
    s = _gaz_szamlalo(((2025, 8, 1), 0), ((2026, 1, 1), 0), ((2026, 2, 1), 0))
    b1 = szamol(_gaz_dikt("gaz/lakossagi_b1", szorzok={"gazmero_teljesitmeny": D(25)}), TAR, date(2026, 1, 1), date(2026, 2, 1), [s])
    assert b1.alapdij_ft == D(38716)  # 14 633 / 12 × 25 = 30 485 Ft nettó/hó, × 1,27
    assert b1.szeletek[0].egysegar_kedvezmenyes == D("1.943") * D("1.27")
    a3 = szamol(_gaz_dikt("gaz/fogyasztoi_kozosseg", keret_szorzo=D(13)), TAR, date(2026, 1, 1), date(2026, 2, 1), [s])
    assert a3.szeletek[0].keret == D(12365) * 13
    assert a3.szeletek[0].egysegar_kedvezmenyes == D("2.373") * D("1.27")


def test_villany_a2_ket_zona_kozos_keret():
    """A2: csúcs és völgy külön áron, a mérési pont egy 2 523 kWh-s kerete a zónák között fogyasztásarányosan."""
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a2", date(2024, 1, 1))],
             [Csatorna(szerep="zona_csucs"), Csatorna(szerep="zona_volgy")])
    csucs = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(200), True)])
    volgy = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(100), True)])
    c, v = szamol(f, TAR, date(2026, 1, 1), date(2026, 2, 1), [csucs, volgy]).szeletek
    assert c.keret + v.keret == D(214)  # 31 × 6,912 → 214, 2/3 – 1/3 arányban
    assert (c.idenyszak, v.idenyszak) == ("csucs", "volgy")
    assert c.kedvezmenyes + v.kedvezmenyes == D(214) and c.piaci + v.piaci == D(86)
    assert c.egysegar_kedvezmenyes == (D("8.95") + D("23.40")) * D("1.27")  # 41,085
    assert v.egysegar_kedvezmenyes == (D("1.05") + D("23.40")) * D("1.27")  # 31,052
    assert c.egysegar_piaci == v.egysegar_piaci == (D("31.80") + D("23.40")) * D("1.27")


def test_villany_a2_savkorrekcio():
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a2", date(2024, 1, 1))],
             [Csatorna(szerep="zona_csucs"), Csatorna(szerep="zona_volgy")], elszamolasi_napok=(date(2026, 1, 1),))
    # Január: 50 + 50 (keret 214, 114 marad); február: 200 + 100 = 300 (keret 194) → mind kedvezményes (+106).
    csucs = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(50), True), Pont(datetime(2026, 3, 1), D(250), True)])
    volgy = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(50), True), Pont(datetime(2026, 3, 1), D(150), True)])
    c, v = szamol(f, TAR, date(2026, 2, 1), date(2026, 3, 1), [csucs, volgy]).szeletek
    assert c.kedvezmenyes + v.kedvezmenyes == D(300) and c.piaci + v.piaci == D(0)
    assert (c.savkorrekcio + v.savkorrekcio).quantize(D(1)) == D(106)


def test_villany_b_komfort_es_b_geo():
    s = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(500), True)])
    k = szamol(Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/b_komfort", date(2024, 1, 1))], [Csatorna()]),
               TAR, date(2026, 1, 1), date(2026, 2, 1), [s]).szeletek[0]
    assert (k.keret, k.kedvezmenyes, k.piaci) == (D(214), D(214), D(286))
    assert k.egysegar_kedvezmenyes.quantize(D("0.001")) == D("23.330") and k.egysegar_piaci.quantize(D("0.001")) == D("60.935")
    g = szamol(Fiok(Kozmu.VILLANY, "elmu", [DijszabasHozzarendeles("villany/b_geo", date(2024, 1, 1))], [Csatorna()]),
               TAR, date(2026, 1, 1), date(2026, 2, 1), [s]).szeletek[0]
    assert (g.keret, g.kedvezmenyes, g.piaci) == (None, D(500), D(0))  # B GEO: nincs fogyasztási határérték
    assert g.egysegar_kedvezmenyes.quantize(D("0.001")) == D("23.368")


def test_a2_zona_idoszabaly():
    """Völgy: munkanapon 22–06 (nyári időszámításban 23–07), nem munkanapon egész nap; ledolgozós szombat munkanap."""
    from motor.zona import munkanap, volgy_ora
    assert volgy_ora(datetime(2026, 1, 7, 22)) and not volgy_ora(datetime(2026, 1, 7, 6))     # téli szerda
    assert not volgy_ora(datetime(2026, 7, 1, 22)) and volgy_ora(datetime(2026, 7, 1, 6))     # nyári szerda
    assert volgy_ora(datetime(2026, 7, 4, 12)) and volgy_ora(datetime(2026, 8, 20, 12))       # szombat, ünnep
    assert volgy_ora(datetime(2026, 1, 2, 12))                                                # áthelyezett pihenőnap
    assert munkanap(date(2026, 1, 10)) and not volgy_ora(datetime(2026, 1, 10, 12))           # ledolgozós szombat


def _a2_egy():
    return Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/a2", date(2024, 1, 1))], [Csatorna()])


def test_villany_a2_egy_csatorna_oras_adatbol():
    """Regiszter-szenzorok nélkül az órás adat adja a völgy arányát (itt 40%); a keret közös, a kedvezményes és a
    piaci rész is fogyasztásarányosan oszlik, a csúcs és a völgy a saját árán."""
    f = _a2_egy()
    f.zona_napok.update({date(2026, 1, 1) + __import__("datetime").timedelta(days=i): (D(4), D(10)) for i in range(31)})
    s = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(300), True)])
    sz = szamol(f, TAR, date(2026, 1, 1), date(2026, 2, 1), [s]).szeletek[0]
    assert (sz.keret, sz.kedvezmenyes, sz.piaci, sz.volgy, sz.becsult) == (D(214), D(214), D(86), D(120), False)
    netto = (D(214) * D("0.6") * D("8.95")).quantize(D(1)) + (D(214) * D("0.4") * D("1.05")).quantize(D(1)) \
        + (D(86) * D("31.80")).quantize(D(1)) + (D(300) * D("23.40")).quantize(D(1))
    assert sz.energia_ft == (netto * D("1.27")).quantize(D("0.01"))


def test_villany_a2_egy_csatorna_adat_nelkul_orak_aranya():
    """Órás adat nélkül az órák aránya: 2026 januárjában 21 munkanap (1/3 völgy) és 10 nem munkanap (egész nap)."""
    s = Szamlalo([Pont(datetime(2026, 1, 1), D(0), True), Pont(datetime(2026, 2, 1), D(310), True)])
    sz = szamol(_a2_egy(), TAR, date(2026, 1, 1), date(2026, 2, 1), [s]).szeletek[0]
    assert sz.becsult and sz.volgy.quantize(D("0.01")) == (D(310) * (D(21) / 3 + 10) / 31).quantize(D("0.01"))


def test_gaz_mero_nelkuli_atalany():
    """Gázmérő nélkül (csak gáztűzhely): havi fix MJ a szobaszám és a tűzhely szerint × 2,465 Ft/MJ nettó.
    MVM-táblázat: 1 szoba, 2 lángú 210 MJ = 518 Ft nettó / 657 Ft bruttó; 2 szoba, 3–4 lángú 450 MJ = 1 109 / 1 408."""
    from gaz_atalany import havi_mj
    from modell import fiok_motorba, szorzok
    assert havi_mj("1", "2_langu") == D(210) and havi_mj(2.5, "garzon") == D(450) and havi_mj("5", "garzon") is None
    for szoba, tuzhely, brutto in (("1", "2_langu", 657), ("2", "3_4_langu", 1408), ("4", "5_langu", 2473)):
        f = Fiok(Kozmu.GAZ, "mvm_next", [DijszabasHozzarendeles("gaz/mero_nelkuli", date(2024, 1, 1))], [Csatorna(keret_aktiv=False)],
                 szorzok=szorzok({"dijszabas": "gaz/mero_nelkuli", "szobaszam": szoba, "tuzhely": tuzhely}))
        r = szamol(f, TAR, date(2026, 10, 1), date(2026, 11, 1), [Szamlalo([Pont(datetime(2026, 1, 1), D(0), True)])])
        assert r.energia_ft == 0 and abs(r.osszesen_ft - D(brutto)) <= 1  # a táblázat bruttója egész Ft-ra kerekített


def test_d_arlista_sorok():
    """Az MVM negyedórás árlistájának sorai → órás átlagár (negatív ár és ezres tagolás is)."""
    from motor.rugalmas import sorok_ora_arak
    ar = sorok_ora_arak([
        "Dátum Időszak kezdete Időszak vége Rugalmas egységár", "2026.04.12 13:00 13:15 -10,00",
        "2026.04.12 13:15 13:30 10,00", "2026.04.12 13:30 13:45 20,00", "2026.04.12 13:45 14:00 40,00",
        "2026.01.20 18:00 18:15 1 168,39 * megjegyzés",
    ])
    assert ar == {"2026-04-12T13": 15.0, "2026-01-20T18": 1168.39}


def test_villany_d_rugalmas_ar():
    """D: a keretig az A1 kedvezményes ára, felette a fogyasztással súlyozott rugalmas ár (nettó, + RHD, + ÁFA)."""
    from datetime import timedelta
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/d", date(2024, 1, 1))], [Csatorna()])
    # 31 nap × 20 kWh: az első 15 napon 50 Ft/kWh, utána 70 Ft/kWh → súlyozott (15×50 + 16×70)/31
    for i in range(31):
        f.d_napok[date(2027, 1, 1) + timedelta(days=i)] = (D(20), D(20) * (D(50) if i < 15 else D(70)), False)
    s = Szamlalo([Pont(datetime(2027, 1, 1), D(0), True), Pont(datetime(2027, 2, 1), D(620), True)])
    sz = szamol(f, TAR, date(2027, 1, 1), date(2027, 2, 1), [s]).szeletek[0]
    d_ar = (D(15) * 50 + D(16) * 70) / 31
    assert (sz.keret, sz.kedvezmenyes, sz.piaci, sz.becsult) == (D(214), D(214), D(406), False)
    assert sz.egysegar_piaci == (d_ar + D("23.40")) * D("1.27")
    assert sz.egysegar_kedvezmenyes == (D("5.25") + D("23.40")) * D("1.27")


def test_villany_d_becsles_kozzetett_ar_nelkul():
    """Ha a hónapra még nincs közzétett ár, a legutóbbi közzétett hónap súlyozott ára (tartalék), becsült jelöléssel."""
    from motor.rugalmas import rugalmas_ar
    f = Fiok(Kozmu.VILLANY, "mvm_demasz", [DijszabasHozzarendeles("villany/d", date(2024, 1, 1))], [Csatorna()], d_tartalek=D(60))
    assert rugalmas_ar(f, date(2027, 3, 1), date(2027, 4, 1)) == (D(60), True)
    f.d_napok[date(2027, 3, 1)] = (D(10), D(400), False)  # mért nap 40 Ft/kWh, a többi 30 nap a tartalékkal
    ar, becsult = rugalmas_ar(f, date(2027, 3, 1), date(2027, 4, 1))
    assert becsult and ar == (D(400) + 30 * D(10) * 60) / (31 * D(10))


def test_viz_egesz_m3_kerekitett_oraallasokbol():
    """A víz egész m³-re (lefelé) kerekített óraállások különbségével számlázódik: 741,6 → 749,3 = 749 − 741 = 8 m³
    (mért 7,7). Hónapfordulón kettévágva is 8 marad (746,9-nél: 746 − 741 = 5, 749 − 746 = 3)."""
    fiok = Fiok(Kozmu.VIZ, "dakov", [DijszabasHozzarendeles("viz/dakov", date(2024, 1, 1))],
                [Csatorna(szerep="fo", merok=[Mero("1", date(2026, 1, 1), D("741.6"))])])
    s = Szamlalo([Pont(datetime(2026, 1, 15), D(0), True), Pont(datetime(2026, 2, 1), D("5.3"), True),
                  Pont(datetime(2026, 2, 20), D("7.7"), True)])
    r = szamol(fiok, TAR, date(2026, 1, 15), date(2026, 2, 20), [s], extra_hatarok={date(2026, 2, 1)})
    assert [sz.elszamolt for sz in r.szeletek] == [D(5), D(3)]
    assert sum(sz.mennyiseg for sz in r.szeletek) == D("7.7")
    viz = sum(sz.energia_ft - sz.csatorna_ft for sz in r.szeletek)
    assert sum(sz.csatorna_ft for sz in r.szeletek) == (D(5) * D("373.82") * D("1.27")).quantize(D("0.01")) + (D(3) * D("373.82") * D("1.27")).quantize(D("0.01"))
    assert abs(viz - D(8) * D("269.52") * D("1.27")) < D("0.02")


def test_viz_almero_levonas_egesz_evben_dakov():
    """DAKÖV: a locsolási almérő vize egész évben levonódik a csatornadíjból (a számlák szerint idényen kívül is,
    pl. 2023 ősz 2 m³, 2025 tavasz 3 m³) – szeptember 6 + október 2 m³ = 8 m³ levonás."""
    fiok = _viz_fiok(True)
    fo = Szamlalo([Pont(datetime(2026, 9, 1), D(0), True), Pont(datetime(2026, 11, 1), D(20), True)])
    al = Szamlalo([Pont(datetime(2026, 9, 1), D(0), True), Pont(datetime(2026, 10, 1), D(6), True), Pont(datetime(2026, 11, 1), D(8), True)])
    r = szamol(fiok, TAR, date(2026, 9, 1), date(2026, 11, 1), [fo, al])
    al_sz = [s for s in r.szeletek if s.csatorna == "almero"]
    assert sum(s.elszamolt for s in al_sz) == D(8)
    assert sum(s.csatorna_ft for s in al_sz) == -(D(8) * D("373.82") * D("1.27")).quantize(D("0.01"))


def test_gaz_tullepes_utan_nincs_visszamenoleges_jovairas():
    """Gáz, diktálás: augusztusban 95 m³ (≈3 288 MJ, keret 565) – a túllépés piaci áron marad; az októberi
    (alacsony) fogyasztásnál a keret nem írja jóvá visszamenőleg, a kedvezményes rész legfeljebb a fogyasztás."""
    s = _gaz_szamlalo(((2026, 7, 15), 0), ((2026, 8, 1), 25), ((2026, 9, 1), 120), ((2026, 10, 1), 130), ((2026, 11, 1), 140))
    r = szamol(_gaz_dikt(), TAR, date(2026, 10, 1), date(2026, 11, 1), [s])
    sz = r.szeletek[0]
    assert sz.piaci >= 0 and sz.kedvezmenyes == sz.elszamolt and r.osszesen_ft > 0
    # Folyó hónap 3. napján (mérés vége okt. 4.): sem negatív piaci rész, sem negatív összeg.
    r2 = szamol(_gaz_dikt(), TAR, date(2026, 10, 1), date(2026, 11, 1), [s], meres_vege=datetime(2026, 10, 4))
    assert all(x.piaci >= 0 for x in r2.szeletek) and r2.osszesen_ft > 0


def test_munkarend_rendelet_szerint_holidays_nelkul(monkeypatch):
    """A munkarend a saját (rendelet szerinti) táblából – a holidays csomag nélkül is (régi változata hibás lehet)."""
    import sys
    from motor import munkarend
    monkeypatch.setitem(sys.modules, "holidays", None)
    munkarend.athelyezesek.cache_clear()
    m = munkarend.munkanap
    assert not m(date(2026, 1, 2)) and m(date(2026, 1, 10))        # 10/2025. NGM: jan. 2. pihenő, jan. 10. munkanap
    assert not m(date(2026, 8, 21)) and m(date(2026, 8, 8)) and not m(date(2026, 12, 24)) and m(date(2026, 12, 12))
    assert not m(date(2025, 5, 2)) and m(date(2025, 5, 17)) and not m(date(2025, 10, 24)) and m(date(2025, 10, 18))
    assert not m(date(2024, 12, 27)) and m(date(2024, 12, 14)) and not m(date(2024, 8, 19)) and m(date(2024, 8, 3))
    assert not m(date(2026, 4, 3)) and not m(date(2026, 4, 6)) and not m(date(2026, 5, 25))  # nagypéntek, húsvét-, pünkösdhétfő
    assert munkarend.husvetvasarnap(2027) == date(2027, 3, 28)
    assert m(date(2027, 1, 4)) and munkarend.athelyezesek(2027)[2].startswith("nincs adat")
    munkarend.athelyezesek.cache_clear()


def test_viz_alfoldviz_2026_08():
    """ALFÖLDVÍZ Zrt. víz, 2026.05.01–08.31 (900014LV26, Városi lakás): mérő 64 → 68 (4 m³), alapdíj nincs.

    Tételek: ivóvíz 4 × 234,00 = 936,00 nettó (1 188,72 bruttó); szennyvíz 4 × 240,30 = 961,20 (1 220,72) +
    vízterhelési díj 4 × 6,90 = 27,60 (35,05) – a díjszabásban a csatornadíjba vonva: 4 × 247,20 = 988,80 (1 255,78).
    A számla a szennyvízsort kétszer számolta (8 m³) → 3 699 Ft; egyszeres szennyvízzel a tételek összege 2 444,50 Ft.
    """
    fiok = Fiok(Kozmu.VIZ, "alfoldviz", [DijszabasHozzarendeles("viz/alfoldviz", date(2024, 1, 1))], [Csatorna(szerep="fo")])
    fo = Szamlalo([Pont(datetime(2026, 5, 1), D(64), True), Pont(datetime(2026, 9, 1), D(68), True)])
    r = szamol(fiok, TAR, date(2026, 5, 1), date(2026, 9, 1), [fo])
    assert sum(s.mennyiseg for s in r.szeletek) == D(4)
    assert sum(s.csatorna_ft for s in r.szeletek) == D("1255.78")
    assert sum(s.energia_ft for s in r.szeletek) == D("2444.50")


def _tavho(legterfogat="118.30", gj="2.0939"):
    return Fiok(Kozmu.TAVHO, "hvsz", [DijszabasHozzarendeles("tavho/hvsz", date(2025, 1, 1))], [Csatorna()],
                szorzok={"legterfogat": D(legterfogat), "futes_gj_ho": D(gj)})


def _tavho_ho(tol, ig, m3):
    s = Szamlalo([Pont(datetime.combine(tol, datetime.min.time()), D(100), True),
                  Pont(datetime.combine(ig, datetime.min.time()), D(100) + D(m3), True)])
    r = szamol(_tavho(), TAR, tol, ig, [s])
    return sum(x.energia_ft + x.alapdij_ft for x in r.szeletek)


def test_tavho_hvsz_havi_szamlak():
    """HVSZ távhő (Városi lakás, 118,30 lm³, havi 2,0939 GJ átalány) – a valódi havi számlák (forintra kerekítve):
    2025.09: fűtési + melegvíz alapdíj, 1 m³ melegvíz + 1 m³ csatorna (240 Ft) → 4 364 Ft (hődíj még nincs);
    2026.01: −30%-os hődíj és melegvíz (2 024 Ft/GJ, 272 Ft/m³) → 8 360 Ft; 2026.02: 2 m³ → 10 909 Ft;
    2026.07: alapdíj és hődíj nélkül, csak 1 m³ melegvíz (csatorna 0 Ft) → 494 Ft."""
    assert _tavho_ho(date(2025, 9, 1), date(2025, 10, 1), 1).quantize(D(1)) == 4364
    assert _tavho_ho(date(2026, 1, 1), date(2026, 2, 1), 1).quantize(D(1)) == 8360
    assert _tavho_ho(date(2026, 2, 1), date(2026, 3, 1), 2).quantize(D(1)) == 10909
    assert _tavho_ho(date(2026, 7, 1), date(2026, 8, 1), 1).quantize(D(1)) == 494


def _tavho_minimum(m3_veg, szamla_honap=1, mentes=False, tol=date(2026, 7, 1), ig=date(2026, 8, 1), meres_vege=None):
    """Júliusi (csak melegvíz, 389 Ft/m³ + 27%) számla a melegvízóra 25,0 → 25 + m3_veg állásával."""
    s = Szamlalo([Pont(datetime.combine(tol, datetime.min.time()), D(25), True),
                  Pont(datetime.combine(ig, datetime.min.time()), D(25) + D(str(m3_veg)), True)])
    f = _tavho()
    f.szamla_honap, f.minimum_mentes = szamla_honap, mentes
    r = szamol(f, TAR, tol, ig, [s], meres_vege=meres_vege)
    return sum(x.energia_ft + x.alapdij_ft for x in r.szeletek).quantize(D(1)), sum(x.elszamolt for x in r.szeletek)


def test_egesz_m3_es_szamlankenti_minimum():
    """A szolgáltató egész m³-re (az óraállások egész részének különbségével) és számlánként legalább 1 m³-rel számláz:
    0 vagy 0,8 m³ → 1 m³ (494 Ft); 2,6 m³ → 2 m³. Nem jár a minimum: ha az időszak nem egy teljes számlázási időszak
    (négyhavi számlázásnál egy hónap), üdülőnél (sajátos számlázás) és a folyó („eddig”) számításnál."""
    assert _tavho_minimum(0) == (494, 1)
    assert _tavho_minimum("0.8") == (494, 1)
    assert _tavho_minimum("2.6") == (988, 2)
    assert _tavho_minimum(0, szamla_honap=4) == (0, 0)
    assert _tavho_minimum(0, mentes=True) == (0, 0)
    assert _tavho_minimum(0, szamla_honap=0) == (0, 0)
    assert _tavho_minimum(0, meres_vege=datetime(2026, 7, 20)) == (0, 0)


def test_szuneteltetes_semmi_nem_jar():
    """Szüneteltetett számlázás (pl. lakatlan ingatlan): a szünet napjaira se fogyasztás, se alapdíj, se fűtési átalány,
    se számlánkénti minimum nem jár; a szünet előtti napok díja időarányosan megmarad."""
    tol, ig = date(2025, 10, 1), date(2025, 11, 1)
    s = Szamlalo([Pont(datetime(2025, 10, 1), D(15), True), Pont(datetime(2025, 11, 1), D(16), True)])
    f = _tavho()
    f.szamla_honap = 1
    teljes = szamol(f, TAR, tol, ig, [s]).osszesen_ft
    f.szunetel = ((date(2025, 10, 1), None),)
    r = szamol(f, TAR, tol, ig, [s])
    assert teljes.quantize(D(1)) == 10720 and r.osszesen_ft == 0 and sum(x.elszamolt or 0 for x in r.szeletek) == 0
    f.szunetel = ((date(2025, 10, 16), None),)  # félhónap után: a havi alapdíj / átalány a hónap 1-jén járt
    r = szamol(f, TAR, tol, ig, [s])
    assert 0 < r.osszesen_ft < teljes
    f.szunetel = ((date(2025, 9, 1), date(2025, 10, 1)),)  # a szünet már véget ért: a teljes díj jár
    assert szamol(f, TAR, tol, ig, [s]).osszesen_ft == teljes
