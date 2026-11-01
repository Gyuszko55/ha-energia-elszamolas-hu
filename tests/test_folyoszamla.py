"""Folyószámla-kivonat: nyitó egyenleg az áthozott sorból, számla a Követel, befizetés a Tartozik oszlopban; MVM
közös folyószámla (A1 + H) együtt; kötbér és kamat új mozgás; a szolgáltató szerinti egyenleggel való egyezés."""
from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from folyoszamla import kivonat, kozos_csoport

MA = date(2026, 10, 6)


def test_athozott_egyenleg_nyito_es_zaro():
    """ALFÖLDVÍZ-szerű: az első (elszámoló) számla 9 876 Ft, a „figyelembe vett túlfizetés” −6 778 → nyitó −6 778,
    fizetendő 3 098; befizetés után 0. Utána egy részszámla, amely még nincs fizetve (nyitott)."""
    sz = {
        "E1": {"kelte": "2025-02-19", "tipus": "elszamolo", "osszeg": "3098", "szamlaertek": "9876", "hatarido": "2025-03-14",
               "idoszak": ["2024-02-13", "2025-02-10"], "elszamolt_viz": {"ivoviz": "16", "csatorna": "16"},
               "egyeb_tetelek": [["figyelembe vett hátralék/túlfizetés", "-6778"]]},
        "R1": {"kelte": "2026-09-01", "tipus": "resz", "osszeg": "604", "szamlaertek": "604", "hatarido": "2026-09-30"},
    }
    k = kivonat("v", {"v": ("Víz", sz)}, {"E1": {"fizetve": True, "datum": "2025-03-10", "forras": "kezi"}}, None, MA)
    assert k["nyito"]["osszeg"] == -6778
    assert [(t["fajta"], t["kovetel"], t["tartozik"], t["egyenleg"]) for t in k["tetelek"]] == [
        ("szamla", 9876, 0, 3098), ("befizetes", 0, 3098, 0), ("szamla", 604, 0, 604)]
    assert k["tetelek"][0]["mennyiseg"] == "ivóvíz 16 m³" and k["zaro"] == 604


def test_feltetelezett_befizetes_es_kezi_nyito():
    """90 napnál régebben lejárt, fizetési adat nélküli számla: feltételezett befizetés a határidőn; kézi nyitó felülír."""
    sz = {"R": {"kelte": "2026-01-10", "tipus": "resz", "osszeg": "1000", "hatarido": "2026-01-31"}}
    k = kivonat("x", {"x": ("X", sz)}, {}, {"datum": "2026-01-01", "osszeg": 250}, MA)
    assert k["nyito"] == {"datum": "2026-01-01", "osszeg": 250.0, "forras": "kézzel megadva"}
    assert k["tetelek"][1]["forras"] == "feltetelezett" and k["tetelek"][1]["datum"] == "2026-01-31" and k["zaro"] == 250


