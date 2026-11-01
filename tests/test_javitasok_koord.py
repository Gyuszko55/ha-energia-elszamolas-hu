"""Koordinátor- és jogosultság-javítások (regresszió): egy hibás fiók nem állítja le a többit, nem véges („nan”)
szenzorállapot, korlátozott percenkénti újrapróba hiányzó forrásnál, összeg nélküli számla, fájl-újraolvasás,
számlánkénti hibatűrés a rögzítésben, diagnosztika személyes adatok nélkül. Csak kitalált adatok."""
import asyncio
from datetime import date, timedelta
from decimal import Decimal as D, InvalidOperation
from types import SimpleNamespace

import pytest

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
import modell
import szamla_import as si
import szamlak as S


# --- 1. Nem véges szenzorállapot ----------------------------------------------------------------------------


@pytest.mark.parametrize("allapot", ["nan", "NaN", "inf", "-inf", "Infinity", "unavailable", "unknown", "", None, "12,5"])
def test_szenzor_ertek_nem_veges_vagy_hibas_none(allapot):
    assert modell.szenzor_ertek(allapot) is None


def test_szenzor_ertek_szam():
    assert modell.szenzor_ertek("1234.5") == D("1234.5")
    assert modell.szenzor_ertek(" 7 ") == D(7)
    assert modell.szenzor_ertek(3) == D(3)


# --- 2. Hiányzó forrás: percenkénti újrapróba csak korlátozottan ----------------------------------------------


def test_frissitesi_perc_korlatozott_ujraprobak():
    n = modell.FORRAS_PROBAK
    assert [modell.frissitesi_perc(True, i, 10) for i in range(1, n + 1)] == [1] * n
    assert modell.frissitesi_perc(True, n + 1, 10) == 10
    assert modell.frissitesi_perc(True, 1000, 10) == 10
    assert modell.frissitesi_perc(False, 0, 10) == 10


# --- 1. Összeg nélküli számla / befizetés ---------------------------------------------------------------------


def test_befizetesek_osszeg_nelkuli_tetel_kimarad():
    tarolt = {"szamlak": {}, "reszszamlak": [
        {"datum": "2026-03-01", "osszeg": None, "sorszam": ""},
        {"datum": "2026-04-01", "osszeg": "5000", "sorszam": "A1"},
    ]}
    assert si.befizetesek_egyesitese(tarolt) == {"A1": (date(2026, 4, 1), D(5000))}


def test_rogzit_osszeg_nelkuli_kezi_befizetes_mellett():
    """A sorszám nélküli, összeg nélküli kézi tétel a duplikátum-keresésnél ne dobjon (Decimal('None'))."""
    tarolt = {"merok": [], "almero_merok": [], "reszszamlak": [{"datum": "2026-05-02", "osszeg": None}]}
    sz = S.Szamla("mvm_gaz", "77", date(2026, 5, 2), D(9000), "resz")
    j = si.rogzit(tarolt, [sz])
    assert j.szamlak == ["77"] and any(r.get("sorszam") == "77" for r in tarolt["reszszamlak"])


# --- 5b. Rögzítés: egy hibás számla nem akasztja meg a többit ---------------------------------------------------


def test_rogzit_hibas_szamla_visszaall_a_tobbi_rogzul():
    tarolt = {"merok": [], "almero_merok": [], "reszszamlak": []}
    rossz = S.Szamla("mvm_gaz", "1", date(2026, 1, 5), D(1000), "resz", futoertekek={"2026-01": "nem szám"})
    jo = S.Szamla("mvm_gaz", "2", date(2026, 2, 5), D(2000), "resz", futoertekek={"2026-02": D("34.5")})
    j = si.rogzit(tarolt, [rossz, jo])
    # A hibás számla nyom nélkül kimarad (nem „feldolgozott”, nincs befizetése), a jó rögzül.
    assert set(tarolt["szamlak"]) == {"2"}
    assert [r["sorszam"] for r in tarolt["reszszamlak"]] == ["2"]
    assert tarolt["futoertekek"] == {"2026-02": "34.5"}
    assert j.szamlak == ["2"] and j.futoertekek == 1
    assert any("1" in f and "nem rögzíthető" in f for f in j.figyelmeztetesek)


# --- 5a. Megnevezett fájlok újraolvasása: a fel nem ismertek közül is kikerülnek ----------------------------------


def test_fajlok_ujraolvasasra_nem_olvasott_is_torlodik():
    tarolt = {"feldolgozott_fajlok": ["a.pdf", "b.pdf"], "nem_olvasott_fajlok": {"x.pdf": "10|20", "y.pdf": "1|2"}}
    si.fajlok_ujraolvasasra(tarolt, {"a.pdf", "x.pdf"})
    assert tarolt["feldolgozott_fajlok"] == ["b.pdf"]
    assert tarolt["nem_olvasott_fajlok"] == {"y.pdf": "1|2"}


def test_fajlok_ujraolvasasra_nem_olvasott_nelkul():
    tarolt = {"feldolgozott_fajlok": ["a.pdf"]}
    si.fajlok_ujraolvasasra(tarolt, {"a.pdf"})
    assert tarolt == {"feldolgozott_fajlok": []}


# --- 1. Koordinátor: egy hibás fiók nem viszi magával a többit (HA-csomag, futó HA nélkül) ------------------------


