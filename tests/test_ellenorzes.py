"""Számla-ellenőrzés: valós MVM-számlahibák mintájára (anonimizált) (A1 nem kiszámlázott fogyasztás, H regisztercsere)."""
import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from ellenorzes import ellenoriz, viz_ellenoriz
from szamlak import mvm_folyoszamla


def test_nem_szamlazott_fogyasztas():
    sorok = [{"sorszam": "900000000001", "kelte": "2026-08-17", "tol": "2026-04-11", "ig": "2026-08-08", "mert": True,
              "szamla_ft": -4019, "szamolt_ft": 59138}]
    szamlak = {"900000000001": {"tipus": "elszamolo", "elszamolt_kwh": "1234", "szamlazott_kwh": "33"}}
    [t] = ellenoriz(sorok, szamlak)
    assert t["tipus"] == "nem_szamlazott" and t["hatas_ft"] == 63157 and t["sulyos"]


def test_h_regisztercsere():
    sorok = [{"sorszam": "900000000002", "kelte": "2026-08-31", "mert": True, "szamla_ft": 25973, "szamolt_ft": 24299,
              "szamolt_idenyek": {"teli": 474.0, "nyari": 349.0}}]
    szamlak = {"900000000002": {"tipus": "elszamolo", "elszamolt_kwh": "823", "szamlazott_kwh": "823",
                                "szamlazott_idenyek": {"teli": "349", "nyari": "474"}}}
    [t] = ellenoriz(sorok, szamlak)
    assert t["tipus"] == "regisztercsere" and t["hatas_ft"] == -1674


def test_rendben_levo_szamla_nem_hiba():
    sorok = [{"sorszam": "1", "mert": True, "szamla_ft": 25690, "szamolt_ft": 25690}]
    assert ellenoriz(sorok, {"1": {"tipus": "elszamolo", "elszamolt_kwh": "434", "szamlazott_kwh": "434"}}) == []


def test_reszszamla_nem_ellenorzott():
    sorok = [{"sorszam": "1", "mert": False, "szamla_ft": 579, "szamolt_ft": 7084}]
    assert ellenoriz(sorok, {"1": {"tipus": "resz"}}) == []


def test_folyoszamla_tetelek():
    t = ("Bruttó számlaérték összesen** 22.607\nEgyéb fizetendőt csökkentő tétel -30.477\nTúlfizetés -17.652\n"
         "Fizetendő összeg összesen -25.522\nA nyilvántartás szerinti folyószámla-egyenlege a számla kibocsátásakor: -25.522 Ft.")
    egyenleg, tetelek = mvm_folyoszamla(t)
    assert egyenleg == -25522
    assert [(n, int(o)) for n, o in tetelek] == [("Egyéb fizetendőt csökkentő tétel", -30477), ("Túlfizetés", -17652)]


def test_tobbsoros_kotber():
    t = ("Bruttó számlaérték összesen** 2.447\nKötbér garantált szolgáltatás\nelmaradása miatt -5.000\n"
         "Fizetendő összeg összesen -2.553\n")
    _, tetelek = mvm_folyoszamla(t)
    assert [(n, int(o)) for n, o in tetelek] == [("Kötbér garantált szolgáltatás elmaradása miatt", -5000)]


def test_kezi_elszamolo_teljes_dija_a_reszszamlakkal():
    # Kézi éves elszámoló részszámlás (átalányos) fióknál: a számlán a fizetendő (247 Ft) áll, a teljes díj ehhez
    # adva az időszak részszámlái – különben hamis „103 818 Ft-tal kevesebb” eltérés.
    from szamlak import szamla_teljes_dija

    szamlak = {f"V-{m:02d}": {"tipus": "resz", "osszeg": "9438", "kezi": True,
                             "idoszak": [f"2026-{m:02d}-01", f"2026-{m:02d}-28"]} for m in range(1, 12)}
    elsz = {"tipus": "elszamolo", "osszeg": "247", "kezi": True, "idoszak": ["2026-01-01", "2026-12-31"]}
    szamlak["V-ELSZ"] = elsz
    assert szamla_teljes_dija(elsz, szamlak) == (247 + 11 * 9438, "fizetendo+reszszamlak")
    sorok = [{"sorszam": "V-ELSZ", "mert": True, "szamla_ft": 247 + 11 * 9438, "szamolt_ft": 104065}]
    assert ellenoriz(sorok, szamlak) == []