def test_mvm_kozos_folyoszamla_kotber_kamat_es_szolgaltato_egyenleg():
    """MVM A1 + H egy folyószámlán (azonos ügyfél-azonosító): az A1 elszámoló jóváírása (−48 129) után a H elszámolón a
    „túlfizetés”, az A1 következő számláján a „csökkentő tétel” áthozott egyenleg (nem új tétel); a kötbér tartozik-,
    a kamat követel-tétel; minden ponton egyezik a számlán közölt folyószámla-egyenleggel."""
    u = {"azonosito": "111"}
    a1 = {"A": {"kelte": "2026-08-17", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-48129", "szamlaertek": "-48129",
                "folyoszamla": "-48129", "ugyfel": u},
          "A2": {"kelte": "2026-09-21", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-7382", "szamlaertek": "23125",
                 "folyoszamla": "-7382", "ugyfel": u, "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-25522"],
                                                                         ["Késedelmi kamat", "15"], ["Kötbér garantált szolgáltatás elmaradása miatt", "-5000"]]}}
    h = {"H": {"kelte": "2026-08-31", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-25522", "szamlaertek": "22607",
               "folyoszamla": "-25522", "ugyfel": u, "egyeb_tetelek": [["Túlfizetés", "-48129"]]}}
    hz = {"a1": ("Villany A1", a1), "h": ("Villany H", h), "g": ("Gáz", {})}
    assert kozos_csoport("h", hz) == ["a1", "h"]
    k = kivonat("a1", hz, {}, None, MA)
    assert k["kozos"] and k["nev"] == "Villany A1 + Villany H"
    assert [(t["megnevezes"][:11], t["kovetel"], t["tartozik"]) for t in k["tetelek"]] == [
        ("Elszámoló s", 0, 48129), ("Elszámoló s", 22607, 0), ("Elszámoló s", 23125, 0), ("Késedelmi k", 15, 0), ("Kötbér gara", 0, 5000)]
    assert [t.get("elteres") for t in k["tetelek"] if t.get("szolgaltato_egyenleg") is not None] == [0, 0, 0]
    assert k["zaro"] == -7382


def test_kezi_egyezteto_tetel():
    """Kézi könyvelési tétel (egyeztetés a szolgáltató egyenlegével): a nap végi egyenlegbe beszámít, az eltérés eltűnik."""
    sz = {"R": {"kelte": "2026-05-22", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "1492", "szamlaertek": "11689",
                "folyoszamla": "1492", "ugyfel": {"azonosito": "9"}}}
    k = kivonat("x", {"x": ("X", sz)}, {}, None, MA)
    assert k["tetelek"][0]["elteres"] == 10197
    k = kivonat("x", {"x": ("X", sz)}, {}, None, MA, [{"id": "e1", "datum": "2026-05-22", "megnevezes": "Egyeztetés", "kovetel": 0, "tartozik": 10197}])
    assert [t["fajta"] for t in k["tetelek"]] == ["szamla", "kezi", "befizetes"] or [t["fajta"] for t in k["tetelek"]][:2] == ["szamla", "kezi"]
    assert k["tetelek"][0]["elteres"] == 0


def test_tamogatas_eloszor_mozgas_utana_athozott():
    """MVM: az első „Támogatás” új jóváírás (tartozik), a következő számlákon az előző mínuszos fizetendőt hozza át
    (nem új tétel) – akár „Kötbér…” néven is."""
    u = {"azonosito": "7"}
    sz = {
        "1": {"kelte": "2026-05-12", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-1186", "szamlaertek": "812",
              "folyoszamla": "-1186", "ugyfel": u, "egyeb_tetelek": [["Támogatás", "-1998"]]},
        "2": {"kelte": "2026-06-10", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-632", "szamlaertek": "554",
              "folyoszamla": "-632", "ugyfel": u, "egyeb_tetelek": [["Támogatás", "-1186"]]},
        "3": {"kelte": "2026-07-09", "tipus": "resz", "forras": "mvm_aram", "osszeg": "1527", "szamlaertek": "2159",
              "folyoszamla": "1527", "ugyfel": u, "egyeb_tetelek": [["Kötbér garantált szolgáltatás elmaradása miatt", "-632"]]},
    }
    k = kivonat("x", {"x": ("Villany", sz)}, {}, None, MA)
    assert [t["megnevezes"][:9] for t in k["tetelek"]] == ["Elszámoló", "Támogatás", "Elszámoló", "Részszáml"]
    assert all(t["elteres"] == 0 for t in k["tetelek"] if "elteres" in t)


