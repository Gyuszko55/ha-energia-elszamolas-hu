"""Számlák e-mailből – egyszerű beállítás és automatikus besorolás: levelező felismerése a címből, jelszó-szóközök,
közérthető hibák, a felderítés besorolása (egyértelmű → bekötés, kétes → kérdés, nincs fiók → ajánlat), a tartalom
szerinti óránkénti besorolás (villany és gáz ugyanattól a feladótól, Telekom-értesítő), a panel websocket-parancsai
(rendszergazda-ellenőrzés), a postafiók létrehozása alárendelt bejegyzésként és a „nem kell” válaszok megőrzése.

Hálózat nélkül: hamis IMAP-kliens, hamis beolvasó-eredmények (szamlak.Szamla) – minden adat kitalált."""

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from tests.test_email_szamlak import GMAIL_LIST, OSSZES, HamisImap, level

from custom_components.hu_rezsi import email_ha
from custom_components.hu_rezsi import email_szamlak as es
from custom_components.hu_rezsi import panel
from custom_components.hu_rezsi import szamlak

MA = date(2026, 11, 1)
TERKEP = {"mvmee.hu": {"mvm_demasz", "eon", "opus_titasz", "elmu", "elmu_emasz", "mvm_next"}, "telekom.hu": {"telekom"}}


# --------------------------------------------------------------------------------------------- segédek


def szamla(forras, sorszam, merok=(), arszabas=None, osszeg=10000, kelte=date(2026, 10, 5)):
    return szamlak.Szamla(forras=forras, sorszam=sorszam, kelte=kelte, osszeg=Decimal(osszeg), tipus="resz",
                          kapcsolt_merok=set(merok), arszabas=arszabas)


# Hamis beolvasó: a melléklet neve mondja meg, milyen számla (a valódi PDF-olvasót a test_szamlak teszteli).
HAMIS_SZAMLAK = {
    "Villany_9000000001.pdf": szamla("mvm_aram", "9000000001", {"11111111"}, "A1"),
    "Villany_9000000002.pdf": szamla("mvm_aram", "9000000002", {"22222222"}, "H"),
    "Gaz_9000000003.pdf": szamla("mvm_gaz", "9000000003", {"G-33333"}),
    "Villany_9000000009.pdf": szamla("mvm_aram", "9000000009", {"99999999"}, "A1"),
}


@pytest.fixture
def hamis_beolvaso(monkeypatch):
    monkeypatch.setattr(es, "_beolvas", lambda f: HAMIS_SZAMLAK.get(f.name))


class TartalomImap(HamisImap):
    """A hamis IMAP kiegészítve: melléklet szerinti Gmail-keresés („filename:pdf”), szabványos SINCE-keresés és
    BODYSTRUCTURE (a melléklet felismeréséhez letöltés nélkül)."""

    def uid(self, parancs, *args):
        if parancs == "SEARCH":
            self.hivasok.append(("uid", parancs, *args))
            levelek = self.mappak[self.kivalasztott]
            feltetel = " ".join(args).lower()
            if args and args[0] == "SINCE" and len(args) == 2:
                return "OK", [b" ".join(levelek)]
            if "filename:pdf" in feltetel:
                talalt = [u for u, n in levelek.items() if b".pdf" in n.lower() or b".xml" in n.lower()
                          or any(f in self._felado(n) for f in tests.test_email_szamlak._feladok_a_feltetelbol(feltetel))]
                return "OK", [b" ".join(talalt)]
        if parancs == "FETCH" and args[1] == "(BODYSTRUCTURE)":
            self.hivasok.append(("uid", parancs, *args))
            nyers = self.mappak[self.kivalasztott][args[0]]
            szerk = b'("application" "pdf" NIL NIL "base64" 10)' if b".pdf" in nyers.lower() else b'("text" "plain" NIL NIL "7bit" 10)'
            return "OK", [b"1 (UID " + args[0] + b" BODYSTRUCTURE " + szerk + b")"]
        return super().uid(parancs, *args)


def _pf(**kw):
    return es.Postafiok(sid="PF1", nev="Saját", felhasznalo="valaki@example.com", jelszo="titok", **kw)


def _auto(sid, kozmu, szolg, merok=(), dijszabas=None, mappa=None, sorszamok=(), feladok=("mvmee.hu",)):
    return es.AutoFiok(sid=sid, nev=sid, mappa=mappa, kozmu=kozmu, szolgaltato=szolg, arszabas=es.ARSZABASOK.get(dijszabas),
                       merok=set(merok), sorszamok=set(sorszamok), feladok=list(feladok))


TELEKOM_SZOVEG = ("Tisztelt Ügyfelünk! Elkészült a számlája. Számla sorszáma: 700000000123 Számlázott összeg: 9 990 Ft "
                  "Számla kelte: 2026.10.05 Beérkezési határidő: 2026.10.20")


# --------------------------------------------------------------------------------------------- levelező, jelszó


