"""2.4.1: a HACS-bírálat (hacs/default#13437) öt pontja – TLS-ellenőrzés, fájlvizsgálat szálon, személyes adat nélküli
Utolsó számla szenzor, jelszó nélküli mentés HA-mentésből, a HA-mentés kulcsa a felhasználótól."""

import asyncio
import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi

CS = Path(__file__).resolve().parents[1] / "custom_components" / "hu_rezsi"


# --- 1. IMAP: tanúsítvány és gépnév ellenőrzése -----------------------------------------------------------------
def test_imap_tls_ellenoriz(monkeypatch):
    import email_szamlak as es

    ctx = es.ssl_kontextus()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    hivasok = []

    class Ssl:
        def __init__(self, *a, **kw):
            hivasok.append(("ssl", kw))

        def login(self, *a):
            return "OK", []

    class Sima:
        def __init__(self, *a, **kw):
            pass

        def starttls(self, **kw):
            hivasok.append(("starttls", kw))

        def login(self, *a):
            return "OK", []

    monkeypatch.setattr(es.imaplib, "IMAP4_SSL", Ssl)
    monkeypatch.setattr(es.imaplib, "IMAP4", Sima)
    es.kapcsolodik(es.Postafiok("p", "P", "a@b.hu", "titok", "imap.example.com", 993, True))
    es.kapcsolodik(es.Postafiok("p", "P", "a@b.hu", "titok", "imap.example.com", 143, False))
    assert [h[0] for h in hivasok] == ["ssl", "starttls"]
    assert all(isinstance(h[1].get("ssl_context"), ssl.SSLContext) for h in hivasok)


# --- 2. fájlvizsgálat nem az eseményhurkon ----------------------------------------------------------------------
def test_fajlvizsgalat_szalon():
    src = (CS / "koordinator.py").read_text(encoding="utf-8")
    assert "p = self._ai_fajl(sub, fajl)" not in src
    assert src.count("await self.hass.async_add_executor_job(self._ai_fajl, sub, fajl)") == 2
    # a négy, eddig az eseményhurkon futó .exists() mind végrehajtó szálon
    assert 'and not (mappa / f).with_suffix(".xml").exists()})' in src
    assert "lambda: [(k, x.get(\"fajl\") or f\"{k}.pdf\") for k, x in szamlak_" in src
    assert "lambda: {f.name for f, x in zip(fajlok, beolvasott, strict=True)" in src


# --- 3. Utolsó számla: személyes adat nélkül --------------------------------------------------------------------
def test_utolso_szamla_attributumai():
    from custom_components.hu_rezsi import sensor

    teljes = {"sorszam": "123", "kelte": "2026-10-05", "osszeg": "12345", "tipus": "elszamolo",
              "idoszak": {"tol": "2026-09-01", "ig": "2026-09-30"}, "hatarido": "2026-10-20", "szamlak_szama": 7,
              "ugyfel": {"nev": "Minta Elek", "cim": "Példa u. 1."}, "fizetesi_mod": "csoportos", "tetelek": [1],
              "fajl": "szamla.pdf", "allasok": [], "folyoszamla": {}}
    attr = sensor.utolso_szamla_attr(teljes)
    assert set(attr) == {"sorszam", "kelte", "osszeg", "tipus", "idoszak", "hatarido", "szamlak_szama"}
    assert sensor.utolso_szamla_attr(None) == {}
    src = (CS / "sensor.py").read_text(encoding="utf-8")
    assert "attr=lambda a: utolso_szamla_attr(a.utolso_szamla)" in src


# --- 4. HA-mentésből készült mentés: jelszó nélkül --------------------------------------------------------------
def test_ha_mentesbol_jelszo_nelkul():
    import mentes as m

    t = m.HaMentesTartalom(config_entries={"data": {"entries": [{
        "domain": "hu_rezsi", "title": "Otthon", "entry_id": "e1",
        "subentries": [{"subentry_id": "s1", "subentry_type": "postafiok", "title": "Posta",
                        "data": {"felhasznalo": "a@b.hu", "jelszo": "titok", "szerver": "imap.example.com"}}]}]}},
        entity_registry={"data": {"entities": []}})
    otthon = m.ha_mentesbol_otthonok(t)[0]
    adat = otthon.alarendeltek[0]["data"]
    assert "jelszo" not in adat and adat["felhasznalo"] == "a@b.hu"
    assert m.jelszo_nelkuli_postafiokok(otthon.alarendeltek) == ["Posta"]


# --- 5. a HA-mentés kulcsa: a felhasználótól, nem a HA beállításaiból -------------------------------------------
def test_ha_mentes_kulcsa_a_felhasznalotol(monkeypatch):
    from homeassistant.components.backup import DATA_MANAGER

    from custom_components.hu_rezsi import mentes as m
    from custom_components.hu_rezsi import mentes_ha

    src = (CS / "mentes_ha.py").read_text(encoding="utf-8")
    assert "create_backup.password" not in src
    agent_backup = SimpleNamespace(protected=True)
    agent = SimpleNamespace(async_get_backup=lambda bid: asyncio.sleep(0, result=agent_backup))
    b = SimpleNamespace(agents={"hassio.local": SimpleNamespace(size=1, protected=True)}, name="Mentés",
                        date="2026-11-13T10:00:00+01:00", homeassistant_version="2026.11.0")
    manager = SimpleNamespace(async_get_backups=lambda: asyncio.sleep(0, result=({"b1": b}, {})),
                              backup_agents={"hassio.local": agent}, local_backup_agents={},
                              config=SimpleNamespace(data=SimpleNamespace(create_backup=SimpleNamespace(password="HA-KULCS"))))
    hass = SimpleNamespace(data={DATA_MANAGER: manager})
    with pytest.raises(m.MentesHiba, match="titkosítási kulcsát"):
        asyncio.run(mentes_ha.ha_mentesbol(hass, "b1"))  # a HA saját kulcsát nem veszi elő
    panel = (CS / "panel.py").read_text(encoding="utf-8")
    assert 'vol.Optional("jelszo"): str' in panel and 'msg.get("jelszo")' in panel
    js = (CS / "frontend" / "rezsi-panel-fo.js").read_text(encoding="utf-8")
    assert "data-hakulcs" in js and "jelszo: kulcs" in js and 'type="password"' in js


def test_verzio():
    import json

    assert json.loads((CS / "manifest.json").read_text(encoding="utf-8"))["version"] == "2.4.1"