def test_oraallas_a_szamlarol():
    """A számlán szereplő induló → záró óraállás a kivonat megnevezése alatt, a leolvasás módjával (becsült is)."""
    from folyoszamla import oraallas

    x = {"allasok": [{"mero": "68027738", "indulo": ["2026-05-01", "64"], "zaro": ["2026-08-31", "68"], "lm": "Becs"}]}
    assert oraallas(x, "m³") == "óraállás 64 → 68 m³ (becsült)"
    assert oraallas({"allasok": [{"mero": "1", "indulo": None, "zaro": ["2026-07-28", "20520"], "lm": "Dikt"}]}, "kWh") == "óraállás záró 20520 kWh (diktált)"
    assert oraallas({}) is None


def test_teljesites_szamlankent():
    """Pénzügyi teljesítés: soronként egy számla (fizetendő, befizetés, állapot); a mínuszos fizetendő túlfizetés, ha egy
    későbbi számla beszámítja, „beszámítva”; összesítő: számlázva, fizetve, nyitott, lejárt."""
    sz = {
        "A": {"kelte": "2026-07-09", "tipus": "resz", "osszeg": "2000", "hatarido": "2026-07-25"},
        "B": {"kelte": "2026-08-13", "tipus": "elszamolo", "osszeg": "-1186", "szamlaertek": "812", "hatarido": "2026-08-28"},
        "C": {"kelte": "2026-09-09", "tipus": "resz", "osszeg": "1000", "szamlaertek": "2186", "hatarido": "2026-09-25",
              "egyeb_tetelek": [["Támogatás", "-1186"]]},
        "D": {"kelte": "2026-10-01", "tipus": "resz", "osszeg": "500", "hatarido": "2026-10-20"},
    }
    k = kivonat("x", {"x": ("X", sz)}, {"A": {"fizetve": True, "datum": "2026-07-20", "forras": "kezi"}}, None, MA)
    t = k["teljesites"]
    assert [(s["sorszam"], s["allapot"]) for s in t["sorok"]] == [("A", "fizetve"), ("B", "beszamitva"), ("C", "lejart"), ("D", "nyitott")]
    assert t["sorok"][1]["beszamitva"] == "C"
    assert t["osszesen"] == {"szamlazva": 3500.0, "fizetve": 2000.0, "nyitott": 1500.0, "lejart": 1000.0, "tulfizetes": 0.0}


def test_mvm_gaz_elszamolo_jovairas_reszszamlan_beszamitva():
    """MVM gáz: az elszámoló jóváírását (−8 835) a következő részszámla „Támogatás, túlfizetés” sorban számítja be
    (számlaérték 11 642, fizetendő 2 807). A beszámítás áthozott egyenleg – a jóváírás nem számít kétszer, záró 0."""
    sz = {"E": {"kelte": "2023-07-25", "tipus": "elszamolo", "forras": "mvm_gaz", "osszeg": "-8835", "szamlaertek": "-8835"},
          "R": {"kelte": "2023-08-23", "tipus": "resz", "forras": "mvm_gaz", "osszeg": "2807", "szamlaertek": "11642",
                "hatarido": "2023-09-07", "egyeb_tetelek": [["Támogatás, túlfizetés", "-8835"]]}}
    k = kivonat("g", {"g": ("Gáz", sz)}, {"R": {"fizetve": True, "datum": "2023-09-04", "forras": "dijnet"}}, None, MA)
    assert [(t["fajta"], t["kovetel"], t["tartozik"], t["egyenleg"]) for t in k["tetelek"]] == [
        ("szamla", 0, 8835, -8835), ("szamla", 11642, 0, 2807), ("befizetes", 0, 2807, 0)]
    assert k["zaro"] == 0


