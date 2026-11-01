"""Éves elszámolási kimutatás (kimutatas.py) és az MVM-számlatételek olvasása (szamlak.mvm_tetelek) – a valódi
MVM-számlák szerkezetével és számaival (Kertes ház A1 2025/26, H 2026), kitalált sorszámokkal."""
from datetime import date
from decimal import Decimal

import tests.conftest  # noqa: F401
from kimutatas import _honap1, ev_jeloltek, kimutatas
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


def test_ev_jeloltek_es_honapok():
    assert ev_jeloltek([date(2024, 10, 1), date(2025, 10, 1), date(2026, 9, 29)]) == [
        (date(2025, 10, 1), date(2026, 9, 29)), (date(2024, 10, 1), date(2025, 10, 1))]
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
