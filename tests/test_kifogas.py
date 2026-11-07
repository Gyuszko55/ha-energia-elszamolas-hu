"""Számlakifogás-tervezet (kifogas.py): az éves kimutatás és a közös folyószámla alapján; kitalált sorszámokkal."""
from datetime import date
from decimal import Decimal

import tests.conftest  # noqa: F401
from kifogas import magyarazott_elteres, tervezet
from kimutatas import kimutatas
from tests.test_kimutatas import A1, H, _allas, _potlasos_ev, _sz, arak


def _bovit(k, dijak=None):
    return k | {"fiok": "Villany A1", "ugyfel": {"azonosito": "1", "nev": "Teszt Elek"}, "mero": "M", "szolgaltato": "MVM Démász",
                "dijak": dijak or {"a1": A1}, "keret_ev": 2523, "allasok": {}}


def _kivonat(sorok=None, tetelek=None, kozos=True):
    return {"nev": "A1 + H", "kozos": kozos, "nyito": {"osszeg": 0}, "zaro": 0.0, "tetelek": tetelek or [],
            "teljesites": {"sorok": sorok or []}}


JEGYZEK = [
    {"sorszam": "e0", "kelte": "2025-10-13", "tipus": "elszamolo", "fiok": "A1", "idoszak": ["2025-09-10", "2025-10-01"], "szamlaertek": 1, "fizetendo": 1, "allapot_nev": "fizetve", "fizetve": None},
    {"sorszam": "1", "kelte": "2025-11-11", "tipus": "elszamolo", "fiok": "A1", "idoszak": ["2025-10-02", "2025-11-10"], "szamlaertek": 2, "fizetendo": 2, "allapot_nev": "fizetve", "fizetve": {"datum": "2025-11-24"}},
    {"sorszam": "st", "kelte": "2026-02-27", "tipus": "storno", "fiok": "A1", "idoszak": ["2026-01-13", "2026-02-02"], "szamlaertek": -5, "fizetendo": 0, "allapot_nev": "sztornó", "fizetve": None},
]
TETELEK = [
    {"datum": "2025-10-13", "fajta": "szamla", "sorszam": "e0", "megnevezes": "x", "kovetel": 1.0, "tartozik": 0.0, "egyenleg": 1.0},
    {"datum": "2025-10-27", "fajta": "befizetes", "sorszam": "e0", "megnevezes": "b", "kovetel": 0.0, "tartozik": 1.0, "egyenleg": 0.0},
    {"datum": "2025-11-11", "fajta": "szamla", "sorszam": "1", "megnevezes": "x", "kovetel": 2.0, "tartozik": 0.0, "egyenleg": 2.0, "szolgaltato_egyenleg": 2.0, "elteres": 0},
    {"datum": "2025-11-24", "fajta": "befizetes", "sorszam": "1", "megnevezes": "b", "kovetel": 0.0, "tartozik": 2.0, "egyenleg": 0.0},
]


def test_potlasos_ev_tervezete():
    t = tervezet(_bovit(_potlasos_ev()), _kivonat(JEGYZEK, TETELEK))
    assert t["allapot"] == "kesz" and not [f for f in t["figyelmeztetesek"] if f["blokkolo"]]
    assert t["targy_szamlak"] == ["8"]                      # a kifogás a pótló számlára szól
    assert t["osszeg"]["irany"] == "javamra" and t["osszeg"]["ft"] == 19220 and abs(t["osszeg"]["szamlasorok_ft"] - 19220) < 50
    assert any("19\u00a0220\u00a0Ft-ra" in x for x in t["kerelmek"])
    assert "4 413 kWh" in t["lenyeg"] and "1 937 kWh" in t["lenyeg"] and "2 507 kWh" in t["lenyeg"]
    # A kimaradt és a pótolt sor egymást ellentételezi: külön forint nem szerepel náluk, a sáv hiánya igen.
    assert not any("hatása" in o for o in t["okok"] if "6 sz." in o or "8 sz." in o)
    assert any("570 kWh piaci áron" in o for o in t["okok"])
    assert "a fogyasztás mennyiségét" in t["nem_vitatott"]
    assert any("térítsék vissza" in x for x in t["kerelmek"]) and any("közös folyószámlá" in x for x in t["kerelmek"])
    # Jegyzék: a sztornó benne van, az előző évi számla nincs; a folyószámla-ablak az első évbeli számlától indul.
    assert [x["sorszam"] for x in t["szamlajegyzek"]] == ["1", "st"]
    f = t["folyoszamla"]
    assert f["sorok"][0]["sorszam"] == "1" and f["nyito"] == 0.0 and f["befizetes"] == 2.0