def test_dakov_befizetes_a_szamlan_kozolt_egyenlegbol():
    """DAKÖV: nincs fizetési adat, de minden számla közli a folyószámla egyenlegét. A két mínuszos elszámoló (−4 132,
    −1 472) jóváírását a DAKÖV a júniusi számla befizetésénél számította be (befizetés 3 855 a 9 459 helyett) – a
    visszafejtett befizetésekkel a kivonat minden ponton egyezik, záró 0, a jóváírások „beszámítva”."""
    def sz_(kelte, osszeg, egyenleg, hat):
        return {"kelte": kelte, "tipus": "resz", "forras": "dakov", "osszeg": str(osszeg), "folyoszamla": str(egyenleg), "hatarido": hat}
    sz = {"A": sz_("2025-03-31", 15653, 11521, "2025-04-25") | {"folyoszamla": "11521"},
          "N1": sz_("2025-02-27", -4132, -4132, "2025-03-26"),
          "N2": sz_("2025-04-28", -1472, 10049, "2025-05-26"),
          "B": sz_("2025-05-27", 8697, 3093, "2025-06-25"),
          "C": sz_("2025-06-27", 9459, 3855, "2025-07-25"),
          "D": sz_("2025-07-29", 6037, 6037, "2025-08-26")}
    k = kivonat("v", {"v": ("Víz", sz)}, {"D": {"fizetve": True, "datum": "2025-08-20", "forras": "kezi"}}, None, MA)
    befiz = {t["sorszam"]: (t["datum"], t["tartozik"], t["forras"]) for t in k["tetelek"] if t["fajta"] == "befizetes"}
    assert befiz["A"] == ("2025-04-28", 15653, "egyenleg") and befiz["B"][1] == 8697 and befiz["C"][1] == 3855
    assert befiz["D"] == ("2025-08-20", 6037, "kezi")
    assert all(not t.get("elteres") for t in k["tetelek"]) and k["zaro"] == 0
    allapot = {s["sorszam"]: (s["allapot"], s["beszamitva"]) for s in k["teljesites"]["sorok"]}
    assert allapot["N1"] == ("beszamitva", "C") and allapot["N2"] == ("beszamitva", "C") and allapot["C"][0] == "fizetve"


def test_dakov_kezi_jeloles_osszeg_az_egyenlegbol():
    """Kézzel „fizetve” jelölt DAKÖV-számla: a nap a jelölésé, az összeg a szolgáltató egyenlegéből (a jóváírással fedezett
    rész nélkül) – így a jóváírás nem ragad be. „Nincs fizetve” jelölésnél nincs befizetés."""
    def sz_(kelte, osszeg, egyenleg):
        return {"kelte": kelte, "tipus": "resz", "forras": "dakov", "osszeg": str(osszeg), "folyoszamla": str(egyenleg)}
    sz = {"N": sz_("2025-04-28", -5604, -5604), "B": sz_("2025-05-27", 8697, 3093), "C": sz_("2025-06-27", 9459, 3855),
          "D": sz_("2025-07-29", 6037, 6037)}
    kezi = {"C": {"fizetve": True, "datum": "2025-07-25", "forras": "kezi"}}
    k = kivonat("v", {"v": ("Víz", sz)}, kezi, None, MA)
    befiz = {t["sorszam"]: (t["datum"], t["tartozik"], t["forras"]) for t in k["tetelek"] if t["fajta"] == "befizetes"}
    assert befiz["C"] == ("2025-07-25", 3855, "kezi")
    k2 = kivonat("v", {"v": ("Víz", sz)}, {"C": {"fizetve": False, "forras": "kezi"}}, None, MA)
    assert "C" not in {t["sorszam"] for t in k2["tetelek"] if t["fajta"] == "befizetes"}

