"""Hangutasítások (2.4.0b2): közmű-szűrés, készenlét, a válaszok szövege – kitalált adatokkal."""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import custom_components.hu_rezsi.hang as G
import custom_components.hu_rezsi.hatarido_ertesites as H
from custom_components.hu_rezsi import panel_beallitas as pb

MA = date(2026, 11, 10)


def _ny(eddig, varhato, keret=None, atlepes=None, egyseg="kWh"):
    return SimpleNamespace(eddig=SimpleNamespace(osszesen_ft=Decimal(eddig), szeletek=[SimpleNamespace(egyseg=egyseg)]),
                           varhato=SimpleNamespace(osszesen_ft=Decimal(varhato)),
                           hatralevo_keret=None if keret is None else Decimal(keret), varhato_keretatlepes=atlepes)


def _a(**k):
    alap = dict(nyitott=None, esedekes=None, szamla_stat=None, utolso_szamla=None, megszunt=None, egyseg="kWh")
    return SimpleNamespace(**(alap | k))


def _f(nev, kozmu, a, otthon="Minta utca", tobb=False):
    return {"otthon": otthon, "nev": nev, "kozmu": kozmu, "a": a, "sid": nev, "tobb": tobb}


def test_datum_rag():
    assert [G.datumon_hang(date(2026, 12, n)) for n in (1, 2, 4, 12, 13, 20, 21, 30)] == [
        "december 1-jén", "december 2-án", "december 4-én", "december 12-én", "december 13-án", "december 20-án",
        "december 21-én", "december 30-án"]


def test_kozmu_kod():
    assert G.kozmu_kod("gáz") == "gaz" and G.kozmu_kod("Áram") == "villany" and G.kozmu_kod("villanyszámla") == "villany"
    assert G.kozmu_kod("fűtés") == "tavho" and G.kozmu_kod("szemét") == "hulladek" and G.kozmu_kod("közös költség") == "kozos"
    assert G.kozmu_kod(None) is None and G.kozmu_kod("") is None and G.kozmu_kod("valami") is None


def test_kovetkezo():
    ff = [_f("Gáz", "gaz", _a(esedekes={"kovetkezo_datum": "2026-11-26", "kovetkezo_osszeg": 11200})),
          _f("Áram", "villany", _a(szamla_stat={"kovetkezo_datum": date(2026, 11, 11), "kovetkezo_osszeg": None})),
          _f("Víz", "viz", _a())]
    assert G.kovetkezo_valasz(ff, None, MA) == ("A következő számlák: Áram: holnap; Gáz: kb. 11 200 forint, "
                                                "november 26. körül.")
    assert G.kovetkezo_valasz([], "viz", MA) == "Nem tudom, mikor jön a következő számla (víz)."
    elmaradt = [_f("Gáz", "gaz", _a(esedekes={"kovetkezo_datum": "2026-11-01", "kovetkezo_osszeg": 5000}))]
    assert "november 1. óta várható, még nem érkezett meg" in G.kovetkezo_valasz(elmaradt, "gaz", MA)


def test_koltseg():
    ff = [_f("Áram", "villany", _a(nyitott=_ny(8000, 14500))), _f("Gáz", "gaz", _a(nyitott=_ny(3000, 9000))),
          _f("Szemét", "hulladek", _a())]
    assert G.koltseg_valasz(ff, None) == ("A folyó elszámolási időszakokban eddig összesen 11 000 forint, az időszakok "
                                         "végére várhatóan 23 500 forint: Áram eddig 8 000 forint, várhatóan 14 500 forint; "
                                         "Gáz eddig 3 000 forint, várhatóan 9 000 forint.")
    assert G.koltseg_valasz(ff[:1], "villany") == "A folyó elszámolási időszakban: Áram eddig 8 000 forint, várhatóan 14 500 forint."


def test_keret():
    ff = [_f("Áram", "villany", _a(nyitott=_ny(1, 1, keret="312.4", atlepes=date(2026, 12, 12)))),
          _f("Gáz", "gaz", _a(nyitott=_ny(1, 1, keret="85", egyseg="m3"))),
          _f("H", "villany", _a(nyitott=_ny(1, 1, keret="0"))), _f("Víz", "viz", _a(nyitott=_ny(1, 1)))]
    assert G.keret_valasz(ff, None) == ("Áram: a kedvezményes keretből még 312 kilowattóra van hátra, várhatóan "
                                        "december 12-én lépi túl; Gáz: a kedvezményes keretből még 85 köbméter van hátra, "
                                        "az időszakban várhatóan nem lépi túl; H: a kedvezményes keretet már elérte, a többi "
                                        "piaci áron megy.")
    assert G.keret_valasz([], "viz") == "Nincs kedvezményes keretes fiók (víz)."


