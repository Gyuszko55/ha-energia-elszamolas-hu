"""Késő, soha meg nem érkező várt számla lemondása (2.3.0b10): csak a becslés tűnik el, a következő valódi számla után
a lemondás hatástalan; a sztornózott számla időszaka nem számít kiszámlázottnak (a H-tarifás eset, kitalált adatokkal)."""
from datetime import date

import tests.conftest  # noqa: F401
from fejlec import kovetkezo_szamla
from custom_components.hu_rezsi.szamla_import import esedekes, lemondott_datumok

SZAMLAK = {
    "R1": {"kelte": "2026-08-19", "idoszak": ["2026-07-16", "2026-08-15"], "osszeg": "991", "tipus": "resz"},
    "S1": {"kelte": "2026-08-27", "idoszak": ["2026-07-16", "2026-08-15"], "osszeg": "-991", "tipus": "storno", "sztornozott": "R1"},
    "E1": {"kelte": "2026-08-31", "idoszak": ["2026-02-03", "2026-08-08"], "osszeg": "22607", "tipus": "elszamolo"},
}
MA = date(2026, 11, 4)


def _f(es):
    return {"reszszamlas": True, "esedekes": es, "utem": {"szamlazas_honap": 1}}


def test_esedekes_lemondas_atugorja():
    t = {"szamlak": SZAMLAK}
    e = esedekes(t, MA, 1, None)
    assert e["kovetkezo_datum"] == date(2026, 9, 30) and e["elmaradt"]
    t["lemondott_szamlak"] = [{"kovetkezo_datum": "2026-09-30"}]
    e = esedekes(t, MA, 1, None)
    assert e["kovetkezo_datum"] == date(2026, 10, 31)  # A) a következő ütem marad (ez is késhet)
    # Valódi számla jött: a régi lemondás hatástalan.
    t["szamlak"] = SZAMLAK | {"R2": {"kelte": "2026-10-28", "idoszak": ["2026-09-09", "2026-10-08"], "osszeg": "570", "tipus": "resz"}}
    assert lemondott_datumok(t) == set() and esedekes(t, MA, 1, None)["kovetkezo_datum"] == date(2026, 11, 28)


def test_fejlec_sztornozott_idoszak_es_lemondas():
    es = {"kovetkezo_datum": "2026-09-30", "kovetkezo_osszeg": 570, "elmaradt": True}
    k = kovetkezo_szamla(_f(es), SZAMLAK, MA)
    # a sztornózott részszámla (…08.15) nem számít: az elszámoló vége (08.08) után indul
    assert (k["tol"], k["ig"], k["dij"], k["kesik"], k["varva"]) == ("2026-08-09", "2026-09-08", 570, True, "2026-09-30")
    es2 = {"kovetkezo_datum": "2026-10-31", "kovetkezo_osszeg": 570, "elmaradt": True}
    k = kovetkezo_szamla(_f(es2) | {"lemondott_szamlak": [{"kovetkezo_datum": "2026-09-30"}]}, SZAMLAK, MA)
    assert (k["tol"], k["ig"], k["varva"]) == ("2026-09-09", "2026-10-08", "2026-10-31")


def test_uton_rendezett_kimarad():
    """Úton lévő (saját számítású) számla, amelyet egy későbbi számla elszámolt: rendezettnek jelölve kimarad."""
    from types import SimpleNamespace
    from custom_components.hu_rezsi.koordinator import _uton_szamlak
    sub = SimpleNamespace(data={"kozmu": "villany", "dijszabas": "villany/a1", "elszamolas_mod": "diktalas"})
    t = {"szamlak": {"A": {"kelte": "2026-10-21", "idoszak": ["2026-09-10", "2026-09-29"], "osszeg": "79942", "tipus": "elszamolo"}}}
    lz = [{"tol": "2026-09-29", "ig": "2026-10-09", "osszesen_ft": 5004, "mennyiseg": 102.4}]
    u = _uton_szamlak(sub, t, lz, date(2026, 11, 5))
    assert [(x["tol"], x["ig"], x["osszeg"]) for x in u] == [("2026-09-30", "2026-10-09", 5004)]
    t["rendezett_uton"] = [{"tol": "2026-09-30", "ig": "2026-10-09", "osszeg": 5004}]
    assert _uton_szamlak(sub, t, lz, date(2026, 11, 5)) == []