def test_mvm_kozos_tarifankent_kezi_befizetes_szamit():
    """Kertes ház 2026. aug.–szept. (valós sor): az A1 jóváírás (−48 129) után a júliusi részszámlákat (16 480 + 1 172)
    kézzel befizették, a H részszámla (991) is rendeződött. Tarifánkénti kivonatban a kézi befizetés számít – a közös
    folyószámla egyenlegéből nem fejtünk vissza befizetést (az a két tarifáé együtt) –, a két záró összege a számla szerinti
    −7 382."""
    u = {"azonosito": "111"}
    a1 = {"R": {"kelte": "2026-07-28", "tipus": "resz", "osszeg": "16480", "hatarido": "2026-08-10", "kezi": True},
          "A": {"kelte": "2026-08-17", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-48129", "szamlaertek": "-48129",
                "folyoszamla": "-30477", "ugyfel": u, "hatarido": "2026-08-25"},
          "A2": {"kelte": "2026-09-21", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-7382", "szamlaertek": "23125",
                 "folyoszamla": "-7382", "ugyfel": u, "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-25522"],
                                                                         ["Késedelmi kamat", "15"], ["Kötbér garantált szolgáltatás elmaradása miatt", "-5000"]]}}
    h = {"HR": {"kelte": "2026-07-28", "tipus": "resz", "osszeg": "1172", "hatarido": "2026-08-10", "kezi": True},
         "HR2": {"kelte": "2026-08-19", "tipus": "resz", "osszeg": "991", "kezi": True},
         "H": {"kelte": "2026-08-31", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-25522", "szamlaertek": "22607",
               "folyoszamla": "-25522", "ugyfel": u, "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-30477"], ["Túlfizetés", "-17652"]]}}
    hz = {"a1": ("Villany A1", a1), "h": ("Villany H", h)}
    fiz = {"R": {"fizetve": True, "datum": "2026-08-18", "forras": "kezi"}, "HR": {"fizetve": True, "datum": "2026-08-18", "forras": "kezi"},
           "HR2": {"fizetve": True, "datum": "2026-08-20", "forras": "kezi"}}
    ka = kivonat("a1", hz, fiz, None, MA, egyutt=False)
    kh = kivonat("h", hz, fiz, None, MA, egyutt=False)
    assert any(t["fajta"] == "befizetes" and t["tartozik"] == 16480 for t in ka["tetelek"])
    assert ka["zaro"] + kh["zaro"] == -7382 and kh["zaro"] == 0


def test_konyvelesi_csuszas_nem_elteres():
    """DAKÖV (Kertes ház 2026): a márciusi részszámlát 03-25-én fizették, de a 04-01-jei számla még nyitottnak mutatja (a szolgáltató
    késve könyvel) – a 8 013 Ft-os különbség a számla előtti 10 nap befizetése, ezért nem eltérés; fordítva is: ha a
    befizetést nálunk 1 nappal a számla utánra rögzítették, de a szolgáltató már lekönyvelte."""
    sz = {"R1": {"kelte": "2026-03-03", "tipus": "resz", "forras": "dakov", "osszeg": "8013", "szamlaertek": "8013",
                 "folyoszamla": "8013", "hatarido": "2026-03-25"},
          "R2": {"kelte": "2026-04-01", "tipus": "resz", "forras": "dakov", "osszeg": "3585", "szamlaertek": "3585",
                 "folyoszamla": "11598", "hatarido": "2026-04-23"},
          "E1": {"kelte": "2026-06-02", "tipus": "elszamolo", "forras": "dakov", "osszeg": "24616", "szamlaertek": "24616",
                 "folyoszamla": "24616", "hatarido": "2026-06-25"}}
    fiz = {"R1": {"fizetve": True, "datum": "2026-03-25", "forras": "kezi"},
           "R2": {"fizetve": True, "datum": "2026-04-23", "forras": "kezi"}}
    k = kivonat("v", {"v": ("Víz", sz)}, fiz, None, MA)
    r2 = next(t for t in k["tetelek"] if t.get("sorszam") == "R2" and t["fajta"] == "szamla")
    assert r2["elteres"] == 0 and r2["konyveles"] == {"irany": "meg_nem_konyvelt", "osszeg": 8013.0}
    assert all(t.get("elteres", 0) == 0 for t in k["tetelek"])
    sz2 = {"A": {"kelte": "2023-01-02", "tipus": "resz", "forras": "dakov", "osszeg": "3718", "szamlaertek": "3718", "folyoszamla": "3718"},
           "B": {"kelte": "2023-01-26", "tipus": "elszamolo", "forras": "dakov", "osszeg": "8621", "szamlaertek": "8621", "folyoszamla": "8621"}}
    k2 = kivonat("v", {"v": ("Víz", sz2)}, {"A": {"fizetve": True, "datum": "2023-01-27", "forras": "kezi"}}, None, MA)
    b = next(t for t in k2["tetelek"] if t.get("sorszam") == "B" and t["fajta"] == "szamla")
    assert b["elteres"] == 0 and b["konyveles"]["irany"] == "korabban_erkezett"