def test_nyomtatott_egyenleg_elteres_megallitja():
    rossz = [dict(TETELEK[2]) | {"elteres": 500, "szolgaltato_egyenleg": 2.0}]
    t = tervezet(_bovit(_potlasos_ev()), _kivonat(JEGYZEK, rossz))
    assert t["allapot"] == "nem_keszitheto" and "lenyeg" not in t
    assert any(f["blokkolo"] and "nyomtatott" in f["szoveg"] for f in t["figyelmeztetesek"])


def test_hianyzo_idoszak_megallitja():
    allasok = {"vetelezes": {"2026-05-31": 1000, "2026-06-30": 1100, "2026-07-31": 1200, "2026-08-31": 1300}}
    szamlak = {"a": _sz("2026-06-01", "2026-06-30", "2026-07-01", 100, 100, 0, 0, 0, {}), "c": _sz("2026-08-01", "2026-08-31", "2026-09-01", 100, 100, 0, 0, 0, {})}
    k = kimutatas("villany/a1", date(2026, 5, 31), date(2026, 8, 31), _allas(allasok), szamlak, arak)
    t = tervezet(_bovit(k), _kivonat())
    assert t["allapot"] == "nem_keszitheto" and any("Hiányzó időszak" in f["szoveg"] for f in t["figyelmeztetesek"])


def test_meg_nem_magyarazhato_elteres_megallitja():
    k = _bovit(_potlasos_ev())
    k["osszesen"] = k["osszesen"] | {"mvm": k["osszesen"]["mvm"] + 5000}
    t = tervezet(k, _kivonat(JEGYZEK, TETELEK))
    assert t["allapot"] == "nem_keszitheto" and any("nem vezethető le" in f["szoveg"] for f in t["figyelmeztetesek"])


def test_nincs_elteres():
    allasok = {"vetelezes": {"2026-05-31": 1000, "2026-06-30": 1100}}
    szamlak = {"a": _sz("2026-06-01", "2026-06-30", "2026-07-01", 100, 100, 0, 845, 2972, {})}
    k = kimutatas("villany/a1", date(2026, 5, 31), date(2026, 6, 30), _allas(allasok), szamlak, arak)
    k["osszesen"] = k["osszesen"] | {"mvm": k["osszesen"]["helyes"]}
    k["megallapitasok"] = []
    assert tervezet(_bovit(k), _kivonat())["allapot"] == "nincs_elteres"


def test_h_regisztercsere_levezetese():
    allasok = {"h_teli": {"2026-02-03": 0, "2026-08-08": 474, "2026-09-29": 474}, "h_nyari": {"2026-02-03": 0, "2026-08-08": 349, "2026-09-29": 527}}
    szamlak = {"e": _sz("2026-02-03", "2026-08-08", "2026-08-31", 823, 474, 0, 4003, 21970,
                        {"2026-03": "50", "2026-04": "50", "2026-05": "153", "2026-06": "153", "2026-07": "153", "2026-08": "153"}, teli=349)}
    k = kimutatas("villany/h", date(2026, 2, 3), date(2026, 9, 29), _allas(allasok), szamlak, arak, kezdo=True)
    b = _bovit(k, {"a1": A1, "h": H})
    assert abs(magyarazott_elteres(b) - 1678) < 2
    t = tervezet(b, _kivonat())
    assert t["allapot"] == "kesz" and t["targy_szamlak"] == ["e"] and "még nincs számlám" in t["fuggo_szoveg"]
    assert any("regiszter" in o and "hatása" in o for o in t["okok"]) and Decimal(t["osszeg"]["ft"]) == 1678


