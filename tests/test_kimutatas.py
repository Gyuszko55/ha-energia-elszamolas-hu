"""Éves elszámolási kimutatás (kimutatas.py) és az MVM-számlatételek olvasása (szamlak.mvm_tetelek) – a valódi
MVM-számlák szerkezetével és számaival (Kertes ház A1 2025/26, H 2026), kitalált sorszámokkal."""
from datetime import date
from decimal import Decimal

import tests.conftest  # noqa: F401
from kimutatas import _honap1, jogi_idoszakok, jogi_lista, kimutatas
from szamlak import mvm_levont_szamlak, mvm_tetelek

A1 = {"afa": 27, "energia_kedvezmenyes": 5.25, "energia_piaci": 31.80, "rendszerhasznalati": 23.40, "alapdij_ho": 120.50}
H = {"afa": 27, "energia_teli": 1.90, "rendszerhasznalati": 16.18, "alapdij_ho": 39.50}


def arak(azon, _nap):
    return H if azon == "villany/h" else A1


def _allas(tabla):
    def f(csat, nap):
        v = tabla.get(csat, {}).get(nap.isoformat())
        return (Decimal(v), True) if v is not None else None
    return f


def _sz(tol, ig, kelte, kisz, kedv, piaci, e, r, alap, teli=0, tipus="elszamolo", levont=None):
    return {"tipus": tipus, "idoszak": [tol, ig], "kelte": kelte, "levont_szamlak": levont or [],
            "tetelek": {"kiszamlazott_kwh": str(kisz), "kedvezmenyes": str(kedv), "piaci": str(piaci), "teli": str(teli),
                        "energia_brutto": str(e), "rhd_brutto": str(r), "alapdij": alap}}


def test_a1_ev_kiszamlazatlan_fogyasztas():
    allasok = {"vetelezes": {"2025-10-01": 16218, "2025-11-10": 16638, "2026-04-10": 18827, "2026-08-08": 20061,
                             "2026-09-09": 20520, "2026-09-29": 20631}}
    szamlak = {
        "1": _sz("2025-10-02", "2025-11-10", "2025-11-11", 420, 276, 144, 7655, 12636, {"2025-11": "154"}),
        # ugyanarra az időszakra egy sztornózott és egy újra kiállított: egyszer számít (a frissebb)
        "2a": _sz("2025-11-11", "2026-04-10", "2026-04-13", 2189, 1043, 1146, 0, 0, {}),
        "2b": _sz("2025-11-11", "2026-04-10", "2026-04-20", 2189, 1043, 1146, 46796, 65000, {"2026-04": "154"}),
        "3": _sz("2026-04-11", "2026-08-08", "2026-08-17", 33, 206, -173, -5612, 1592,
                 {"2026-05": "153", "2026-06": "153", "2026-07": "153", "2026-08": "153"}),
        "r": {**_sz("2026-02-03", "2026-03-11", "2026-03-12", 293, 256, 37, 3202, 8861, {"2026-03": "154"}), "tipus": "resz"},
    }
    k = kimutatas("villany/a1", date(2025, 10, 1), date(2026, 9, 29), _allas(allasok), szamlak, arak)
    sorok = {s["sorszam"]: s for s in k["sorok"]}
    assert "2a" not in sorok and "2b" in sorok
    s1 = sorok["1"]
    assert (s1["mert"], s1["keret"], s1["kedvezmenyes"], s1["piaci"]) == (420, 276, 276, 144)
    assert s1["helyes"] == 20291 == s1["mvm"]["dij"]           # valódi MVM-számla: forintra
    s3 = sorok["3"]
    assert s3["mert"] == 1234 and s3["mvm"]["kiszamlazott"] == 33
    assert s3["dij"]["alapdij"] == 612                          # 4 hó × 120,50 = 482 → 612 (tételként kerekítve)
    meg = {m["sorszam"]: m for m in k["megallapitasok"]}
    assert meg["3"]["tipus"] == "nem_kiszamlazott" and "1201 kWh kimaradt" in meg["3"]["szoveg"]
    assert meg["r"]["tipus"] == "nem_levont"                    # a részszámlát egyik elszámoló sem vonta le
    assert k["fuggo"]["tol"] == "2026-08-09" and k["fuggo"]["ig"] == "2026-09-29"