def test_mvm_kozos_kimutatas_storno_es_kiegyenlites():
    """Kertes ház, az MVM folyószámla-kimutatása szerint (2026. júl.–szept.): A1 + H egy kivonatban. A 991 Ft-os H
    részszámla fizetendője −47 138 (a túlfizetésből rendezett), majd stornózták – befizetés nincs rá, a stornó a saját
    számláját egyenlíti ki. A közös 17 652 Ft-os befizetés a júliusi két részszámlát; minden közölt egyenleg egyezik,
    a záró −7 382 (túlfizetés), mint a kimutatáson."""
    u = {"azonosito": "111"}
    a1 = {"R": {"kelte": "2026-07-28", "tipus": "resz", "osszeg": "16480", "hatarido": "2026-08-18", "kezi": True},
          "A": {"kelte": "2026-08-17", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-48129", "szamlaertek": "-48129",
                "folyoszamla": "-30477", "ugyfel": u, "hatarido": "2026-08-25"},
          "A2": {"kelte": "2026-09-21", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-7382", "szamlaertek": "23125",
                 "folyoszamla": "-7382", "ugyfel": u, "hatarido": "2026-10-05",
                 "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-25522"], ["Késedelmi kamat", "15"],
                                   ["Kötbér garantált szolgáltatás elmaradása miatt", "-5000"]]}}
    h = {"HR": {"kelte": "2026-07-28", "tipus": "resz", "osszeg": "1172", "hatarido": "2026-08-18", "kezi": True},
         "HR2": {"kelte": "2026-08-19", "tipus": "resz", "forras": "mvm_aram", "osszeg": "991", "szamlaertek": "991", "folyoszamla": "-47138",
                 "ugyfel": u, "hatarido": "2026-09-14", "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-30477"], ["Túlfizetés", "-17652"]]},
         "S": {"kelte": "2026-08-27", "tipus": "storno", "forras": "mvm_aram", "osszeg": "0", "szamlaertek": "-991", "sztornozott": "HR2",
               "ugyfel": u, "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "30477"], ["Túlfizetés", "17652"]]},
         "H": {"kelte": "2026-08-31", "tipus": "elszamolo", "forras": "mvm_aram", "osszeg": "-25522", "szamlaertek": "22607",
               "folyoszamla": "-25522", "ugyfel": u, "hatarido": "2026-09-21",
               "egyeb_tetelek": [["Egyéb fizetendőt csökkentő tétel", "-30477"], ["Túlfizetés", "-17652"]]}}
    hz = {"a1": ("Villany A1", a1), "h": ("Villany H", h)}
    fiz = {"R": {"fizetve": True, "datum": "2026-08-17", "forras": "kezi"}, "HR": {"fizetve": True, "datum": "2026-08-17", "forras": "kezi"},
           "HR2": {"fizetve": False, "forras": None, "nincs_fizetendo": True}}
    k = kivonat("h", hz, fiz, None, MA)
    assert k["kozos"] and k["zaro"] == -7382
    assert not any(t["fajta"] == "befizetes" and t["sorszam"] == "HR2" for t in k["tetelek"])
    assert [t.get("elteres") for t in k["tetelek"] if t.get("szolgaltato_egyenleg") is not None] == [0, 0, 0, 0]
    ki = {t["sorszam"]: t.get("kiegyenlitve") for t in k["tetelek"] if t["fajta"] == "szamla" and t["kovetel"] > 0}
    assert ki == {"R": "2026-08-17", "HR": "2026-08-17", "HR2": "2026-08-27", "H": "2026-08-31", "A2": "2026-09-21"}
    allapot = {s["sorszam"]: s["allapot"] for s in k["teljesites"]["sorok"]}
    assert allapot["HR2"] == "sztornozva" and allapot["S"] == "storno"
    # Terhelés / jóváírás összesen, mint a kimutatáson (64 390 / 71 772).
    assert sum(t["kovetel"] for t in k["tetelek"]) == 64390 and sum(t["tartozik"] for t in k["tetelek"]) == 71772
    # Tarifánként: a stornó (előjelfordított) egyéb sorai nem hoznak új átvezetést; a két záró együtt a közös egyenleg.
    kh, ka = kivonat("h", hz, fiz, None, MA, egyutt=False), kivonat("a1", hz, fiz, None, MA, egyutt=False)
    assert not any("845100000001" in t["megnevezes"] or (t["fajta"] == "egyeb" and t["sorszam"] == "S") for t in kh["tetelek"] + ka["tetelek"])
    assert kh["zaro"] + ka["zaro"] == -7382