def _koordinator(monkeypatch, fiok_hiba):
    from custom_components.hu_rezsi import koordinator as K

    k = object.__new__(K.RezsiKoordinator)
    mentve = []
    subok = {sid: SimpleNamespace(data={K.CONF_KOZMU: "viz", K.CONF_FORRAS: f"sensor.{sid}"}, title=sid) for sid in ("A", "B")}
    tarolok = {sid: {"merok": [{"gyari_szam": "1"}]} for sid in subok}

    async def futtat(fn, *args):
        return fn(*args)

    async def ment():
        mentve.append(True)

    async def fiok(sid, sub, tarolt, most, egyseg):
        if sid in fiok_hiba:
            raise fiok_hiba[sid]
        return K.FiokAllapot(egyseg=egyseg), True

    async def semmi(*_a, **_k):
        return False

    async def szigetek(_k, _most):
        return {}

    def dijnet_hibas(*_a):
        raise ValueError("hibás Díjnet-YAML")

    k.hass = SimpleNamespace(async_add_executor_job=futtat, config=SimpleNamespace(config_dir="/nincs"))
    k.config_entry = SimpleNamespace(entry_id="E1")
    k.tarolo = SimpleNamespace(fiok=lambda sid: tarolok[sid], adat={"fiokok": dict(tarolok)}, ment=ment)
    k.fiokok = lambda: subok
    k.mappa_halasztva = True
    k.elonezet = {}
    k._forras_probak = 0
    k._hianyzo_forrasok = set()
    k._naplozott_hibak = set()
    k._fiok = fiok
    k._kezdes_ujrabazis = semmi
    k._ellenorzes = semmi
    monkeypatch.setattr(K, "mero_szinkron", lambda *_a: False)
    monkeypatch.setattr(K, "kezdo_origo_szinkron", lambda *_a: False)
    monkeypatch.setattr(K.sziget_ha, "szamol_mind", szigetek)
    monkeypatch.setattr(K.dijnet, "fizetett", dijnet_hibas)
    monkeypatch.setattr(K.ir, "async_create_issue", lambda *a, **kw: None)
    monkeypatch.setattr(K.ir, "async_delete_issue", lambda *a, **kw: None)
    return k, mentve


@pytest.mark.parametrize("hiba", [InvalidOperation(), TypeError("x"), ZeroDivisionError("y")])
def test_szamol_egy_hibas_fiok_nem_allitja_le_a_tobbit(monkeypatch, hiba):
    k, mentve = _koordinator(monkeypatch, {"A": hiba})
    kimenet = asyncio.run(k._szamol())
    assert kimenet["A"].hiba and type(hiba).__name__ in kimenet["A"].hiba
    assert kimenet["B"].hiba is None
    assert mentve  # a tárolt adat mentése (és a Díjnet-frissítés) nem marad ki
    assert k.dijnet_kesz  # a hibás Díjnet-fájl sem állítja meg a frissítést
    # Ugyanaz a hiba másodszor már nem kerül részletesen a naplóba.
    asyncio.run(k._szamol())
    assert len(k._naplozott_hibak) == 1


def test_szamol_hianyzo_forras_utemezes(monkeypatch):
    from custom_components.hu_rezsi import koordinator as K

    k, _ = _koordinator(monkeypatch, {})
    letrehozott = []
    monkeypatch.setattr(K.ir, "async_create_issue", lambda hass, dom, iid, **kw: letrehozott.append((iid, kw)))

    async def fiok_hianyzo(sid, sub, tarolt, most, egyseg):
        k._forras_hianyzik = True
        k._hianyzo_forrasok.add("sensor.nincs")
        return K.FiokAllapot(egyseg=egyseg), False

    k._fiok = fiok_hianyzo
    percek = []
    for _ in range(modell.FORRAS_PROBAK + 2):
        asyncio.run(k._szamol())
        percek.append(k.update_interval)
    assert percek[: modell.FORRAS_PROBAK] == [timedelta(minutes=1)] * modell.FORRAS_PROBAK
    assert percek[-1] == timedelta(minutes=K.FRISSITES_PERC)
    assert letrehozott and "sensor.nincs" in letrehozott[-1][1]["translation_placeholders"]["entitasok"]


# --- 4. Diagnosztika: személyes adatok nélkül, alfiók-azonosító szerint -------------------------------------------


def test_diagnosztika_kitakar_es_sid_szerint():
    from custom_components.hu_rezsi import diagnostics as DG

    tarolt = {
        "merok": [{"gyari_szam": "GY-123", "leolvasasok": [{"datum": "2026-01-01", "allas": "5"}]}],
        "szamlak": {"100": {"osszeg": "1000", "ugyfel": {"nev": "Minta Béla", "hely": "Minta u. 1."}}},
        "meresi_pontok": {"HU000PONT": ["GY-123"]},
    }
    sub = SimpleNamespace(title="Kossuth u. 3. – villany", data={"szamla_mappa": "Dijnet /x", "dijnet_szolgaltato": "MVM", "kozmu": "villany"})
    koord = SimpleNamespace(fiokok=lambda: {"SID1": sub}, data={}, tarolo=SimpleNamespace(fiok=lambda sid: tarolt), utolso_szamlalok={})
    ki = asyncio.run(DG.async_get_config_entry_diagnostics(None, SimpleNamespace(runtime_data=koord)))
    assert list(ki["fiokok"]) == ["SID1"]
    szoveg = repr(ki)
    for titok in ("Minta Béla", "Minta u. 1.", "GY-123", "HU000PONT", "Dijnet /x", "Kossuth"):
        assert titok not in szoveg
    assert ki["fiokok"]["SID1"]["beallitas"]["kozmu"] == "villany"
    assert tarolt["merok"][0]["gyari_szam"] == "GY-123"  # a tárolt adat érintetlen