def test_h_regisztercsere_idenyekkel():
    # H-mérő 2026-02-03-tól (kezdőállás 0): téli (1.81) 474, nyári (1.82) 349 kWh a 08-08-i diktálásig.
    allasok = {"h_teli": {"2026-02-03": 0, "2026-08-08": 474, "2026-09-29": 474},
               "h_nyari": {"2026-02-03": 0, "2026-08-08": 349, "2026-09-29": 527}}
    szamlak = {"e": _sz("2026-02-03", "2026-08-08", "2026-08-31", 823, 474, 0, 4003, 21970,
                        {"2026-03": "50", "2026-04": "50", "2026-05": "153", "2026-06": "153", "2026-07": "153", "2026-08": "153"},
                        teli=349)}
    k = kimutatas("villany/h", date(2026, 2, 3), date(2026, 9, 29), _allas(allasok), szamlak, arak, kezdo=True)
    s = k["sorok"][0]
    assert s["tol"] == "2026-02-03"                             # a felszerelés napja is az első időszak
    assert (s["teli"], s["nyari"], s["piaci"]) == (474, 349, 0)  # a nyári a saját kereten belül
    assert s["dij"] == {"kedvezmenyes": 2327, "piaci": 0, "rhd": 10372, "teli": 1144, "teli_rhd": 9740, "alapdij": 712}
    assert s["helyes"] == 24295 and s["elteres"] == -1678       # a számla (felcserélt regiszterekkel) 25 973 Ft
    assert k["megallapitasok"][0]["tipus"] == "regisztercsere"
    assert k["fuggo"]["helyes"] == 6631 and k["ev_helyes"] == 30926


def _sz_k(tol, ig, kelte, kisz, kedv, piaci, e, r, alap, kedv_t):
    x = _sz(tol, ig, kelte, kisz, kedv, piaci, e, r, alap)
    x["tetelek"]["kedv_tetelek"] = kedv_t
    return x


def _potlasos_szamlak():
    k_ = [["2025-10-02", "2025-11-10", "276"]]
    return {
        "1": _sz_k("2025-10-02", "2025-11-10", "2025-11-11", 420, 276, 144, 7655, 12636, {"2025-11": "154"}, k_),
        "2": _sz_k("2025-11-11", "2025-12-02", "2025-12-03", 372, 152, 220, 9898, 11209, {"2025-12": "154"}, [["2025-11-11", "2025-12-02", "152"]]),
        "3": _sz_k("2025-12-03", "2026-01-12", "2026-01-13", 747, 284, 463, 20591, 22354, {"2026-01": "154"}, [["2025-12-03", "2026-01-12", "284"]]),
        "4": _sz_k("2026-01-13", "2026-02-02", "2026-02-27", 434, 145, 289, 12637, 13052, {"2026-02": "154"}, [["2026-01-13", "2026-02-02", "145"]]),
        "5": _sz_k("2026-02-03", "2026-04-10", "2026-04-13", 636, 463, 173, 10073, 19208, {"2026-03": "154", "2026-04": "154"}, [["2026-02-03", "2026-04-10", "463"]]),
        "6": _sz_k("2026-04-11", "2026-08-08", "2026-08-17", 33, 206, -173, -5612, 1592, {"2026-05": "153", "2026-06": "153", "2026-07": "153", "2026-08": "153"},
                   [["2026-04-11", "2026-07-31", "30"], ["2026-08-01", "2026-08-08", "3"], ["2026-04-11", "2026-07-31", "173"]]),
        "7": _sz_k("2026-08-09", "2026-09-09", "2026-09-21", 459, 273, 186, 9330, 13795, {"2026-09": "154"}, [["2026-08-09", "2026-09-09", "221"], ["2026-08-09", "2026-09-09", "52"]]),
        "8": _sz_k("2026-09-10", "2026-09-29", "2026-10-21", 1312, 138, 1174, 48334, 38990, {}, [["2026-09-10", "2026-09-29", "138"]]),
    }


def _potlasos_ev():
    # A valódi 2025/26-os év szerkezete: az ápr. 11.–júl. 31. közötti 1201 kWh az augusztusi számlából kimarad, az
    # októberi pótolja, de csak az utolsó 20 nap keretével; a jan. 13.-i és a záró soroknál a számla szerinti kerekítés.
    allasok = {"vetelezes": {"2025-10-01": 16218, "2025-11-10": 16638, "2025-12-02": 17010, "2026-01-12": 17757, "2026-02-02": 18191,
                             "2026-04-10": 18827, "2026-07-31": 20028, "2026-08-08": 20061, "2026-09-09": 20520, "2026-09-29": 20631}}
    szamlak = _potlasos_szamlak()
    return kimutatas("villany/a1", date(2025, 10, 1), date(2026, 9, 29), _allas(allasok), szamlak, arak)