@pytest.mark.parametrize("cim,szerver,kulcs,ismert", [
    ("valaki@gmail.com", "imap.gmail.com", "gmail", True),
    ("Valaki@GoogleMail.com", "imap.gmail.com", "gmail", True),
    ("valaki@freemail.hu", "imap.freemail.hu", "freemail", True),
    ("valaki@citromail.hu", "imap.citromail.hu", "citromail", True),
    ("valaki@hotmail.com", "outlook.office365.com", "outlook", True),
    ("valaki@live.com", "outlook.office365.com", "outlook", True),
    ("valaki@yahoo.com", "imap.mail.yahoo.com", "yahoo", True),
    ("valaki@me.com", "imap.mail.me.com", "icloud", True),
    ("valaki@pelda-szolgaltato.hu", "imap.pelda-szolgaltato.hu", "egyeb", False),
])
def test_levelezo_a_cim_domainjebol(cim, szerver, kulcs, ismert):
    lv = es.levelezo(cim)
    assert (lv["szerver"], lv["kulcs"], lv["ismert"], lv["port"], lv["ssl"]) == (szerver, kulcs, ismert, 993, True)
    assert es.levelezo("valaki@outlook.com").get("nem_tamogatott") is True
    assert es.levelezo("valaki@gmail.com")["link"] == "https://myaccount.google.com/apppasswords"


def test_jelszo_szokozok_csak_a_csoportos_alkalmazasjelszonal():
    for szerver in ("imap.gmail.com", "imap.mail.yahoo.com", "imap.mail.me.com", "outlook.office365.com"):
        assert es.jelszo_tisztitas("abcd efgh ijkl mnop", szerver) == "abcdefghijklmnop", szerver
    assert es.jelszo_tisztitas("titkos jelszo", "imap.freemail.hu") == "titkos jelszo"
    assert es.Postafiok.adatbol("P", "x", {"imap_szerver": "imap.mail.yahoo.com", "jelszo": "ab cd"}).jelszo == "abcd"
    assert es.Postafiok.adatbol("P", "x", {"imap_szerver": "imap.freemail.hu", "jelszo": "ab cd"}).jelszo == "ab cd"


def test_postafiok_adat_a_cimbol_es_alap_nev():
    adat, nev = email_ha.postafiok_adat({"email_cim": "kovacs.anna@freemail.hu", "jelszo": "x y"})
    assert nev == "kovacs.anna" and adat["imap_szerver"] == "imap.freemail.hu" and adat["jelszo"] == "x y"
    assert adat["imap_port"] == 993 and adat["imap_ssl"] is True and adat["email_napok"] == 45 and adat["email_kuka"] is True
    adat, nev = email_ha.postafiok_adat({"email_cim": "a@gmail.com", "jelszo": "", "nev": "Párom"}, {"jelszo": "regi", "imap_port": 993})
    assert nev == "Párom" and adat["jelszo"] == "regi"
    adat, _ = email_ha.postafiok_adat({"email_cim": "a@sajat.hu", "jelszo": "j", "imap_szerver": "mail.sajat.hu", "imap_port": 143})
    assert adat["imap_szerver"] == "mail.sajat.hu" and adat["imap_port"] == 143


def _hass_exec():
    async def executor(fn, *args):
        return fn(*args)
    return SimpleNamespace(async_add_executor_job=executor)


def test_bejelentkezes_ellenorzes_kozertheto_hibakkal(monkeypatch):
    hass = _hass_exec()

    def futtat(adat):
        return asyncio.run(email_ha.bejelentkezes_ellenorzes(hass, email_ha.postafiok_adat(adat)[0]))

    assert futtat({"email_cim": "nem-cim", "jelszo": "x"}) == "cim_hibas"
    assert futtat({"email_cim": "a@gmail.com", "jelszo": ""}) == "jelszo_kell"
    assert futtat({"email_cim": "a@hotmail.com", "jelszo": "x"}) == "nem_tamogatott"

    def rossz(pf):
        raise es.HitelesitesiHiba("x")

    monkeypatch.setattr(es, "bejelentkezes_proba", rossz)
    assert futtat({"email_cim": "a@gmail.com", "jelszo": "x"}) == "hitelesites_gmail"
    assert futtat({"email_cim": "a@freemail.hu", "jelszo": "x"}) == "hitelesites_freemail"
    assert futtat({"email_cim": "a@sajat.hu", "jelszo": "x"}) == "hitelesites"
    assert "https://myaccount.google.com/apppasswords" in email_ha.hiba_szoveg("hitelesites_gmail", "imap.gmail.com")
    assert "alkalmazásjelszó kell, nem a szokásos jelszavad" in email_ha.hiba_szoveg("hitelesites_gmail", "imap.gmail.com")

    def nincs(pf):
        raise es.KapcsolatiHiba("x")

    monkeypatch.setattr(es, "bejelentkezes_proba", nincs)
    assert futtat({"email_cim": "a@sajat.hu", "jelszo": "x"}) == "szerver_ismeretlen"  # a kitalált imap.<domain> nem él
    assert futtat({"email_cim": "a@gmail.com", "jelszo": "x"}) == "kapcsolat"
    monkeypatch.setattr(es, "bejelentkezes_proba", lambda pf: None)
    assert futtat({"email_cim": "a@gmail.com", "jelszo": "x"}) is None


def test_hitelesitesi_hiba_szovege_levelezonkent():
    assert "myaccount.google.com/apppasswords" in es.hitelesites_szoveg("imap.gmail.com")
    assert "Yahoo" in es.hitelesites_szoveg("imap.mail.yahoo.com")
    assert "továbbítást" in es.hitelesites_szoveg("outlook.office365.com")
    assert es.lepesek("gmail")[0].startswith("Nyisd meg ezt az oldalt: https://myaccount.google.com/apppasswords")
    assert es.lepesek_szoveg("freemail").startswith("1. ")


# --------------------------------------------------------------------------------------------- tartalom szerinti választás


