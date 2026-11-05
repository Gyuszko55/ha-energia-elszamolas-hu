"""Határidő-értesítés és „van befizetendő számlám?” (2.4.0b1) – kitalált adatokkal."""
import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

import custom_components.hu_rezsi.hatarido_ertesites as H
from custom_components.hu_rezsi import panel_beallitas as pb

MA = date(2026, 11, 10)


def _a(osszeg, hatarido, **k):
    return {"fizetve": False, "nincs_fizetendo": False, "osszeg": osszeg, "hatarido": hatarido, "utemezett": None} | k


def _fiokok():
    return [
        ("Minta utca", "s1", "Áram", {"1": {}, "2": {}, "3": {"fizetesi_mod": "Csoportos beszedés"}},
         {"1": _a(12345, "2026-11-13"), "2": _a(5000, "2026-11-09"), "3": _a(8000, "2026-11-12")}),
        ("Minta utca", "s2", "Víz", {"4": {}, "5": {}, "6": {}, "7": {}},
         {"4": _a(6789, "2026-11-20"), "5": _a(100, "2026-11-11", fizetve=True),
          "6": _a(900, "2026-11-12", utemezett="2026-11-12"), "7": _a(0, "2026-11-12", nincs_fizetendo=True)}),
    ]


def test_tetelek_kihagyja_a_beszedest_atutalast_fizetettet():
    t = H.tetelek(_fiokok(), MA)
    assert [(x["sorszam"], x["nap"]) for x in t] == [("2", -1), ("1", 3), ("4", 10)]
    assert t[0]["lejart"] and not t[1]["lejart"]


def test_regi_hatarido_kimarad():
    t = H.tetelek([("O", "s", "F", {"1": {}}, {"1": _a(10, "2026-07-01")})], MA)
    assert t == []


def test_kuldendok_egyszer():
    t = H.tetelek(_fiokok(), MA)
    elotte, lejart = H.kuldendok(t, 3, {})
    assert [x["sorszam"] for x in elotte] == ["1"] and [x["sorszam"] for x in lejart] == ["2"]
    elotte, lejart = H.kuldendok(t, 3, {"s1|1|elotte": "2026-11-10", "s1|2|lejart": "2026-11-10"})
    assert elotte == [] and lejart == []
    # később érkezett számla: a határidőn belül még jelez (nem csak pontosan N nappal előtte)
    elotte, _ = H.kuldendok(H.tetelek(_fiokok(), date(2026, 11, 12)), 3, {})
    assert [x["sorszam"] for x in elotte] == ["1"]


def test_uzenet_szovege():
    t = H.tetelek(_fiokok(), MA)
    cim, szoveg = H.uzenet(*H.kuldendok(t, 3, {}))
    assert cim == "Rezsikövető – 2 befizetendő számla"
    assert szoveg.splitlines() == ["Áram: 12 345 Ft, határidő nov. 13. (3 nap múlva)",
                                   "Áram: 5 000 Ft – tegnap lejárt (nov. 9.), még nincs befizetve"]
    assert H.uzenet([], []) is None


def test_hang_valasz():
    assert H.hang_valasz([]) == "Nincs befizetendő számlád."
    t = H.tetelek(_fiokok(), MA)
    v = H.hang_valasz(t)
    assert v.startswith("3 befizetendő számlád van, összesen 24 134 forint: ")
    assert "Áram 12 345 forint, 3 nap múlva esedékes" in v and "Áram 5 000 forint, tegnap lejárt" in v
    assert "Lejárt számla nincs" not in v
    v1 = H.hang_valasz([x for x in t if x["sorszam"] == "4"])
    assert v1 == "Egy befizetendő számlád van: Víz 6 789 forint, 10 nap múlva esedékes. Lejárt számla nincs."


def test_tobb_otthon_neve():
    f = _fiokok() + [("Nyaraló", "s3", "Gáz", {"9": {}}, {"9": _a(3000, "2026-11-10")})]
    v = H.hang_valasz(H.tetelek(f, MA))
    assert "Nyaraló · Gáz 3 000 forint, ma esedékes" in v


def test_beallitas_ellenorzes():
    assert pb.ervenyes({pb.ERT_BE: True, pb.ERT_NAPOK: "5", pb.ERT_CELOK: ["notify.mobile_app_b", "notify.mobile_app_a"],
                        pb.ERT_IDO: "8:5"}) == {pb.ERT_BE: True, pb.ERT_NAPOK: 5,
                                                pb.ERT_CELOK: ["notify.mobile_app_a", "notify.mobile_app_b"], pb.ERT_IDO: "08:05"}
    for rossz in ({pb.ERT_NAPOK: 0}, {pb.ERT_NAPOK: 15}, {pb.ERT_CELOK: ["light.x"]}, {pb.ERT_IDO: "25:00"}, {pb.ERT_BE: "igen"}):
        with pytest.raises(ValueError):
            pb.ervenyes(rossz)


def test_bekapcsolas_cel_nelkul_hiba(monkeypatch):
    hass = SimpleNamespace(data={})

    async def betolt(h):
        return pb.alap()
    monkeypatch.setattr(pb, "betolt", betolt)
    with pytest.raises(ValueError):
        asyncio.run(pb.ment(hass, {pb.ERT_BE: True}))


def test_otthon_szures(monkeypatch):
    def koord(cim):
        sub = SimpleNamespace(title="Áram")
        return SimpleNamespace(fiokok=lambda: {"s" + cim: sub}, javitott_szamlak=lambda sid: {"1": {}},
                               fizetes_allapotok=lambda sid: {"1": _a(1000, "2026-11-12")})
    entries = [SimpleNamespace(entry_id="e1", title="Első", runtime_data=koord("1")),
               SimpleNamespace(entry_id="e2", title="Második", runtime_data=koord("2"))]
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda d: entries), data={})
    monkeypatch.setattr(pb, "aktualis", lambda h: pb.alap())
    t = H._gyujt(hass, MA)
    assert [x["otthon"] for x in t] == ["Első", "Második"] and all(x["tobb_otthon"] for x in t)
    monkeypatch.setattr(pb, "aktualis", lambda h: pb.alap() | {pb.ERT_OTTHONOK: ["e2"]})
    t = H._gyujt(hass, MA)
    assert [x["otthon"] for x in t] == ["Második"] and not t[0].get("tobb_otthon")
    assert H.hang_valasz(t).startswith("Egy befizetendő számlád van: Áram 1 000 forint")
    assert pb.ervenyes({pb.ERT_OTTHONOK: ["b", "a", "a"]}) == {pb.ERT_OTTHONOK: ["a", "b"]}
    with pytest.raises(ValueError):
        pb.ervenyes({pb.ERT_OTTHONOK: "e1"})