def test_a1_potolt_fogyasztas_es_kedvezmenyes_evek():
    k = _potlasos_ev()
    o = k["osszesen"]
    assert (o["mert"], o["kiszamlazott"], o["kedvezmenyes"], o["mvm_kedvezmenyes"]) == (4413, 4413, 2507, 1937)
    meg = {m["sorszam"]: m for m in k["megallapitasok"] if m["tipus"] != "sav_hiany"}
    assert meg["6"]["tipus"] == "nem_kiszamlazott"
    assert meg["8"]["tipus"] == "potolt_fogyasztas" and "1201 kWh korábbi fogyasztást" in meg["8"]["szoveg"] and "a 6 sz. számlán" in meg["8"]["szoveg"]
    e1, e2 = k["kedv_evek"]
    assert (e1["ev"], e1["tol"], e1["ig"], e1["nap"]) == ("2025/2026", "2025-10-02", "2026-07-31", 303)
    assert (e1["keret"], e1["fogyasztas"], e1["kedvezmenyes"], e1["mvm_kedvezmenyes"], e1["hiany"]) == (2093, 3810, 2093, 1523, 570)
    assert (e2["ev"], e2["nap"], e2["keret"], e2["kedvezmenyes"], e2["mvm_kedvezmenyes"], e2["hiany"]) == ("2026/2027", 60, 414, 414, 414, 0)
    sav = [m for m in k["megallapitasok"] if m["tipus"] == "sav_hiany"]
    assert len(sav) == 1 and sav[0]["sorszam"] == "8" and sav[0]["hatas_ft"] is None
    assert sav[0]["becsult_ft"] == 19220 and "570 kWh piaci áron" in sav[0]["szoveg"]
    assert "keret járt, a számlák" in sav[0]["szoveg"] and "kb. 19 220 Ft" in sav[0]["szoveg"]


def test_teljes_kedvezmenyes_ev_az_elszamolasi_evtol_fuggetlenul():
    # A valódi 2025/26: aug. 1.–okt. 1. számlái is számítanak, 365 nap, 2523 kWh; a hiány 571 kWh (a levél számai).
    allasok = {"vetelezes": {"2025-07-31": 15636, "2025-08-10": 15743, "2025-09-09": 16076, "2025-10-01": 16218, "2025-11-10": 16638, "2025-12-02": 17010,
                             "2026-01-12": 17757, "2026-02-02": 18191, "2026-04-10": 18827, "2026-07-31": 20028, "2026-08-08": 20061, "2026-09-09": 20520, "2026-09-29": 20631}}
    szamlak = _potlasos_szamlak() | {
        "a": _sz_k("2025-07-09", "2025-08-10", "2025-08-12", 352, 228, 124, 0, 0, {}, [["2025-07-09", "2025-07-31", "159"], ["2025-08-01", "2025-08-10", "69"]]),
        "b": _sz_k("2025-08-11", "2025-09-09", "2025-09-10", 333, 207, 126, 0, 0, {}, [["2025-08-11", "2025-09-09", "207"]]),
        "c": _sz_k("2025-09-10", "2025-10-01", "2025-10-13", 142, 153, -11, 0, 0, {}, [["2025-09-10", "2025-10-01", "142"], ["2025-09-10", "2025-10-01", "11"]]),
    }
    k = kimutatas("villany/a1", date(2025, 10, 1), date(2026, 9, 29), _allas(allasok), szamlak, arak)
    t1, t2 = k["kedv_evek"][0]["teljes"], k["kedv_evek"][1]["teljes"]
    assert (t1["tol"], t1["ig"], t1["nap"], t1["keret"], t1["fogyasztas"], t1["mvm_kedvezmenyes"], t1["hiany"]) == ("2025-08-01", "2026-07-31", 365, 2523, 4392, 1952, 571)
    assert (t2["ig"], t2["nap"], t2["keret"], t2["mvm_kedvezmenyes"]) == ("2026-09-29", 60, 415, 414)
    sav = next(m for m in k["megallapitasok"] if m["tipus"] == "sav_hiany")
    assert sav["becsult_ft"] == 19220 and "365 napra 2523 kWh keret járt, a számlákon 1952 kWh szerepel: 571 kWh" in sav["szoveg"]


def test_teljes_kedvezmenyes_ev_hianyzo_szamlanal_nincs():
    # Az év eleji számlák nélkül a teljes év nem számolható: nem találunk ki számot.
    assert _potlasos_ev()["kedv_evek"][0]["teljes"] is None


def test_a1_a_keret_nem_megy_at_aug_1_utan():
    # Júliusig alig fogy (rengeteg szabad keret), augusztusban sok: a régi évből nem hozható át a keret.
    allasok = {"vetelezes": {"2026-05-31": 1000, "2026-07-31": 1010, "2026-08-31": 1610}}
    szamlak = {"j": _sz("2026-06-01", "2026-07-31", "2026-08-01", 10, 10, 0, 0, 0, {}), "a": _sz("2026-08-01", "2026-08-31", "2026-09-01", 600, 214, 386, 0, 0, {})}
    k = kimutatas("villany/a1", date(2026, 5, 31), date(2026, 8, 31), _allas(allasok), szamlak, arak)
    s = {x["sorszam"]: x for x in k["sorok"]}
    assert (s["j"]["keret"], s["j"]["kedvezmenyes"]) == (422, 10)
    assert (s["a"]["keret"], s["a"]["kedvezmenyes"], s["a"]["piaci"]) == (214, 214, 386)