def test_automatikus_rendezes_kozos_folyoszamla():
    """MVM közös folyószámla (kitalált adatok): az A1 úton lévő számláját a saját későbbi kelte számla, a H késő
    átalány-részszámláját a társfiók későbbi számlája rendezi; a még későbbi várt H-számla marad."""
    from custom_components.hu_rezsi.szamla_import import automatikus_rendezes
    a1 = {"szamlak": {"A": {"kelte": "2026-10-21", "idoszak": ["2026-09-10", "2026-09-29"], "osszeg": "79942", "tipus": "elszamolo"}}}
    h = {"szamlak": dict(SZAMLAK)}
    uton = [{"tol": "2026-09-30", "ig": "2026-10-09", "osszeg": 5004}]
    es_h = {"kovetkezo_datum": date(2026, 9, 30), "kovetkezo_osszeg": 570, "elmaradt": True}
    csop = {"A1": ["A1", "H"], "H": ["A1", "H"]}
    r = automatikus_rendezes({"A1": (a1, None, uton), "H": (h, es_h, None)}, csop, "2026-11-05T10:00:00")
    assert [(s, f, b.get("tol") or b.get("kovetkezo_datum"), b["sorszam"]) for s, f, b in r] == [
        ("A1", "uton", "2026-09-30", "A"), ("H", "lemondas", "2026-09-30", "A")]
    assert lemondott_datumok(h) == {"2026-09-30"} and a1["rendezett_uton"][0]["auto"]
    # Második kör: a következő várt H-számla (10.31.) után még nem jött számla – marad; nincs ismételt bejegyzés.
    es_h2 = {"kovetkezo_datum": date(2026, 10, 31), "kovetkezo_osszeg": 570, "elmaradt": True}
    assert automatikus_rendezes({"A1": (a1, None, []), "H": (h, es_h2, None)}, csop, "2026-11-05T10:01:00") == []
    # Közös folyószámla nélkül a másik fiók számlája nem számít.
    h2 = {"szamlak": dict(SZAMLAK)}
    assert automatikus_rendezes({"A1": (a1, None, []), "H": (h2, es_h, None)}, {}, "x") == []


def test_esedekes_kozos_utolso_kelte():
    """Közös számlázás: a társfiók későbbi számlája (10.21.) után a következő számla 11.21. körül."""
    t = {"szamlak": SZAMLAK, "lemondott_szamlak": [{"kovetkezo_datum": "2026-09-30"}, {"kovetkezo_datum": "2026-10-31"}]}
    e = esedekes(t, MA, 1, None, date(2026, 10, 21))
    assert e["kovetkezo_datum"] == date(2026, 11, 21) and not e["elmaradt"]


def test_fejlec_dupla_lemondas_egyszer_tol():
    """Ugyanarra a várt keltére két lemondás (két gyors kérés): az időszak csak egy ütemmel csúszik."""
    es2 = {"kovetkezo_datum": "2026-10-31", "kovetkezo_osszeg": 570, "elmaradt": True}
    dupla = [{"kovetkezo_datum": "2026-09-30"}, {"kovetkezo_datum": "2026-09-30"}]
    k = kovetkezo_szamla(_f(es2) | {"lemondott_szamlak": dupla}, SZAMLAK, MA)
    assert (k["tol"], k["ig"]) == ("2026-09-09", "2026-10-08")


def test_automatikus_rendezes_sajat_szamla_csak_lefedo_idoszakkal():
    """Közös folyószámla nélkül (pl. mért gáz) a késve jött korábbi számla nem rendezi az úton lévő időszakot – csak
    az, amelyiknek az időszaka eléri."""
    from custom_components.hu_rezsi.szamla_import import automatikus_rendezes
    uton = [{"tol": "2026-10-01", "ig": "2026-10-31", "osszeg": 9000}]
    gaz = {"szamlak": {"G9": {"kelte": "2026-11-02", "idoszak": ["2026-09-01", "2026-09-30"], "osszeg": "8000", "tipus": "elszamolo"}}}
    assert automatikus_rendezes({"G": (gaz, None, uton)}, {"G": ["G"]}, "x") == []
    gaz["szamlak"]["G10"] = {"kelte": "2026-11-06", "idoszak": ["2026-10-01", "2026-10-31"], "osszeg": "9100", "tipus": "elszamolo"}
    r = automatikus_rendezes({"G": (gaz, None, uton)}, {"G": ["G"]}, "x")
    assert [(f, b["tol"], b["sorszam"]) for _, f, b in r] == [("uton", "2026-10-01", "G10")]