def test_tartalom_mero_szolgaltato_es_arszabas():
    a1 = _auto("A1", "villany", "mvm_demasz", {"11111111"}, "villany/a1")
    h = _auto("H", "villany", "mvm_demasz", {"22222222"}, "villany/h")
    gaz = _auto("GAZ", "gaz", "mvm_next")
    fiokok = [a1, h, gaz]
    jel = es.szamla_jel(HAMIS_SZAMLAK["Villany_9000000001.pdf"])
    assert es.tartalom_valasztas(jel, fiokok) == ([a1], "mero")
    jel = es.szamla_jel(HAMIS_SZAMLAK["Gaz_9000000003.pdf"])
    lista, ok = es.tartalom_valasztas(jel, fiokok)
    assert lista == [gaz] and ok == "szolgaltato" and es.egyertelmu(lista, ok) is gaz  # villany és gáz: ugyanaz a feladó
    # Ismeretlen mérő, de van ilyen szolgáltatójú fiók másik mérővel: kérdés (mérőcsere vagy másik ingatlan).
    jel = es.szamla_jel(HAMIS_SZAMLAK["Villany_9000000009.pdf"])
    lista, ok = es.tartalom_valasztas(jel, fiokok)
    assert ok == "mas_mero" and lista == [a1] and es.egyertelmu(lista, ok) is None  # az árszabás (A1) szűkít
    # A már ismert sorszám maga a bizonyíték.
    gaz.sorszamok = {"9000000009"}
    assert es.tartalom_valasztas(jel, fiokok) == ([gaz], "ismert")


def test_tartalom_ket_mero_nelkuli_villanyfiok_kerdes():
    v1, v2 = _auto("V1", "villany", "eon"), _auto("V2", "villany", "elmu")
    lista, ok = es.tartalom_valasztas(es.szamla_jel(szamla("mvm_aram", "1", {"5"})), [v1, v2])
    assert lista == [v1, v2] and es.egyertelmu(lista, ok) is None
    lista, ok = es.tartalom_valasztas(es.szamla_jel(szamla("mvm_aram", "1", {"5"})), [v1, _auto("T", "tavkozles", "telekom")])
    assert es.egyertelmu(lista, ok) is v1  # egy MVM-villanyfiók van: az az


def test_auto_fiok_adatai_a_beallitasbol_es_a_tarbol(tmp_path):
    f = es.AutoFiok.adatbol("S", "Villany", {"kozmu": "villany", "szolgaltato": "eon", "dijszabas": "villany/h", "gyari_szam": "00123",
                                              "szamla_merok": "456, 789", "szamla_mappa": "Szamlak/V", "email_irsz": "1111"},
                            {"merok": [{"gyari_szam": "0321"}], "meresi_pontok": {"HU000X": ["654"]}, "szamlak": {"S1": {}}}, tmp_path)
    assert f.merok == {"123", "456", "789", "321", "654"} and f.meresi_pontok == {"HU000X"} and f.sorszamok == {"S1"}
    assert f.arszabas == "H" and f.irszok == ["1111"] and f.mappa == (tmp_path / "Szamlak/V").resolve()


def test_osztalyozas_harom_esete_es_mellozes():
    a1 = _auto("A1", "villany", "mvm_demasz", {"11111111"}, "villany/a1")
    h = _auto("H", "villany", "mvm_demasz", {"22222222"}, "villany/h")
    gaz = _auto("GAZ", "gaz", "mvm_next")
    jelek = [es.szamla_jel(HAMIS_SZAMLAK[n]) for n in ("Villany_9000000001.pdf", "Gaz_9000000003.pdf", "Villany_9000000009.pdf")]
    jelek.append(es.ertesito_jel(es.ertesito_szamla(TELEKOM_SZOVEG), {"telekom"}))
    fe = es.osztalyoz(jelek, [a1, h, gaz])
    assert set(fe.osszekot) == {"A1", "GAZ"} and fe.osszekot["GAZ"]["forrasok"] == ["mvm_gaz"]
    assert [k["id"] for k in fe.kerdesek] == ["mvm_aram|99999999"] and fe.kerdesek[0]["jeloltek"] == [{"sid": "A1", "nev": "A1"}]
    assert [a["id"] for a in fe.ajanlatok] == ["telekom|-"] and fe.ajanlatok[0]["kozmu"] == "tavkozles"
    assert fe.ajanlatok[0]["osszeg"] == 9990 and fe.talalt == 4
    # „Egyik sem / Nem kell”: legközelebb nem kérdez; a kézi szűrővel már bekötött fiókot nem írja át.
    fe = es.osztalyoz(jelek, [a1, h, gaz], mellozott={"mvm_aram|99999999", "telekom|-"}, kezi={"A1"})
    assert fe.kerdesek == [] and fe.ajanlatok == [] and set(fe.osszekot) == {"GAZ"} and set(fe.mar_bekotve) == {"A1"}


# --------------------------------------------------------------------------------------------- IMAP: felderítés, átnézés