def test_a1_tetelek_nelkul_nincs_sav_jelzes():
    # Tételes adat nélkül (régebben beolvasott számla) nincs MVM-oldali bontás, hibajelzés sem.
    allasok = {"vetelezes": {"2026-05-31": 1000, "2026-07-31": 1500}}
    k = kimutatas("villany/a1", date(2026, 5, 31), date(2026, 7, 31), _allas(allasok), {"j": _sz("2026-06-01", "2026-07-31", "2026-08-01", 500, 100, 400, 0, 0, {})}, arak)
    assert k["kedv_evek"][0]["mvm_kedvezmenyes"] is None and not [m for m in k["megallapitasok"] if m["tipus"] == "sav_hiany"]


def test_sztornozott_reszszamla_nem_kell_levonni():
    allasok = {"vetelezes": {"2026-05-31": 1000, "2026-07-31": 1500}}
    szamlak = {
        "e": _sz("2026-06-01", "2026-07-31", "2026-08-01", 500, 421, 79, 0, 0, {}),
        "r1": {**_sz("2026-06-01", "2026-06-30", "2026-07-01", 100, 100, 0, 0, 0, {}), "tipus": "resz"},
        "r2": {**_sz("2026-07-01", "2026-07-31", "2026-08-01", 100, 100, 0, 0, 0, {}), "tipus": "resz"},
        "st": {"tipus": "storno", "sztornozott": "r2", "idoszak": ["2026-07-01", "2026-07-31"], "kelte": "2026-08-02"},
    }
    k = kimutatas("villany/a1", date(2026, 5, 31), date(2026, 7, 31), _allas(allasok), szamlak, arak)
    assert [m["sorszam"] for m in k["megallapitasok"] if m["tipus"] == "nem_levont"] == ["r1"]


def _pontok(tabla):
    return lambda c: sorted((date.fromisoformat(n), Decimal(str(v))) for n, v in tabla.get(c, {}).items())


def _interp(tabla):
    def f(csat, nap):
        p = sorted((date.fromisoformat(n), Decimal(str(v))) for n, v in tabla.get(csat, {}).items())
        for n, v in p:
            if n == nap:
                return v, True
        e, u = [x for x in p if x[0] < nap], [x for x in p if x[0] > nap]
        if not e or not u:
            return None
        return e[-1][1] + (u[0][1] - e[-1][1]) * Decimal((nap - e[-1][0]).days) / Decimal((u[0][0] - e[-1][0]).days), False
    return f


def test_jogi_idoszakok_a1_lezart_es_folyamatban():
    allasok = {"vetelezes": {"2025-07-08": 15391 - 0, "2025-07-31": 15636, "2025-08-10": 15743, "2025-09-09": 16076, "2025-10-01": 16218, "2025-11-10": 16638, "2025-12-02": 17010,
                             "2026-01-12": 17757, "2026-02-02": 18191, "2026-04-10": 18827, "2026-07-31": 20028, "2026-08-08": 20061, "2026-09-09": 20520, "2026-09-29": 20631, "2026-11-04": 20900}}
    szamlak = _potlasos_szamlak() | {
        "a": _sz_k("2025-07-09", "2025-08-10", "2025-08-12", 352, 228, 124, 0, 0, {}, [["2025-07-09", "2025-07-31", "159"], ["2025-08-01", "2025-08-10", "69"]]),
        "b": _sz_k("2025-08-11", "2025-09-09", "2025-09-10", 333, 207, 126, 0, 0, {}, [["2025-08-11", "2025-09-09", "207"]]),
        "c": _sz_k("2025-09-10", "2025-10-01", "2025-10-13", 142, 153, -11, 0, 0, {}, [["2025-09-10", "2025-10-01", "142"], ["2025-09-10", "2025-10-01", "11"]]),
    }
    lez, fo = jogi_idoszakok("villany/a1", date(2026, 11, 6), _pontok(allasok), _interp(allasok), szamlak, arak)
    assert (lez["nev"], lez["allapot"], lez["tol"], lez["ig"], lez["nap"], lez["keret_teljes"]) == ("2025/2026", "lezart", "2025-08-01", "2026-07-31", 365, 2523)
    assert (lez["mert"], lez["kedvezmenyes"], lez["piaci"], lez["szamla_kedvezmenyes"], lez["hiany"], lez["hiany_ft"]) == (4392, 2523, 1869, 1952, 571, 19253)
    assert lez["szamlazva_ig"] == "2026-07-31" and not lez["lyuk"]
    assert [r["sorszam"] for r in lez["reszek"]] == ["a", "b", "c", "1", "2", "3", "4", "5", "6"]
    assert lez["reszek"][0]["tol"] == "2025-08-01" and lez["reszek"][0]["szamla_fo"] == 69 and lez["reszek"][-1]["ig"] == "2026-07-31"
    assert (fo["nev"], fo["allapot"], fo["tol"], fo["ig"], fo["eddig"], fo["szamlazva_ig"]) == ("2026/2027", "folyamatban", "2026-08-01", "2027-07-31", "2026-11-04", "2026-09-29")
    assert (fo["keret_szamlazva"], fo["szamla_kedvezmenyes"], fo["hiany"], fo["hiany_ft"]) == (415, 414, 1, 0)
    assert fo["nap_eddig"] == 96 and fo["keret_eddig"] == 664