def test_kezi_havi_szamla_reszszamla_nelkul_valtozatlan():
    # Diktálásos havi kézi számla: nincs levont részszámla, a fizetendő maga a díj – az eltérés továbbra is jelez.
    from szamlak import szamla_teljes_dija

    h = {"tipus": "elszamolo", "osszeg": "14403", "kezi": True, "idoszak": ["2026-02-01", "2026-02-28"]}
    assert szamla_teljes_dija(h, {"H-02": h}) == (14403, "fizetendo")
    [t] = ellenoriz([{"sorszam": "H-02", "mert": True, "szamla_ft": 14403, "szamolt_ft": 11991}], {"H-02": h})
    assert t["tipus"] == "elteres" and t["hatas_ft"] == -2412


def test_viz_csatorna_tobblet():
    """Vízszámla (anonimizált): 4 m³ ivóvízre 8 m³ szennyvíz (kétszer szereplő szennyvízdíj-sor) – a 4 m³ többlet csatornadíja
    (240,30 + 6,90 vízterhelési = 247,20 Ft/m³ nettó, + 27% ÁFA) reklamálható; az almérős (kevesebb csatorna) számla nem hiba."""
    from decimal import Decimal as D
    szamlak = {
        "900000000003": {"kelte": "2026-08-24", "osszeg": "3699.0", "tipus": "resz", "idoszak": ["2026-05-01", "2026-08-31"],
                         "elszamolt_viz": {"ivoviz": "4", "csatorna": "8", "atalany": True, "idoszak": ["2026-05-01", "2026-08-31"]}},
        "900000000004": {"kelte": "2026-10-01", "osszeg": "20929", "tipus": "resz",
                         "elszamolt_viz": {"ivoviz": "28", "csatorna": "22", "idoszak": ["2026-08-01", "2026-09-30"]}},
    }
    [t] = viz_ellenoriz(szamlak, lambda nap: D("247.20") * D("1.27"))
    assert t["tipus"] == "csatorna_tobblet" and t["sorszam"] == "900000000003" and t["sulyos"]
    assert t["hatas_ft"] == -1256 and t["szamolt_ft"] == 2443
    assert viz_ellenoriz(szamlak, lambda nap: None) == []
    assert viz_ellenoriz(szamlak, lambda nap: D(300), hatar="2026-09-01") == []


def test_viz_csatorna_tobblet_melegvizzel():
    """Ha a háztartás melegvize távhőről jön, és a vízmű a melegvíz szennyvizét is számlázza (ALFÖLDVÍZ 2026.05-től),
    a 4 m³ ivóvízre jutó 8 m³ szennyvíz nem hiba: + 4 × 1 m³ melegvíz = 8."""
    from datetime import date
    from decimal import Decimal as D
    szamlak = {"900000000005": {"kelte": "2026-08-24", "osszeg": "3699", "tipus": "resz",
                                "elszamolt_viz": {"ivoviz": "4", "csatorna": "8", "idoszak": ["2026-05-01", "2026-08-31"]}}}
    havi = lambda tol, ig: D((ig.year - tol.year) * 12 + ig.month - tol.month + 1)  # noqa: E731 – 1 m³/hó
    assert viz_ellenoriz(szamlak, lambda nap: D(300), melegviz=havi) == []
    assert havi(date(2026, 5, 1), date(2026, 8, 31)) == 4


def test_viz_csatorna_tobblet_elszamolon_nem():
    """Elszámoló számlán a mennyiségek különbözetek (a részszámlák levonása után): a több csatorna nem hiba."""
    from decimal import Decimal as D
    szamlak = {"E": {"kelte": "2026-02-02", "osszeg": "9018", "tipus": "elszamolo",
                     "elszamolt_viz": {"ivoviz": "7", "csatorna": "13", "idoszak": ["2025-07-27", "2026-01-23"]}}}
    assert viz_ellenoriz(szamlak, lambda nap: D(300)) == []


def test_tavho_elszamolo_nem_elteres():
    """Távhő: a fűtési idény utáni elszámoló (hődíj-korrekció) a ház költségmegosztásából jön – nem eltérés."""
    sor = [{"sorszam": "K", "kelte": "2026-05-20", "tol": "2025-11-01", "ig": "2026-04-30", "szamla_ft": 91957, "szamolt_ft": 100409}]
    sz = {"K": {"tipus": "elszamolo", "osszeg": "-8450"}}
    assert ellenoriz(sor, sz, tavho=True) == []