def test_jovairas_reszletekben_beszamitva():
    """MVM gáz (Kertes ház 2024): a −14 482 Ft-os elszámoló jóváírásából 11 165 az augusztusi, 3 317 a szeptemberi
    részszámlán számítódik be – a jóváírás „beszámítva” (a két számlán), nem túlfizetés."""
    sz = {"E": {"kelte": "2024-07-25", "tipus": "elszamolo", "forras": "mvm_gaz", "osszeg": "-14482", "folyoszamla": "-14482"},
          "R1": {"kelte": "2024-08-21", "tipus": "resz", "forras": "mvm_gaz", "osszeg": "0", "szamlaertek": "11165", "folyoszamla": "-3317",
                 "egyeb_tetelek": [["Támogatás, túlfizetés", "-11165"]]},
          "R2": {"kelte": "2024-09-24", "tipus": "resz", "forras": "mvm_gaz", "osszeg": "7848", "szamlaertek": "11165", "folyoszamla": "7848",
                 "egyeb_tetelek": [["Támogatás, túlfizetés", "-3317"]], "hatarido": "2024-10-07"}}
    k = kivonat("g", {"g": ("Gáz", sz)}, {"R2": {"fizetve": True, "datum": "2024-10-07", "forras": "dijnet"}}, None, MA)
    sor = {x["sorszam"]: x for x in k["teljesites"]["sorok"]}
    assert sor["E"]["allapot"] == "beszamitva" and sor["E"]["beszamitva"] == "R1, R2"
    assert k["teljesites"]["osszesen"]["tulfizetes"] == 0
    assert [t.get("elteres") for t in k["tetelek"] if t.get("szolgaltato_egyenleg") is not None] == [0, 0, 0] and k["zaro"] == 0


def test_szamla_javitas_hatarido_es_megjegyzes_a_kivonatban():
    """A kézi javítás (koordinator.javitott_szamlak) a számlába „hatarido” és „javitas_megjegyzes” mezőként kerül –
    a kivonat tétele mindkettőt hordozza."""
    from datetime import date

    from folyoszamla import kivonat
    szamlak = {"1": {"kelte": "2026-09-07", "osszeg": "8758", "tipus": "egyeb", "hatarido": "2026-10-05",
                     "javitas_megjegyzes": "kedvezmény miatt kevesebb"}}
    k = kivonat("s", {"s": ("Telekom", szamlak)}, {}, None, date(2026, 10, 8))
    t = next(x for x in k["tetelek"] if x["fajta"] == "szamla")
    assert (t["hatarido"], t["megjegyzes"]) == ("2026-10-05", "kedvezmény miatt kevesebb")