def test_jogi_idoszakok_h_nyari_idenye_az_ev_aranyos_resze():
    # A nyári regiszter télen nem nő: az idény eleji állás nem becsülhető arányosan (0 marad, nem a 02.03–08.08 közti rész).
    allasok = {"h_teli": {"2026-02-03": 0, "2026-08-08": 474, "2026-09-29": 474, "2026-11-01": 500},
               "h_nyari": {"2026-02-03": 0, "2026-08-08": 349, "2026-09-29": 527, "2026-11-01": 560}}
    szamlak = {"e": _sz("2026-02-03", "2026-08-08", "2026-08-31", 823, 474, 0, 4003, 21970, {}, teli=349)}
    szamlak["e"]["tetelek"] |= {"kedv_tetelek": [["2026-04-16", "2026-07-31", "414"], ["2026-08-01", "2026-08-08", "60"]], "piaci_tetelek": [],
                                "teli_tetelek": [["2026-02-03", "2026-04-15", "349"]]}
    lez, tel = jogi_idoszakok("villany/h", date(2026, 11, 6), _pontok(allasok), _interp(allasok), szamlak, arak)
    assert (lez["fajta"], lez["nev"], lez["tol"], lez["ig"], lez["nap"], lez["keret_teljes"]) == ("nyari", "2026", "2026-04-16", "2026-10-14", 182, 1258)
    assert lez["mert"] == 560 and lez["eddig"] == "2026-10-14" and lez["keret_eddig"] == 1258 and lez["piaci"] == 0
    assert lez["szamlazva_ig"] == "2026-08-08" and lez["szamla_kedvezmenyes"] == 474
    assert (tel["fajta"], tel["nev"], tel["allapot"], tel["tol"], tel["ig"], tel["keret_teljes"], tel["mert"]) == ("teli", "2026/2027", "folyamatban", "2026-10-15", "2027-04-15", None, 26)
    assert tel["reszek"] == [] and tel["hiany"] is None


def test_jogi_idoszakok_nyaron_a_nyari_ido_folyamatban():
    allasok = {"h_teli": {"2025-02-03": 0}, "h_nyari": {"2025-02-03": 0, "2025-10-20": 300, "2026-05-16": 300, "2026-06-30": 400}}
    sor = jogi_idoszakok("villany/h", date(2026, 7, 1), _pontok(allasok), _interp(allasok), {}, arak)
    assert [(s["nev"], s["allapot"]) for s in sor] == [("2025", "lezart"), ("2026", "folyamatban")]
    assert sor[1]["mert"] == 100 and sor[1]["eddig"] == "2026-06-30" and sor[1]["nap_eddig"] == 76 and sor[1]["szamlazva_ig"] is None


def test_jogi_lista_az_eves_leolvasastol_fuggetlen():
    a = jogi_lista("villany/a1", date(2026, 11, 6), date(2024, 10, 1))
    assert [(x["nev"], x["allapot"]) for x in a] == [("2026/2027", "folyamatban"), ("2025/2026", "lezart"), ("2024/2025", "lezart")]
    assert (a[1]["tol"], a[1]["ig"]) == (date(2025, 8, 1), date(2026, 7, 31))
    h = jogi_lista("villany/h", date(2026, 11, 6), date(2026, 2, 3))
    assert [(x["fajta"], x["nev"], x["allapot"]) for x in h] == [("teli", "2026/2027", "folyamatban"), ("nyari", "2026", "lezart"), ("teli", "2025/2026", "lezart")]
    assert (h[1]["tol"], h[1]["ig"]) == (date(2026, 4, 16), date(2026, 10, 14))