def test_utolso():
    ff = [_f("Gáz", "gaz", _a(utolso_szamla={"osszeg": "11187", "kelte": "2026-10-26"}), otthon="A", tobb=True),
          _f("Víz", "viz", _a(utolso_szamla={"osszeg": 6789.0, "kelte": "2026-10-30"}), otthon="B", tobb=True)]
    assert G.utolso_valasz(ff, None) == ("Az utolsó számlák: B · Víz: 6 789 forint, kelte október 30.; "
                                         "A · Gáz: 11 187 forint, kelte október 26.")


def _hass(entries):
    return SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda d: entries), data={})


def _entry(eid, data):
    sub = SimpleNamespace(title="Gáz", data={"kozmu": "gaz"})
    koord = SimpleNamespace(data=data, fiokok=lambda: {"s1": sub})
    return SimpleNamespace(entry_id=eid, title="Minta utca", runtime_data=koord)


def test_kesz_es_betoltes_valasz(monkeypatch):
    monkeypatch.setattr(pb, "aktualis", lambda h: pb.alap())
    nem = _hass([_entry("e1", None)])
    assert not G.kesz(nem)
    intent_obj = SimpleNamespace(hass=nem, slots={}, create_response=lambda: _Valasz())
    r = asyncio.run(G.UtolsoSzamlaIntent().async_handle(intent_obj))
    assert r.szoveg == G.BETOLT_SZOVEG
    kesz = _hass([_entry("e1", {"s1": _a(utolso_szamla={"osszeg": 500, "kelte": "2026-11-01"})})])
    assert G.kesz(kesz)
    intent_obj = SimpleNamespace(hass=kesz, slots={"kozmu": {"value": "gáz"}}, create_response=lambda: _Valasz())
    r = asyncio.run(G.UtolsoSzamlaIntent().async_handle(intent_obj))
    assert r.szoveg == "Az utolsó számla (gáz): Gáz: 500 forint, kelte november 1."
    intent_obj = SimpleNamespace(hass=kesz, slots={"kozmu": {"value": "víz"}}, create_response=lambda: _Valasz())
    assert asyncio.run(G.UtolsoSzamlaIntent().async_handle(intent_obj)).szoveg == "Nincs rögzített számla (víz)."


class _Valasz:
    szoveg = None

    def async_set_speech(self, s):
        self.szoveg = s


def test_ertesito_nem_kuld_elso_szamolas_elott(monkeypatch):
    hass = _hass([_entry("e1", None)])
    monkeypatch.setattr(pb, "aktualis", lambda h: pb.alap() | {pb.ERT_BE: True, pb.ERT_CELOK: ["notify.mobile_app_x"]})
    later = []
    monkeypatch.setattr(H, "async_call_later", lambda h, mp, cb: later.append(mp))
    e = H.Ertesito.__new__(H.Ertesito)
    e.hass, e.adat, e._ujra = hass, {"kuldott": {}, "utolso": None}, None
    monkeypatch.setattr(H, "async_call_later", lambda h, mp, cb: later.append(mp) or (lambda: None))
    assert asyncio.run(e.fut()) == 0 and later == [H.UJRA_MP] and e.adat["utolso"] is None
    assert asyncio.run(e.fut()) == 0 and later == [H.UJRA_MP]  # a második napi futás nem indít újabb újrapróbálást


def test_llm_eszkozok(monkeypatch):
    from homeassistant.helpers import intent
    from homeassistant.helpers.llm import LLM_API_ASSIST
    from custom_components.hu_rezsi import llm as L
    monkeypatch.setattr(intent, "async_get", lambda hass: [k() for k in G.SZANDEKOK])
    eszk = L.async_get_tools(None, None, LLM_API_ASSIST).tools
    assert [e.name for e in eszk] == ["hu_rezsi__befizetendo_szamlak", "hu_rezsi__kovetkezo_szamla", "hu_rezsi__koltseg_eddig",
                                      "hu_rezsi__kedvezmenyes_keret", "hu_rezsi__utolso_szamla"]
    assert all(e.integration == "hu_rezsi" and "kozmu" in str(e.parameters.schema) for e in eszk)
    assert L.async_get_tools(None, None, "mas_api") is None
