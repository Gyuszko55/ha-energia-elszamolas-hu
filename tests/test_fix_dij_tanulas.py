"""Fix díjas fiók (MOHU): a díj a számlákból, ha a beépített díjszabás eltér (2.2.0b6)."""
from decimal import Decimal
from types import SimpleNamespace

import custom_components.hu_rezsi.koordinator as K


def _koord(monkeypatch, szamlak, feluliras=None, alapdij_ho=1924 / 1.0):
    k = object.__new__(K.RezsiKoordinator)
    ertesites = []
    monkeypatch.setattr(K.persistent_notification, "async_create", lambda hass, msg, **kw: ertesites.append(msg))
    monkeypatch.setattr(K, "_hozzarendeles", lambda fiok, nap: None)
    k.hass = SimpleNamespace()
    k.motor_fiok = lambda sid: SimpleNamespace(szolgaltato="mohu", feluliras=[])
    k.tar = SimpleNamespace(felold=lambda *a: SimpleNamespace(dijak={"alapdij_ho": alapdij_ho, "afa": 0}, szabalyok={"alapdij": {}}))
    sub = SimpleNamespace(title="MOHU", data={K.CONF_KOZMU: "hulladek", K.CONF_SZAMLAZAS_HONAP: 3})
    tarolt = {"szamlak": szamlak, "feluliras": feluliras or []}
    return k, sub, tarolt, ertesites


def _sz(kelte, tol, ig, osszeg):
    return {"kelte": kelte, "idoszak": [tol, ig], "osszeg": osszeg, "szamlaertek": osszeg}


SZAMLAK = {
    "1": _sz("2026-01-08", "2025-10-01", "2025-12-31", 3896),
    "2": _sz("2026-04-08", "2026-01-01", "2026-03-31", 3896),
    "3": _sz("2026-07-08", "2026-04-01", "2026-06-30", 3896),
}


def test_ket_egyezo_szamla_eltero_dijjal_tanul(monkeypatch):
    k, sub, tarolt, ert = _koord(monkeypatch, SZAMLAK)
    assert k._fix_dij_tanul("S", sub, tarolt) is True
    f = tarolt["feluliras"][-1]
    assert f["kulcs"] == "dijak.alapdij_ho" and Decimal(f["ertek"]) == Decimal("1298.67") and f["ervenyes_tol"] == "2025-10-01"
    assert ert and "3896 Ft / 3 hónap" in ert[0]
    assert k._fix_dij_tanul("S", sub, tarolt) is False                      # egyszer


def test_kezi_dij_vagy_egyezo_dij_eseten_nem(monkeypatch):
    k, sub, tarolt, _ = _koord(monkeypatch, SZAMLAK, feluliras=[{"kulcs": "dijak.alapdij_ho", "ertek": "1500", "ervenyes_tol": "2025-01-01"}])
    assert k._fix_dij_tanul("S", sub, tarolt) is False
    k, sub, tarolt, _ = _koord(monkeypatch, SZAMLAK, alapdij_ho=3896 / 3)
    assert k._fix_dij_tanul("S", sub, tarolt) is False


def test_valtozo_osszegnel_nem(monkeypatch):
    sz = dict(SZAMLAK, **{"3": _sz("2026-07-08", "2026-04-01", "2026-06-30", 4200)})
    k, sub, tarolt, _ = _koord(monkeypatch, sz)
    assert k._fix_dij_tanul("S", sub, tarolt) is False


def test_sajat_dijak_mentes_bruttobol_es_tiltott_mezo(monkeypatch):
    import asyncio
    from datetime import date
    k, sub, tarolt, _ = _koord(monkeypatch, SZAMLAK)
    sub.data = {K.CONF_KOZMU: "viz"}
    k.fiokok = lambda: {"S": sub}
    mentve = []
    async def ment():
        mentve.append(1)
    k.tarolo = SimpleNamespace(fiok=lambda sid: tarolt, ment=ment)
    k._hatter_frissites = lambda: None
    k.tar = SimpleNamespace(felold=lambda *a: SimpleNamespace(dijak={"viz_m3": 400, "csatorna_m3": 500, "alapdij_ho": 0, "afa": 27}, szabalyok={}))
    d = k.sajat_dijak("S", date(2026, 11, 4))
    assert [m["kulcs"] for m in d["mezok"]] == ["viz_m3", "csatorna_m3", "alapdij_ho"] and d["mezok"][0]["ertek"] == 508.0
    asyncio.run(k.sajat_dijak_ment("S", {"viz_m3": 635.0}, date(2026, 1, 1)))
    f = [x for x in tarolt["feluliras"] if x["kulcs"] == "dijak.viz_m3"][0]
    assert Decimal(f["ertek"]) == Decimal("500.0000") and f["ervenyes_tol"] == "2026-01-01" and mentve
    assert tarolt["fix_dij_tanulva"]                                           # kézi díj után nincs tanulás
    try:
        asyncio.run(k.sajat_dijak_ment("S", {"energia": 1.0}, date(2026, 1, 1)))
        raise AssertionError("tiltott mező")
    except ValueError:
        pass