def test_honapok():
    assert _honap1(date(2025, 10, 2), date(2025, 11, 10)) == [date(2025, 11, 1)]
    assert _honap1(date(2026, 2, 3), date(2026, 4, 10)) == [date(2026, 3, 1), date(2026, 4, 1)]


REGI = """SZÁMLARÉSZLETEZŐ
Fogyasztás összesen: 420 kWh
ESZ Lakossági A1 kedv. árszabás ára 2025.10.02-2025.11.10 276,00 kWh 5,2500 Ft/kWh 1 449 27 1 840
ESZ Lakossági A1 lakossági piaci ár 2025.10.02-2025.11.10 144,00 kWh 31,8000 Ft/kWh 4 579 27 5 815
Energiadíj összesen 2025.10.02-2025.11.10 6 028 7 655
Rendszerhasználati díjak (az elosztói alapdíj
kivételével) 2025.10.02-2025.11.10 420,00 kWh 23,4000 Ft/kWh 9 828 27 12 482
Elosztói alapdíj* 11 1,00 db 120,5000 Ft/db 121 27 154
Rendszerhasználati díjak összesen 9 949 12 636
Nettó számlaérték összesen 15 977
ÁFA összesítő (Ft)
Az elszámoló számlában elszámolt részszámlák sorszáma és a számla végösszege:
Sorszám: Számla végösszege (Ft):
011500000010 12 062 Ft
"""
UJ = """SZÁMLARÉSZLETEZŐ
Fogyasztás összesen: "H" 823 kWh
ESZ "H" árszabás ára2026.02.03-2026.04.15349kWh1,9000 Ft/kWh66327 842
ESZ "H" árszabás ára2026.04.16-2026.07.31414kWh5,2500 Ft/kWh2.17427 2.761
ESZ "H" árszabás ára2026.08.01-2026.08.0860 kWh5,2500 Ft/kWh31527 400
Energiadíj összesen 3.152 4.003
Átviteli forgalmi díj "H"2026.02.03-2026.04.15349kWh3,3900 Ft/kWh1.18327 1.502
Elosztói alapdíj "H"*2026.02.03-2026.04.152 hó 39,5000 Ft/hó7927 100
Elosztói alapdíj "H"*2026.04.16-2026.08.084 hó 120,5000 Ft/hó48227 612
Rendszerhasználati díjak összesen17.30021.970
ÁFA összesítő (Ft)
"""


def test_mvm_tetelek_regi_es_uj_formatum():
    r = mvm_tetelek(REGI, (date(2025, 10, 2), date(2025, 11, 10)), date(2025, 11, 11))
    assert (r["kiszamlazott_kwh"], r["kedvezmenyes"], r["piaci"], r["energia_brutto"], r["rhd_brutto"]) == ("420", "276.00", "144.00", "7655", "12636")
    assert r["alapdij"] == {"2025-11": "154"}
    u = mvm_tetelek(UJ, (date(2026, 2, 3), date(2026, 8, 8)), date(2026, 8, 31))
    assert (u["kiszamlazott_kwh"], u["teli"], u["kedvezmenyes"], u["energia_brutto"], u["rhd_brutto"]) == ("823", "349", "474", "4003", "21970")
    assert sum(Decimal(v) for v in u["alapdij"].values()) == 712 and len(u["alapdij"]) == 6
    assert mvm_levont_szamlak(REGI) == [("011500000010", Decimal(12062))]
    assert r["kedv_tetelek"] == [["2025-10-02", "2025-11-10", "276.00"]]
    assert u["kedv_tetelek"] == [["2026-04-16", "2026-07-31", "414"], ["2026-08-01", "2026-08-08", "60"]]


def test_mvm_tetelek_savkorrekcio_a_kedvezmenyes_tetelek_kozott():
    szoveg = """SZÁMLARÉSZLETEZŐ
Fogyasztás összesen: "A1" 33 kWh
ESZ Lakossági "A1" kedv. árszabás ára 2026.04.11-2026.07.31 30 kWh 5,2500 Ft/kWh 158 27 201
ESZ Lakossági "A1" kedv. árszabás ára 2026.08.01-2026.08.08 3 kWh 5,2500 Ft/kWh 16 27 20
ESZ Lakossági "A1" kedv. árszabás ára sávkorrekció 2026.04.11-2026.07.31 173 kWh 5,2500 Ft/kWh 908 27 1.153
ESZ Lakossági "A1" lakossági piaci ár sávkorrekció 2026.04.11-2026.07.31 -173 kWh 31,8000 Ft/kWh -5.501 27 -6.986
Energiadíj összesen -4.419 -5.612
Rendszerhasználati díjak összesen 1.254 1.592
ÁFA összesítő (Ft)
"""
    t = mvm_tetelek(szoveg, (date(2026, 4, 11), date(2026, 8, 8)), date(2026, 8, 17))
    assert (t["kedvezmenyes"], t["piaci"]) == ("206", "-173")
    assert t["kedv_tetelek"] == [["2026-04-11", "2026-07-31", "30"], ["2026-08-01", "2026-08-08", "3"], ["2026-04-11", "2026-07-31", "173"]]