def _postafiok(gmail=True):
    villany = level("MVM Next <ugyfelszolgalat@mvmee.hu>", "Villanyszámla", "<v1@x>",
                    mellekletek=[("Villany_9000000001.pdf", b"%PDF-hamis-1")])
    gaz = level("MVM Next <ugyfelszolgalat@mvmee.hu>", "Gázszámla", "<g1@x>", mellekletek=[("Gaz_9000000003.pdf", b"%PDF-hamis-3")])
    tovabbitott = level("Párom <parom@example.com>", "Fwd: számla", "<f1@x>",
                        mellekletek=[("Villany_9000000002.pdf", b"%PDF-hamis-2")])
    telekom = level("Telekom <ertesito@telekom.hu>", "Elkészült a számlája", "<t1@x>", szoveg=TELEKOM_SZOVEG)
    hirlevel = level("Bolt <hirlevel@bolt.example>", "Akció", "<h1@x>")
    egyeb_pdf = level("Iskola <info@iskola.example>", "Menü", "<m1@x>", mellekletek=[("menu.pdf", b"%PDF-menu")])
    mappak = {OSSZES: {b"1": villany, b"2": gaz, b"3": tovabbitott, b"4": telekom, b"5": hirlevel, b"6": egyeb_pdf},
              "[Gmail]/Kuka": {b"9": gaz}}
    if not gmail:
        return TartalomImap({"INBOX": mappak[OSSZES], "Trash": {b"9": gaz}},
                            [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Trash) "/" "Trash"', b'(\\Sent) "/" "Sent"'], gmail=False)
    return TartalomImap(mappak, GMAIL_LIST)


@pytest.mark.parametrize("gmail", [True, False])
def test_felderites_csak_olvas_es_megtalalja_a_szamlakat(hamis_beolvaso, gmail):
    imap = _postafiok(gmail)
    jelek = es.felderit(_pf(), MA, TERKEP, gyar=lambda pf: imap)
    assert sorted(j.sorszam for j in jelek) == ["700000000123", "9000000001", "9000000002", "9000000003"]  # a Kukában lévő is egyszer
    telekom = next(j for j in jelek if j.forras == "telekom")
    assert telekom.tipus == "ertesito" and telekom.osszeg == 9990
    assert all(h[2] is True for h in imap.hivasok if h[0] == "select")  # csak olvasásra
    assert ("select", '"Sent"', True) not in imap.hivasok
    assert imap.kilepett


def test_atnezes_tartalom_szerint_villany_gaz_es_telekom(tmp_path, hamis_beolvaso):
    imap = _postafiok()
    a1 = _auto("A1", "villany", "mvm_demasz", {"11111111"}, "villany/a1", mappa=tmp_path / "A1")
    h = _auto("H", "villany", "mvm_demasz", {"22222222"}, "villany/h", mappa=tmp_path / "H")
    gaz = _auto("GAZ", "gaz", "mvm_next", mappa=tmp_path / "GAZ")
    tk = _auto("TK", "tavkozles", "telekom", mappa=tmp_path / "TK", feladok=("telekom.hu",))
    er = es.atnez(_pf(), [], set(), {}, MA, gyar=lambda pf: imap, auto=[a1, h, gaz, tk], felado_terkep=TERKEP)
    assert {(m["fiok"], m["fajl"]) for m in er.mentett} == {
        ("A1", "Villany_9000000001.pdf"), ("GAZ", "Gaz_9000000003.pdf"), ("H", "Villany_9000000002.pdf")}  # a továbbított is
    assert (tmp_path / "H" / "Villany_9000000002.pdf").read_bytes() == b"%PDF-hamis-2"
    assert [(x["fiok"], x["adat"]["sorszam"]) for x in er.ertesitok] == [("TK", "700000000123")]
    assert er.nem_besorolhato == []
    assert len(er.latott) == 5  # az iskolai PDF is „látott” (nem töltjük le újra); a hírlevelet a keresés ki sem adja
    # Másodszor: semmi új.
    er2 = es.atnez(_pf(), [], {"9000000001", "9000000002", "9000000003", "700000000123"}, er.latott, MA, gyar=lambda pf: _postafiok(),
                   auto=[a1, h, gaz, tk], felado_terkep=TERKEP)
    assert er2.mentett == [] and er2.ertesitok == []


def test_atnezes_tartalom_ketes_eset_tartalek_kezi_szurovel(tmp_path, hamis_beolvaso):
    """Két mérő nélküli villanyfiók: a tartalom nem dönt – a kézi szűrő (tárgy) választ; szűrő nélkül nem besorolható."""
    v1 = _auto("V1", "villany", "eon", mappa=tmp_path / "V1")
    v2 = _auto("V2", "villany", "elmu", mappa=tmp_path / "V2")
    er = es.atnez(_pf(), [], set(), {}, MA, gyar=lambda pf: _postafiok(), auto=[v1, v2], felado_terkep=TERKEP)
    assert er.mentett == [] and {tuple(x["fiokok"]) for x in er.nem_besorolhato} == {("V1", "V2")}
    kezi = es.FiokSzuro(sid="V2", nev="V2", mappa=tmp_path / "V2", feladok=["mvmee.hu", "example.com"], targy="villany")
    er = es.atnez(_pf(), [kezi], set(), {}, MA, gyar=lambda pf: _postafiok(), auto=[v1, v2], felado_terkep=TERKEP)
    assert {m["fajl"] for m in er.mentett} == {"Villany_9000000001.pdf"}  # a „Villanyszámla” tárgyú a V2-é
    assert [x["fiokok"] for x in er.nem_besorolhato] == [["V1", "V2"]]  # a továbbított („Fwd: számla”) kétes marad


# --------------------------------------------------------------------------------------------- HA-oldal


class HamisBejegyzesek:
    def __init__(self, entry):
        self.entry = entry
        self.frissitett: list[tuple[str, dict]] = []
        self.hozzaadott: list = []

    def async_update_subentry(self, entry, sub, *, data):
        self.frissitett.append((sub.subentry_id, dict(data)))
        sub.data = dict(data)
        return True

    def async_add_subentry(self, entry, sub):
        self.hozzaadott.append(sub)
        entry.subentries[sub.subentry_id] = sub
        return True

    def async_entries(self, domain=None):
        return [self.entry]

    def async_get_entry(self, entry_id):
        return self.entry if entry_id == self.entry.entry_id else None


def _sub(sid, tipus, title, data):
    return SimpleNamespace(subentry_id=sid, subentry_type=tipus, title=title, data=dict(data))


def _otthon(tmp_path, monkeypatch, fiokok=None):
    from homeassistant.config_entries import ConfigEntryState

    monkeypatch.setattr(email_ha.ir, "async_create_issue", lambda *a, **k: None)
    monkeypatch.setattr(email_ha.ir, "async_delete_issue", lambda *a, **k: None)
    ertesitesek = []
    monkeypatch.setattr(email_ha.persistent_notification, "async_create", lambda hass, uz, **kw: ertesitesek.append(uz))
    subs = {"PF1": _sub("PF1", "postafiok", "Saját", {"email_cim": "valaki@gmail.com", "jelszo": "titok", "imap_szerver": "imap.gmail.com"})}
    for f in fiokok or [
        _sub("A1", "fiok", "Villany A1", {"kozmu": "villany", "szolgaltato": "mvm_demasz", "dijszabas": "villany/a1", "gyari_szam": "11111111"}),
        _sub("H", "fiok", "H tarifa", {"kozmu": "villany", "szolgaltato": "mvm_demasz", "dijszabas": "villany/h", "gyari_szam": "22222222"}),
        _sub("GAZ", "fiok", "Gáz", {"kozmu": "gaz", "szolgaltato": "mvm_next", "szamla_mappa": "Szamlak/Gaz"}),
    ]:
        subs[f.subentry_id] = f

    async def executor(fn, *args):
        return fn(*args)

    mentve = []

    async def ment():
        mentve.append(True)

    async def frissit():
        pass

    entry = SimpleNamespace(entry_id="E1", title="Kertes ház", subentries=subs, domain="hu_rezsi", state=ConfigEntryState.LOADED,
                            async_create_background_task=lambda hass, coro, nev: hatter.append(coro))
    hatter = []
    tar = SimpleNamespace(szolgaltatok={"mvm_demasz": {"nev": "MVM Démász", "email_feladok": ["mvmee.hu"]},
                                        "mvm_next": {"nev": "MVM Next", "email_feladok": ["mvmee.hu"]},
                                        "telekom": {"nev": "Magyar Telekom", "email_feladok": ["telekom.hu"]}})
    koord = SimpleNamespace(fiokok=lambda: {k: v for k, v in entry.subentries.items() if v.subentry_type == "fiok"},
                            tarolo=SimpleNamespace(adat={"fiokok": {}}, ment=ment), tar=tar, async_request_refresh=frissit, _zar=asyncio.Lock())
    hass = SimpleNamespace(async_add_executor_job=executor, config=SimpleNamespace(config_dir=str(tmp_path)), data={},
                           is_running=True)
    hass.config_entries = HamisBejegyzesek(entry)
    figyelo = email_ha.EmailFigyelo(hass, entry, koord)
    koord.email = figyelo
    entry.runtime_data = koord
    return SimpleNamespace(hass=hass, entry=entry, koord=koord, figyelo=figyelo, ertesitesek=ertesitesek, hatter=hatter)


def test_felderites_bekoti_kerdez_ajanl_es_valaszok(tmp_path, monkeypatch, hamis_beolvaso):
    o = _otthon(tmp_path, monkeypatch)
    monkeypatch.setattr(es, "kapcsolodik", lambda pf, gyar=None: _postafiok())
    # Egy 9-es mérőjű (ismeretlen) villanyszámla is van: kérdés.
    imap = _postafiok()
    imap.mappak[OSSZES][b"7"] = level("MVM <ugyfelszolgalat@mvmee.hu>", "Villanyszámla", "<v9@x>",
                                      mellekletek=[("Villany_9000000009.pdf", b"%PDF-hamis-9")])
    monkeypatch.setattr(es, "kapcsolodik", lambda pf, gyar=None: imap)
    bekotott = asyncio.run(o.figyelo.felderit("PF1"))
    assert bekotott is True
    fr = dict(o.hass.config_entries.frissitett)
    assert set(fr) == {"A1", "H", "GAZ"}  # a továbbított H-számla is (tartalom szerint)
    assert fr["A1"]["email_auto"] is True and fr["A1"]["email_postafiokok"] == ["PF1"]
    assert fr["A1"]["szamla_mappa"] == "Szamlak/Villany_A1" and fr["GAZ"]["szamla_mappa"] == "Szamlak/Gaz"  # a meglévő marad
    allapot = o.koord.tarolo.adat["postafiokok"]["PF1"]
    assert allapot["felzarkozas_kell"] is True and allapot["felderites"]["talalt"] == 5
    h = o.koord.tarolo.adat["email_felderites"]
    assert [k["id"] for k in h["kerdesek"]] == ["mvm_aram|99999999"] and [a["id"] for a in h["ajanlatok"]] == ["telekom|-"]
    assert any("Az MVM villanyszámlái mostantól e-mailből jönnek a „Villany A1” fiókhoz." == u["szoveg"] for u in h["uzenetek"])
    assert any("Az MVM gázszámlái mostantól e-mailből jönnek a „Gáz” fiókhoz." in x for x in o.ertesitesek)
    panel_adat = o.figyelo.panel_adat()
    assert panel_adat["kerdesek"][0]["jeloltek"] == [{"sid": "A1", "nev": "Villany A1"}, {"sid": "H", "nev": "H tarifa"}] or \
        panel_adat["kerdesek"][0]["jeloltek"][0]["sid"] == "A1"
    assert {b["mod"] for b in panel_adat["postafiokok"][0]["bekotott"]} == {"auto"}

    # Kérdés: „Egyik sem” → megjegyzi; az újrakeresés nem kérdezi újra.
    asyncio.run(o.figyelo.valasz("kerdes", "mvm_aram|99999999", "egyik_sem"))
    assert h["mellozott"] == ["mvm_aram|99999999"] and h["kerdesek"] == []
    # Ajánlat: Telekom-fiók létrehozása (mérő nélküli: közvetlenül, az e-mailes számlákkal).
    r = asyncio.run(o.figyelo.valasz("ajanlat", "telekom|-", "letrehoz"))
    uj = o.hass.config_entries.hozzaadott[-1]
    assert r["letrehozva"] == uj.subentry_id and uj.subentry_type == "fiok" and uj.title == "Magyar Telekom"
    assert dict(uj.data) | {} == {"kozmu": "tavkozles", "szolgaltato": "telekom", "dijszabas": "tavkozles/elofizetes",
                                   "dijszabas_tol": "2000-01-01", "szamlazas_honap": "1", "szamla_mappa": "Szamlak/Magyar_Telekom",
                                   "email_postafiokok": ["PF1"], "email_auto": True}
    o.hass.config_entries.frissitett.clear()
    imap.mappak[OSSZES].pop(b"4")  # a Telekom-értesítő nélkül
    assert asyncio.run(o.figyelo.felderit("PF1")) is False  # minden be van kötve, a mellőzött nem jön elő
    assert o.koord.tarolo.adat["email_felderites"]["kerdesek"] == [] and o.hass.config_entries.frissitett == []


def test_kerdes_valasz_bekoti_a_valasztott_fiokot(tmp_path, monkeypatch):
    o = _otthon(tmp_path, monkeypatch)
    o.koord.tarolo.adat["email_felderites"] = {"kerdesek": [{"id": "mvm_aram|5", "pf": "PF1", "jeloltek": [{"sid": "A1"}, {"sid": "H"}]}]}
    with pytest.raises(ValueError):
        asyncio.run(o.figyelo.valasz("kerdes", "mvm_aram|5", "GAZ"))  # nem jelölt
    o.koord.tarolo.adat["email_felderites"]["kerdesek"] = [{"id": "mvm_aram|5", "pf": "PF1", "jeloltek": [{"sid": "A1"}, {"sid": "H"}]}]
    assert asyncio.run(o.figyelo.valasz("kerdes", "mvm_aram|5", "H")) == {"bekotott": "H"}
    assert o.hass.config_entries.frissitett[-1][0] == "H" and o.hass.config_entries.frissitett[-1][1]["email_auto"] is True
    assert o.koord.tarolo.adat["postafiokok"]["PF1"]["felzarkozas_kell"] is True
    with pytest.raises(ValueError):
        asyncio.run(o.figyelo.valasz("kerdes", "mvm_aram|5", "H"))  # már nem aktuális


def test_meros_ajanlat_elotolti_a_fiok_varazslot(tmp_path, monkeypatch):
    o = _otthon(tmp_path, monkeypatch)
    o.koord.tarolo.adat["email_felderites"] = {"ajanlatok": [{"id": "mvm_gaz|G", "pf": "PF1", "kozmu": "gaz", "nev": "MVM gázszámla",
                                                               "szolgaltatok": ["mvm_next"]}]}
    r = asyncio.run(o.figyelo.valasz("ajanlat", "mvm_gaz|G", "letrehoz"))
    assert r == {"navigal": "/config/integrations/integration/hu_rezsi"}
    assert o.hass.data["hu_rezsi"]["elotoltes"]["E1"]["kozmu"] == "gaz"
    assert asyncio.run(o.figyelo.valasz("ajanlat", "mvm_gaz|G", "nem_kell")) == {}
    assert o.koord.tarolo.adat["email_felderites"]["mellozott"] == ["mvm_gaz|G"]


def test_kezi_postafiok_marad_kezi_es_atallithato(tmp_path, monkeypatch, hamis_beolvaso):
    """Frissítés 2.2.0b1-ről: a kézi szűrős fiókokat a felderítés nem írja át; a panel gombja (auto) átállítja."""
    kezi = [_sub(sid, "fiok", nev, {**d, "email_postafiokok": ["PF1"], "email_feladok": "mvmee.hu", "szamla_mappa": f"Szamlak/{sid}"})
            for sid, nev, d in (("A1", "Villany A1", {"kozmu": "villany", "szolgaltato": "mvm_demasz", "dijszabas": "villany/a1", "gyari_szam": "11111111"}),
                                ("GAZ", "Gáz", {"kozmu": "gaz", "szolgaltato": "mvm_next"}))]
    o = _otthon(tmp_path, monkeypatch, kezi)
    o.koord.tarolo.adat["postafiokok"] = {"PF1": {"utolso_atnezes": "2026-10-31T10:00:00"}}
    o.figyelo.takaritas()
    assert not o.figyelo._teendo_van()  # meglévő postafióknál nincs magától felderítés
    assert [b["mod"] for b in o.figyelo.panel_adat()["postafiokok"][0]["bekotott"]] == ["kezi", "kezi"]
    monkeypatch.setattr(es, "kapcsolodik", lambda pf, gyar=None: _postafiok())
    assert asyncio.run(o.figyelo.felderit("PF1")) is False and o.hass.config_entries.frissitett == []
    assert {x["sid"] for x in o.koord.tarolo.adat["postafiokok"]["PF1"]["felderites"]["mar_bekotve"]} == {"A1", "GAZ"}
    r = asyncio.run(o.figyelo.valasz("auto", "PF1", ""))
    assert r == {"valtott": 2} and all(d["email_auto"] and d["email_feladok"] == "mvmee.hu" for _, d in o.hass.config_entries.frissitett)


def test_uj_postafiok_felderitest_kap(tmp_path, monkeypatch):
    o = _otthon(tmp_path, monkeypatch)
    o.figyelo.indit = email_ha.EmailFigyelo.indit.__get__(o.figyelo)
    for sid in email_ha.postafiokok(o.entry):
        if sid not in o.figyelo._allapotok():
            o.figyelo.allapot(sid)["felderites_kell"] = True
    assert o.figyelo._teendo_van()


def test_postafiok_letrehozas_a_panelrol(tmp_path, monkeypatch):
    o = _otthon(tmp_path, monkeypatch)

    def rossz(pf):
        raise es.HitelesitesiHiba("x")

    monkeypatch.setattr(es, "bejelentkezes_proba", rossz)
    r = asyncio.run(email_ha.postafiok_letrehoz(o.hass, o.entry, {"email_cim": "masik@gmail.com", "jelszo": "rossz"}))
    assert r["hiba"] == "hitelesites_gmail" and "alkalmazásjelszó" in r["szoveg"] and r["link"].startswith("https://myaccount.google.com")
    assert o.hass.config_entries.hozzaadott == []
    r = asyncio.run(email_ha.postafiok_letrehoz(o.hass, o.entry, {"email_cim": "Valaki@gmail.com", "jelszo": "x"}))
    assert r["hiba"] == "mar_van"
    probalt = []
    monkeypatch.setattr(es, "bejelentkezes_proba", lambda pf: probalt.append(pf))
    r = asyncio.run(email_ha.postafiok_letrehoz(o.hass, o.entry, {"email_cim": "kovacs.anna@freemail.hu", "jelszo": "titkos jelszo"}))
    uj = o.hass.config_entries.hozzaadott[-1]
    assert r == {"sid": uj.subentry_id, "nev": "kovacs.anna"} and uj.subentry_type == "postafiok" and uj.title == "kovacs.anna"
    assert uj.data["imap_szerver"] == "imap.freemail.hu" and uj.data["jelszo"] == "titkos jelszo" and probalt[0].szerver == "imap.freemail.hu"
    assert o.koord.tarolo.adat["postafiokok"][uj.subentry_id] == {"felderites_kell": True}


# --------------------------------------------------------------------------------------------- websocket


class Kapcsolat:
    def __init__(self, admin):
        self.user = SimpleNamespace(is_admin=admin)
        self.eredmeny, self.hiba = None, None

    def send_result(self, mid, ered=None):
        self.eredmeny = ered

    def send_error(self, mid, kod, uzenet):
        self.hiba = (kod, uzenet)


def _ws(handler, hass, msg, admin=True):
    from homeassistant.exceptions import Unauthorized

    feladatok = []
    hass.async_create_background_task = lambda coro, nev, eager_start=True: feladatok.append(coro)
    k = Kapcsolat(admin)
    try:
        handler(hass, k, {"id": 1, **msg})
    except Unauthorized:
        return "nincs_jog"
    for f in feladatok:
        asyncio.run(f)
    return k


def test_websocket_rendszergazda_ellenorzes(tmp_path, monkeypatch):
    o = _otthon(tmp_path, monkeypatch)
    for handler, msg in ((panel.ws_postafiok_hozzaad, {"type": "hu_rezsi/postafiok_hozzaad", "entry_id": "E1", "email_cim": "a@gmail.com", "jelszo": "x"}),
                         (panel.ws_email_felderites, {"type": "hu_rezsi/email_felderites", "entry_id": "E1"}),
                         (panel.ws_email_valasz, {"type": "hu_rezsi/email_valasz", "entry_id": "E1", "tipus": "uzenet"}),
                         (panel.ws_postafiok_felismeres, {"type": "hu_rezsi/postafiok_felismeres", "email": "a@gmail.com"})):
        assert _ws(handler, o.hass, msg, admin=False) == "nincs_jog", handler.__name__
    k = _ws(panel.ws_postafiok_felismeres, o.hass, {"email": "a@freemail.hu"})
    assert k.eredmeny["szerver"] == "imap.freemail.hu" and k.eredmeny["cim_jo"] is True
    monkeypatch.setattr(es, "bejelentkezes_proba", lambda pf: None)
    k = _ws(panel.ws_postafiok_hozzaad, o.hass, {"entry_id": "E1", "email_cim": "uj@gmail.com", "jelszo": "abcd efgh"})
    assert k.eredmeny["nev"] == "uj" and o.hass.config_entries.hozzaadott[-1].data["jelszo"] == "abcdefgh"
    k = _ws(panel.ws_postafiok_hozzaad, o.hass, {"entry_id": "NINCS", "email_cim": "uj@gmail.com", "jelszo": "x"})
    assert k.hiba[0] == "nincs_otthon"
    o.koord.tarolo.adat["email_felderites"] = {"uzenetek": [{"ido": "2026-11-01", "szoveg": "x"}]}
    k = _ws(panel.ws_email_valasz, o.hass, {"entry_id": "E1", "tipus": "uzenet", "azon": "", "ertek": ""})
    assert k.eredmeny == {} and o.koord.tarolo.adat["email_felderites"]["uzenetek"] == []
    k = _ws(panel.ws_email_valasz, o.hass, {"entry_id": "E1", "tipus": "kerdes", "azon": "nincs", "ertek": "A1"})
    assert k.hiba[0] == "hiba"



def test_felderites_kezdete_a_panelen_futas_kozben(tmp_path, monkeypatch, hamis_beolvaso):
    """A panel „… perce fut” sora: futás közben ott a kezdet, a végén eltűnik (hibánál is)."""
    o = _otthon(tmp_path, monkeypatch)
    latott = []

    def kapcsolodik(pf, gyar=None):
        latott.append(o.figyelo.panel_adat()["postafiokok"][0]["felderites_kezdet"])
        return _postafiok()

    monkeypatch.setattr(es, "kapcsolodik", kapcsolodik)
    k = _ws(panel.ws_email_felderites, o.hass, {"entry_id": "E1", "sid": "PF1"})
    assert k.eredmeny == {"indult": ["PF1"]}
    for f in o.hatter:
        asyncio.run(f)
    assert latott and latott[0]
    pf = o.figyelo.panel_adat()["postafiokok"][0]
    assert pf["felderites_kezdet"] is None and pf["felderites_fut"] is False and pf["felderites"]
    monkeypatch.setattr(es, "kapcsolodik", lambda pf, gyar=None: (_ for _ in ()).throw(es.EmailHiba("x")))
    asyncio.run(o.figyelo.felderit("PF1"))
    assert o.figyelo.felderites_kezdet == {}


def test_websocket_parancs_nem_hasznal_id_mezot():
    """Az „id” a WebSocket-üzenet saját (egész) sorszáma: parancs-mezőként a HA felülírja („expected str at 'id'”)."""
    import inspect

    import voluptuous as vol

    parancsok = [f for _, f in inspect.getmembers(panel) if callable(f) and isinstance(getattr(f, "_ws_schema", None), vol.Schema)]
    assert parancsok
    for f in parancsok:  # a HA minden parancs sémájába beteszi a saját (egész) „id”-ját – azt senki ne írja felül
        ertek = [v for k, v in f._ws_schema.schema.items() if str(k.schema if isinstance(k, vol.Marker) else k) == "id"]
        assert ertek and ertek[0] is not str, f.__name__
    # a HA által ténylegesen küldött alak (egész sorszám) átmegy a sémán
    panel.ws_email_valasz._ws_schema({"id": 195, "type": "hu_rezsi/email_valasz", "entry_id": "E1", "tipus": "auto", "azon": "", "ertek": ""})


# --------------------------------------------------------------------------------------------- beállító felület


def test_postafiok_urlap_ket_mezo_es_osszecsukott_halado(monkeypatch):
    from custom_components.hu_rezsi import config_flow as cf
    from tests.test_email_szamlak import _flow_hass

    f = cf.PostafiokFlow()
    f.hass, f.handler, f.context, f.flow_id = _flow_hass(), ("E1", "postafiok"), {"source": "user"}, "1"
    r = asyncio.run(f.async_step_user())
    kulcsok = [str(k) for k in r["data_schema"].schema]
    assert kulcsok == ["email_cim", "jelszo", "halado"]
    halado = r["data_schema"].schema[next(k for k in r["data_schema"].schema if str(k) == "halado")]
    assert halado.options["collapsed"] is True
    assert [str(k) for k in halado.schema.schema] == ["nev", "imap_szerver", "imap_port", "imap_ssl", "email_napok", "email_kuka"]
    assert "myaccount.google.com/apppasswords" in r["description_placeholders"]["lepesek"]

    def nincs(pf):
        raise es.KapcsolatiHiba("x")

    monkeypatch.setattr(es, "bejelentkezes_proba", nincs)
    r = asyncio.run(f.async_step_user({"email_cim": "a@sajat-domain.hu", "jelszo": "x", "halado": {}}))
    assert r["errors"] == {"base": "szerver_ismeretlen"}
    halado = r["data_schema"].schema[next(k for k in r["data_schema"].schema if str(k) == "halado")]
    assert halado.options["collapsed"] is False  # ismeretlen szerver: a Haladó kinyitva
    szerver = next(k for k in halado.schema.schema if str(k) == "imap_szerver")
    assert szerver.description == {"suggested_value": "imap.sajat-domain.hu"}
    probalt = []
    monkeypatch.setattr(es, "bejelentkezes_proba", lambda pf: probalt.append(pf))
    r = asyncio.run(f.async_step_user({"email_cim": "kiss.bela@gmail.com", "jelszo": "abcd efgh ijkl mnop", "halado": {}}))
    assert r["type"] == "create_entry" and r["title"] == "kiss.bela"
    assert r["data"]["imap_szerver"] == "imap.gmail.com" and r["data"]["jelszo"] == "abcdefghijklmnop"
