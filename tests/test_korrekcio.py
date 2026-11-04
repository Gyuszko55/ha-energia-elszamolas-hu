"""Korrekciós leolvasás (2.3.0b6): saját leolvasás csak a szenzor szerinti állás és a korrekciós szorzó igazítására –
nem időszakhatár, nem diktálás, nem elszámoló, és nem írja felül az aznapi rendes saját leolvasást."""
import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ServiceValidationError

import custom_components.hu_rezsi.szolgaltatasok as SZ
from custom_components.hu_rezsi.modell import diktalasi_hatarok


def _tarolt(*leolv):
    return {"merok": [{"beepitve": "2026-08-01", "kezdo_allas": "1000", "leolvasasok": list(leolv)}], "szamlak": {}}


def test_korrekcio_nem_idoszakhatar():
    t = _tarolt({"datum": "2026-09-03", "allas": "1254", "tipus": "kezi"},
                {"datum": "2026-09-20", "allas": "1300", "tipus": "kezi", "korrekcio": True},
                {"datum": "2026-10-01", "allas": "1330", "tipus": "kezi", "diktalt": True})
    assert diktalasi_hatarok(t, minden_leolvasas=True) == [date(2026, 8, 1), date(2026, 9, 3), date(2026, 10, 1)]
    assert diktalasi_hatarok(t) == [date(2026, 10, 1)]


def _hivas(monkeypatch, tarolt, **adat):
    koord = SimpleNamespace(tarolo=SimpleNamespace(fiok=lambda sid: tarolt), fiokok=lambda: {"S": SimpleNamespace(data={})})
    monkeypatch.setattr(SZ, "_celpont", lambda hass, dev: (koord, "S"))

    async def ment(k):
        return None
    monkeypatch.setattr(SZ, "_ment", ment)
    call = SimpleNamespace(data={"device_id": "d", "csatorna": "vetelezes", "tipus": "kezi", **adat})
    asyncio.run(SZ.leolvasas_rogzites(SimpleNamespace(), call))
    return tarolt["merok"][0]["leolvasasok"]


def test_korrekcio_rogzites_jelolessel(monkeypatch):
    lo = _hivas(monkeypatch, _tarolt({"datum": "2026-09-03", "allas": "1254", "tipus": "kezi"}),
                datum=date(2026, 9, 20), allas=1300.5, korrekcio=True, diktalt=True, elszamolasi=True, evkezdet=True)
    uj = lo[-1]
    assert uj["korrekcio"] is True and uj["elszamolasi"] is False and "diktalt" not in uj and "evkezdet" not in uj
    assert uj["megjegyzes"] == "korrekciós leolvasás" and uj["allas"] == "1300.5"


def test_korrekcio_nem_irja_felul_az_aznapi_leolvasast(monkeypatch):
    t = _tarolt({"datum": "2026-09-20", "allas": "1300", "tipus": "kezi", "diktalt": True})
    with pytest.raises(ServiceValidationError):
        _hivas(monkeypatch, t, datum=date(2026, 9, 20), allas=1301, korrekcio=True)
    assert t["merok"][0]["leolvasasok"] == [{"datum": "2026-09-20", "allas": "1300", "tipus": "kezi", "diktalt": True}]


def test_rendes_leolvasas_felulirja_az_aznapi_korrekciot(monkeypatch):
    lo = _hivas(monkeypatch, _tarolt({"datum": "2026-09-20", "allas": "1300", "tipus": "kezi", "korrekcio": True}),
                datum=date(2026, 9, 20), allas=1302)
    assert len(lo) == 1 and lo[0]["allas"] == "1302" and "korrekcio" not in lo[0]


def test_szolgaltatoi_nem_lehet_korrekcio(monkeypatch):
    with pytest.raises(ServiceValidationError):
        _hivas(monkeypatch, _tarolt(), datum=date(2026, 9, 20), allas=1300, korrekcio=True, tipus="szolgaltatoi")


def test_meglevo_azonos_allas_megjelolese(monkeypatch):
    """A korrekció jelölése előtt rögzített aznapi saját leolvasás utólag megjelölhető (az időpont marad)."""
    t = _tarolt({"datum": "2026-11-04", "allas": "20971", "tipus": "kezi", "ido": "08:12", "megjegyzes": "Mérő most (panel)"})
    lo = _hivas(monkeypatch, t, datum=date(2026, 11, 4), allas=20971.0, korrekcio=True)
    assert lo == [{"datum": "2026-11-04", "allas": "20971", "tipus": "kezi", "ido": "08:12", "korrekcio": True,
                   "megjegyzes": "korrekciós leolvasás (Mérő most (panel))"}]
    # más érték, vagy diktálás: nem jelöli meg, hibát ad
    with pytest.raises(ServiceValidationError):
        _hivas(monkeypatch, _tarolt({"datum": "2026-11-04", "allas": "20971", "tipus": "kezi"}), datum=date(2026, 11, 4), allas=20972, korrekcio=True)


def test_korrekcio_nem_szoritja_ki_a_szolgaltatoi_allast(monkeypatch):
    t = _tarolt({"datum": "2026-09-29", "allas": "20631", "tipus": "szolgaltatoi", "megjegyzes": "számla 1 (Leol)"})
    with pytest.raises(ServiceValidationError):
        _hivas(monkeypatch, t, datum=date(2026, 9, 29), allas=20633, korrekcio=True)
    assert len(t["merok"][0]["leolvasasok"]) == 1 and "felulirt" not in t["merok"][0]


def test_ai_szamla_marad_ujraolvasaskor():
    from custom_components.hu_rezsi.szamla_import import mappas_adatok_torlese
    from custom_components.hu_rezsi.koordinator import _ismert_masolat
    t = {"szamlak": {"PV-1": {"forras": "ai", "fajl": "pv.pdf"}, "M-1": {"forras": "mvm_aram", "fajl": "m.pdf"}},
         "reszszamlak": [{"sorszam": "PV-1"}, {"sorszam": "M-1"}],
         "merok": [{"leolvasasok": [{"datum": "2026-09-30", "allas": "1", "megjegyzes": "számla PV-1 (Leol)"},
                                     {"datum": "2026-09-30", "allas": "2", "megjegyzes": "számla M-1 (Leol)"}]}]}
    mappas_adatok_torlese(t)
    assert list(t["szamlak"]) == ["PV-1"] and t["reszszamlak"] == [{"sorszam": "PV-1"}]
    assert [lo["allas"] for lo in t["merok"][0]["leolvasasok"]] == ["1"]
    assert _ismert_masolat("pv.pdf", t)