def test_kesobbi_szamla_csak_potlasnal_kell():
    from kimutatas import kesobbi_szamla_kell
    k = _potlasos_ev()
    assert kesobbi_szamla_kell(k, date(2026, 7, 31))           # a szept. 10-i számla pótol
    assert not kesobbi_szamla_kell(k, date(2026, 9, 29))       # utána már nincs mit pótolni
    assert not kesobbi_szamla_kell({"megallapitasok": [{"tipus": "sav_hiany", "tol": "2026-08-01"}]}, date(2026, 7, 31))


def _pont(t):
    return lambda c: sorted((date.fromisoformat(n), Decimal(str(v))) for n, v in t.get(c, {}).items())


def _hatarszamla(tol, ig, **tetelek):
    return {"tipus": "elszamolo", "idoszak": [tol, ig], "kelte": ig, "tetelek": tetelek}


def test_evhatar_a_szamla_tetelbontasabol():
    from kimutatas import evhatar_allasok
    sz = {"a": _hatarszamla("2025-07-09", "2025-08-10", kedv_tetelek=[["2025-07-09", "2025-07-31", "159"], ["2025-08-01", "2025-08-10", "69"]],
                            piaci_tetelek=[["2025-07-09", "2025-07-31", "86"], ["2025-08-01", "2025-08-10", "38"]])}
    u = evhatar_allasok("villany/a1", sz, _pont({"vetelezes": {"2025-07-08": 15391, "2025-08-10": 15743}}))
    assert u == [{"datum": "2025-07-31", "csatorna": "vetelezes", "allas": 15636.0, "sorszam": "a", "mod": "tetelek"}]


def test_evhatar_a_rogzitett_meroallasbol_ha_a_tetelek_nem_adjak_ki():
    from kimutatas import evhatar_allasok
    sz = {"b": _hatarszamla("2026-04-11", "2026-08-08", kedv_tetelek=[["2026-04-11", "2026-07-31", "30"], ["2026-08-01", "2026-08-08", "3"]])}
    t = {"vetelezes": {"2026-04-10": 18827, "2026-07-31": 20028, "2026-08-08": 20061}}
    assert [(x["allas"], x["mod"]) for x in evhatar_allasok("villany/a1", sz, _pont(t))] == [(20028.0, "mero")]
    del t["vetelezes"]["2026-07-31"]
    assert evhatar_allasok("villany/a1", sz, _pont(t)) == []     # 33 kWh a tételeken, 1234 a mérőn: nem számolható


def test_evhatar_h_felcserelt_regiszterbol_nem_szamol_a_javitottbol_igen():
    from kimutatas import evhatar_allasok
    t = {"h_teli": {"2026-02-03": 0, "2026-08-08": 474}, "h_nyari": {"2026-02-03": 0, "2026-08-08": 349}}
    rossz = {"e": _hatarszamla("2026-02-03", "2026-08-08", teli_tetelek=[["2026-02-03", "2026-04-15", "349"]],
                               kedv_tetelek=[["2026-04-16", "2026-07-31", "414"], ["2026-08-01", "2026-08-08", "60"]])}
    assert evhatar_allasok("villany/h", rossz, _pont(t)) == []
    jo = {"e": _hatarszamla("2026-02-03", "2026-08-08", teli_tetelek=[["2026-02-03", "2026-04-15", "474"]],
                            kedv_tetelek=[["2026-04-16", "2026-07-31", "300"], ["2026-08-01", "2026-08-08", "49"]])}
    assert {(x["datum"], x["csatorna"]): x["allas"] for x in evhatar_allasok("villany/h", jo, _pont(t))} == {
        ("2026-04-15", "h_nyari"): 0.0, ("2026-04-15", "h_teli"): 474.0, ("2026-07-31", "h_nyari"): 300.0}


def test_tetel_reszek_a_kovetkezo_ev_hataran_is_bont():
    from kimutatas import _tetel_reszek
    assert _tetel_reszek(date(2025, 9, 10), date(2026, 9, 9), "08-01") == [(date(2025, 9, 10), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 9, 9))]
    assert _tetel_reszek(date(2026, 2, 4), date(2026, 9, 29), "08-01") == [(date(2026, 2, 4), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 9, 29))]
    assert _tetel_reszek(date(2026, 2, 4), date(2026, 3, 1), "08-01") == [(date(2026, 2, 4), date(2026, 3, 1))]
    assert _tetel_reszek(date(2026, 2, 4), date(2026, 9, 29), None) == [(date(2026, 2, 4), date(2026, 9, 29))]


