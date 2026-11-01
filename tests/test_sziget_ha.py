"""Szigetüzem HA-oldal (regresszió): ismeretlen mértékegységű forrás nem számít kWh-nak, a napi statisztika
gyorstára (naponta egyszer, korlátos). Futó HA nélkül, kitalált adatokkal."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi

MOST = datetime(2026, 10, 31, 12, 0)


def _napi(kezd, napok, q):
    return [(kezd + timedelta(days=i), D(1000) + q * i) for i in range(napok + 1)]


def _koord(egysegek, sorozatok):
    async def sorozat(eid, tol, most, napi_gyorstar=False):
        return sorozatok[eid]

    allapotok = {eid: SimpleNamespace(attributes={} if e is None else {"unit_of_measurement": e}) for eid, e in egysegek.items()}
    return SimpleNamespace(
        hass=SimpleNamespace(states=SimpleNamespace(get=allapotok.get)),
        tarolo=SimpleNamespace(sziget=lambda sid: {"leolvasasok": {}}),
        _sorozat=sorozat,
    )


def _sub(**forrasok):
    from custom_components.hu_rezsi import sziget_ha

    data = {sziget_ha.CONF_SZEREPEK: list(forrasok)} | {sziget_ha.forras_kulcs(k): v for k, v in forrasok.items()}
    return SimpleNamespace(data=data, title="Teszt sziget", subentry_type="sziget")


def test_nem_energia_mertekegyseg_nem_szamit_kwh_nak():
    from custom_components.hu_rezsi import sziget_ha

    okt1 = datetime(2026, 10, 1)
    koord = _koord({"sensor.load": "kWh", "sensor.grid": "W"},
                   {"sensor.load": _napi(okt1, 30, 10), "sensor.grid": _napi(okt1, 30, 2)})
    ki = asyncio.run(sziget_ha.szamol(koord, "S1", _sub(fogyasztas=["sensor.load"], halozat=["sensor.grid"]), MOST))
    h = ki["idoszakok"]["honap"]
    assert h["ertekek"]["halozat"] is None and h["minoseg"] == "PARTIAL"
    assert any("sensor.grid" in m and "„W”" in m for m in h["megjegyzesek"])
    assert ki["honapok"][-1]["megjegyzesek"][0].startswith("sensor.grid")


def test_hianyzo_mertekegyseg_fogyasztasnal_hiba_nevvel():
    from custom_components.hu_rezsi import sziget_ha

    koord = _koord({"sensor.load": None}, {"sensor.load": _napi(datetime(2026, 10, 1), 30, 10)})
    ki = asyncio.run(sziget_ha.szamol(koord, "S1", _sub(fogyasztas=["sensor.load"]), MOST))
    assert "sensor.load" in ki["hiba"] and "nincs megadva" in ki["hiba"] and ki["idoszakok"] == {}


# --- napi statisztika gyorstára ----------------------------------------------------------------------------------


def _sorozat_koord(monkeypatch, hivasok):
    from custom_components.hu_rezsi import koordinator as K

    def statisztika(_hass, kezd, veg, eidk, periodus, _u, _t):
        hivasok.append((periodus, kezd.replace(tzinfo=None), veg and veg.replace(tzinfo=None)))
        (eid,) = eidk
        vege = (veg or kezd + timedelta(days=1)).timestamp()
        return {eid: [{"end": vege, "state": 1000.0 + len(hivasok)}]}

    async def futtat(fn, *args):
        return fn(*args)

    monkeypatch.setattr(K, "statistics_during_period", statisztika)
    monkeypatch.setattr(K, "get_instance", lambda _h: SimpleNamespace(async_add_executor_job=futtat))
    k = object.__new__(K.RezsiKoordinator)
    k.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _e: SimpleNamespace(state="1234.5")))
    k._napi_stat, k._napi_stat_kert = {}, set()
    k._hianyzo_forrasok = set()
    return k


def test_napi_statisztika_naponta_egyszer(monkeypatch):
    hivasok = []
    k = _sorozat_koord(monkeypatch, hivasok)
    tol = datetime(2024, 8, 22)
    asyncio.run(k._sorozat("sensor.load", tol, MOST, napi_gyorstar=True))
    asyncio.run(k._sorozat("sensor.load", tol, MOST + timedelta(minutes=10), napi_gyorstar=True))
    hosszu = [h for h in hivasok if h[0] == "day" and h[1] == tol]
    assert hosszu == [("day", tol, datetime(2026, 10, 31))]  # a lezárt napok csak egyszer, ma éjfélig
    assert sum(1 for h in hivasok if h[0] == "hour") == 2  # az órás rész minden alkalommal friss
    assert sum(1 for h in hivasok if h[0] == "day" and h[1] == datetime(2026, 10, 31)) == 2  # a mai nap is
    asyncio.run(k._sorozat("sensor.load", tol, datetime(2026, 11, 1, 0, 5), napi_gyorstar=True))  # napváltás
    assert [h for h in hivasok if h[0] == "day" and h[1] == tol][-1] == ("day", tol, datetime(2026, 11, 1))


def test_napi_statisztika_gyorstar_korlatos(monkeypatch):
    hivasok = []
    k = _sorozat_koord(monkeypatch, hivasok)
    tol = datetime(2024, 8, 22)
    for eid in ("sensor.a", "sensor.b"):
        asyncio.run(k._sorozat(eid, tol, MOST, napi_gyorstar=True))
    k.napi_gyorstar_takaritas()
    asyncio.run(k._sorozat("sensor.a", tol, MOST, napi_gyorstar=True))
    k.napi_gyorstar_takaritas()  # a b forrást már nem kérte senki
    assert [eid for eid, _ in k._napi_stat] == ["sensor.a"]


def test_gyorstar_nelkul_valtozatlan(monkeypatch):
    hivasok = []
    k = _sorozat_koord(monkeypatch, hivasok)
    asyncio.run(k._sorozat("sensor.load", datetime(2025, 10, 1, 7, 30), MOST))
    assert [h[0] for h in hivasok] == ["day", "hour"] and hivasok[0][2] is None and k._napi_stat == {}