def test_jogalap_es_erveles_potlasnal():
    t = tervezet(_bovit(_potlasos_ev()), _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    cimek = " | ".join(j["cim"] for j in t["jogalap"])
    assert "4/2011. (I. 31.) NFM rendelet 6. § (1)" in cimek and "6. § (3)" in cimek and "6. § (4)" in cimek
    assert "M.1. melléklet" in cimek and "tájékoztatója" in cimek and "259/2022" not in cimek
    e = " ".join(t["erveles"])
    assert "1\u00a0201\u00a0kWh" in e and "112 napos" in e and "774\u00a0kWh" in e and "2523 ÷ 365 × 112" in e
    assert "20 napos" in e and "138\u00a0kWh" in e and "2025/2026. kedvezményes évből a 2026/2027." in e
    assert "15 napos" in t["valasz"] and any("8 napon belül" in x for x in t["kerelmek"])
    assert not t["figyelmeztetesek"]


def _jogi_ev(**x):
    return {"fajta": "ev", "nev": "2025/2026", "allapot": "lezart", "tol": "2025-08-01", "ig": "2026-07-31", "nap": 365, "nap_eddig": 365, "mert": 4392.0, "keret_szamlazva": 2523,
            "szamla_kedvezmenyes": 1952.0, "szamla_piaci": 1269.0, "szamla_teli": None, "hiany": 571.0, "hiany_ft": 19253, "reszek": []} | x


def test_a_level_a_jogszabaly_szerinti_evhez_igazodik():
    b = _bovit(_potlasos_ev()) | {"valasztott": "2025-08-01", "jogi_idoszakok": [_jogi_ev()]}
    t = tervezet(b, _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    assert t["allapot"] == "kesz" and t["keret_hiany"] and (t["tol"], t["ig"]) == ("2025-08-01", "2026-07-31")
    assert t["osszeg"]["ft"] == 19253 and t["osszeg"]["irany"] == "javamra" and t["idoszak"]["nev"] == "2025/2026"
    assert "2025/2026. kedvezményes évben" in t["lenyeg"] and "4\u00a0392\u00a0kWh" in t["lenyeg"] and "571\u00a0kWh hiányzik" in t["lenyeg"] and "19\u00a0253\u00a0Ft" in t["lenyeg"]
    assert any("19\u00a0253\u00a0Ft-ra" in x for x in t["kerelmek"]) and any("kedvezményes évre és az azt követő számlákra" in x for x in t["kerelmek"])
    # A sáv-hiány egyszer, az év számaival szerepel; a pótlás története és az érvelés megmarad.
    assert not any("570 kWh piaci áron" in o for o in t["okok"]) and sum("hiányzik" in o for o in t["okok"]) == 1
    assert any("korábbi fogyasztást pótol" in o for o in t["okok"]) and t["erveles"]
    assert not any("259/2022" in j["cim"] for j in t["jogalap"])


def test_ha_nincs_jogi_sor_vagy_tetel_marad_a_szamlak_szerinti_level():
    b = _bovit(_potlasos_ev())
    t = tervezet(b, _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    assert not t["keret_hiany"] and t["idoszak"] is None and t["osszeg"]["ft"] == 19220
    t2 = tervezet(b | {"valasztott": "2025-08-01", "jogi_idoszakok": [_jogi_ev(hiany=None, hiany_ft=0)]}, _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    assert not t2["keret_hiany"] and t2["osszeg"]["ft"] == 19220 and t2["allapot"] == "kesz"


def test_ha_a_hiany_masik_evben_van_oda_kuld():
    e27 = _jogi_ev(nev="2026/2027", allapot="folyamatban", tol="2026-08-01", ig="2027-07-31", hiany=1.0, hiany_ft=0)
    t = tervezet(_bovit(_potlasos_ev()) | {"valasztott": "2026-08-01", "jogi_idoszakok": [e27]}, _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    assert t["allapot"] == "nincs_elteres" and t["masik_ev"] == "2025/2026" and "lenyeg" not in t


def test_jogi_hivatkozas_elavul():
    t = tervezet(_bovit(_potlasos_ev()), _kivonat(JEGYZEK, TETELEK), date(2028, 1, 1))
    assert any("hivatkozásokat legutóbb" in f["szoveg"] and not f["blokkolo"] for f in t["figyelmeztetesek"])
    assert t["allapot"] == "kesz"


def test_nem_mvm_szolgaltatonal_nincs_mvm_hivatkozas():
    b = _bovit(_potlasos_ev()) | {"szolgaltato": "Más Szolgáltató"}
    t = tervezet(b, _kivonat(JEGYZEK, TETELEK), date(2026, 11, 6))
    assert not any("MVM" in j["cim"] for j in t["jogalap"]) and t["valasz"] == "Válaszukat írásban kérem."
    assert not any("8 napon belül" in x for x in t["kerelmek"])


def test_2025_aug_elotti_idoszak_regi_rendeletre_is_hivatkozik():
    allasok = {"vetelezes": {"2025-05-31": 1000, "2025-06-30": 1500}}
    szamlak = {"a": _sz("2025-06-01", "2025-06-30", "2025-07-01", 500, 100, 400, 0, 0, {})}
    k = kimutatas("villany/a1", date(2025, 5, 31), date(2025, 6, 30), _allas(allasok), szamlak, arak)
    k["megallapitasok"] = [{"tipus": "elteres", "sorszam": "a", "tol": "2025-06-01", "ig": "2025-06-30", "hatas_ft": 500, "szoveg": "x"}]
    # A számla díja a mennyiségekből levezethető legyen: csak a szöveges ágat vizsgáljuk.
    o = k["osszesen"]
    k["osszesen"] = o | {"kedvezmenyes": o["mvm_kedvezmenyes"], "piaci": o["mvm_piaci"], "mert": o["kiszamlazott"], "mvm": o["helyes"]}
    t = tervezet(_bovit(k), _kivonat(), date(2026, 11, 6))
    assert t["allapot"] == "kesz"
    assert any("259/2022" in j["cim"] for j in t["jogalap"]) and any("259/2022" in f["szoveg"] for f in t["figyelmeztetesek"])
    assert t["erveles"] == []


def test_h_nem_kap_potlas_ervelest_es_aug_julius_hivatkozast():
    allasok = {"h_teli": {"2026-02-03": 0, "2026-08-08": 474, "2026-09-29": 474}, "h_nyari": {"2026-02-03": 0, "2026-08-08": 349, "2026-09-29": 527}}
    szamlak = {"e": _sz("2026-02-03", "2026-08-08", "2026-08-31", 823, 474, 0, 4003, 21970,
                        {"2026-03": "50", "2026-04": "50", "2026-05": "153", "2026-06": "153", "2026-07": "153", "2026-08": "153"}, teli=349)}
    k = kimutatas("villany/h", date(2026, 2, 3), date(2026, 9, 29), _allas(allasok), szamlak, arak, kezdo=True)
    t = tervezet(_bovit(k, {"a1": A1, "h": H}), _kivonat(), date(2026, 11, 6))
    assert not any("6. § (3)" in j["cim"] for j in t["jogalap"]) and "fűtési idényen kívüli" in t["jogalap"][0]["szoveg"] and t["erveles"] == []


def test_negativ_es_csonka_sor_megallitja():
    for extra, resz in (({"mert": -49600}, "negatív"), ({"csonka": True, "szamla_tol": "2025-10-01"}, "nem vethető össze")):
        k = _potlasos_ev()
        k["sorok"][0] |= extra
        t = tervezet(_bovit(k), _kivonat(JEGYZEK, TETELEK))
        assert t["allapot"] == "nem_keszitheto" and any(resz in f["szoveg"] and f["blokkolo"] for f in t["figyelmeztetesek"])


def test_merocsere_figyelmeztet():
    t = tervezet(_bovit(_potlasos_ev()) | {"merocsere": True}, _kivonat(JEGYZEK, TETELEK))
    assert any("Mérőcsere" in f["szoveg"] and not f["blokkolo"] for f in t["figyelmeztetesek"])


def test_lenyeg_a_szamlazott_napig_veti_ossze():
    from kifogas import _lenyeg_jogi
    j = {"nev": "2026/2027", "tol": "2026-08-01", "ig": "2027-07-31", "nap": 365, "mert": 943.0, "mert_szamlazva": 600.0, "keret_szamlazva": 415, "szamla_kedvezmenyes": 300.0, "hiany": 115.0, "hiany_ft": 3800}
    assert "600\u00a0kWh" in _lenyeg_jogi(j) and "943" not in _lenyeg_jogi(j)