def test_tarolt_pontok_mérocsere_folytonos():
    from kimutatas import tarolt_pontok
    t = {"merok": [
        {"beepitve": "2026-01-10", "kezdo_allas": "0", "leolvasasok": [{"datum": "2026-03-01", "allas": 400}]},
        {"beepitve": "2020-01-01", "kezdo_allas": "50000", "kiszerelve": "2026-01-10", "zaro_allas": "50900", "leolvasasok": []},
    ]}
    p = dict(tarolt_pontok(t, "vetelezes", folytonos=True))
    assert p[date(2026, 3, 1)] - p[date(2020, 1, 1)] == 1300  # 900 a régin + 400 az újon
    nyers = dict(tarolt_pontok(t, "vetelezes"))
    assert nyers[date(2026, 3, 1)] == 400 and nyers[date(2020, 1, 1)] == 50000
    egy = {"merok": [{"beepitve": "2020-01-01", "kezdo_allas": "5", "leolvasasok": [{"datum": "2020-02-01", "allas": 9}]}]}
    assert tarolt_pontok(egy, "vetelezes", folytonos=True) == tarolt_pontok(egy, "vetelezes")


def test_szokoev_kerete():
    from kimutatas import _ev_napok
    assert _ev_napok(date(2027, 9, 1), "08-01") == 366 and _ev_napok(date(2028, 7, 31), "08-01") == 366
    assert _ev_napok(date(2028, 8, 1), "08-01") == 365 and _ev_napok(date(2026, 1, 1), "08-01") == 365
    assert _ev_napok(date(2028, 5, 1), None) == 366 and _ev_napok(date(2027, 5, 1), None) == 365


def _a1_kimutatas(szamlak, allasok, tol, ig):
    return kimutatas("villany/a1", date.fromisoformat(tol), date.fromisoformat(ig), _allas({"vetelezes": allasok}), szamlak, arak, tetel_hatar="08-01")


def test_a_meres_elott_indulo_szamla_nem_ad_hamis_potlast():
    sz = {"1": _sz("2025-10-01", "2026-01-31", "2026-02-02", 800, 800, 0, 4200, 18720, {})}
    k = _a1_kimutatas(sz, {"2025-11-01": 100, "2026-01-31": 700}, "2025-11-01", "2026-01-31")
    s = k["sorok"][0]
    assert s["csonka"] and s["szamla_tol"] == "2025-10-01"
    assert [m["tipus"] for m in k["megallapitasok"] if m["tipus"] in ("potolt_fogyasztas", "csonka")] == ["csonka"]
    # Ha a mérés a számla elejétől megvan (legfeljebb egy nap eltérés), nem csonka.
    k = _a1_kimutatas(sz, {"2025-09-30": 0, "2026-01-31": 800}, "2025-09-30", "2026-01-31")
    assert not k["sorok"][0]["csonka"]


def test_regi_formaju_szamla_tetelei_nem_jelentenek_hianyt():
    x = _sz("2023-10-07", "2024-10-01", "2024-10-05", 3000, 428, 185, 1000, 2000, {}) | {"sorszam": "regi"}
    # Kiszámlázott mennyiség nélkül, a tételek a számla végére dátumozva (valódi régi számla szerkezete).
    x["tetelek"] |= {"kiszamlazott_kwh": None, "kedv_tetelek": [["2024-08-01", "2024-10-01", "428"]], "piaci_tetelek": [["2024-08-01", "2024-10-01", "185"]], "teli_tetelek": []}
    k = _a1_kimutatas({"regi": x}, {"2023-10-06": 0, "2024-07-31": 3190, "2024-10-01": 3600}, "2023-10-06", "2024-10-01")
    assert all(e["hiany"] is None for e in k["kedv_evek"])
    assert not [m for m in k["megallapitasok"] if m["tipus"] == "sav_hiany"]
    pontok = lambda c: [(date(2023, 10, 6), Decimal(0)), (date(2024, 7, 31), Decimal(3190)), (date(2024, 10, 1), Decimal(3600))]
    j = jogi_idoszakok("villany/a1", date(2026, 11, 7), pontok, _allas({"vetelezes": {"2023-10-06": 0, "2024-07-31": 3190, "2024-10-01": 3600, "2023-07-31": 0}}), {"regi": x}, arak, valasztott=date(2023, 8, 1))
    e = next(v for v in j if v["nev"] == "2023/2024")
    assert e["hiany"] is None and e["hiany_ft"] == 0
