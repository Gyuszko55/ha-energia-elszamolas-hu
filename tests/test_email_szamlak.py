"""Számlák e-mailből (email_szamlak, email_ha): mappák felderítése, keresés, levél → fiók besorolás (feladó, tárgy,
mérő gyári száma, felhasználási hely irányítószáma), melléklet-mentés és ismétlődés-szűrés, továbbított MVM-melléklet
neve, melléklet nélküli számlaértesítő, hibák elszigetelése. Hálózat nélkül, hamis IMAP-klienssel és kitalált
adatokkal (a címek, sorszámok, irányítószámok nem valódiak)."""

import asyncio
import imaplib
from datetime import date
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
import email_szamlak as es

MA = date(2026, 11, 1)


# --------------------------------------------------------------------------------------------- segédek


def pdf(sorok: list[str]) -> bytes:
    """Minimális, szöveget tartalmazó PDF (Helvetica, ASCII) – a pypdf ki tudja olvasni."""
    tartalom = "BT /F1 10 Tf 50 800 Td 12 TL " + " ".join(
        "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for s in sorok) + " ET"
    objektumok = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(tartalom)} >>\nstream\n{tartalom}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    ki, helyek = b"%PDF-1.4\n", []
    for i, o in enumerate(objektumok, 1):
        helyek.append(len(ki))
        ki += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(ki)
    ki += f"xref\n0 {len(objektumok) + 1}\n0000000000 65535 f \n".encode()
    ki += "".join(f"{h:010d} 00000 n \n" for h in helyek).encode()
    ki += f"trailer\n<< /Size {len(objektumok) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return ki


def level(felado: str, targy: str, mid: str, szoveg: str = "Tisztelt Ügyfelünk!", html: str | None = None,
          mellekletek: list[tuple[str, bytes]] = (), datum: str = "Fri, 30 Oct 2026 10:00:00 +0100") -> bytes:
    m = EmailMessage()
    m["From"] = felado
    m["To"] = "valaki@example.com"
    m["Subject"] = targy
    m["Message-ID"] = mid
    m["Date"] = datum
    m.set_content(szoveg)
    if html:
        m.add_alternative(html, subtype="html")
    for nev, adat in mellekletek:
        m.add_attachment(adat, maintype="application", subtype="pdf" if nev.lower().endswith(".pdf") else "xml", filename=nev)
    return m.as_bytes()


class HamisImap:
    """IMAP-kliens helyett: mappák listája, mappánként levelek (uid → nyers bájt). Naplózza a hívásokat, hogy
    ellenőrizhető legyen: csak olvas (EXAMINE / readonly, BODY.PEEK), nem töröl, nem jelöl."""

    def __init__(self, mappak: dict[str, dict[bytes, bytes]], list_valasz: list, jelszo: str = "titok",
                 gmail: bool = True) -> None:
        self.mappak = mappak
        self.list_valasz = list_valasz
        self.jelszo = jelszo
        self.capabilities = ("IMAP4REV1", "X-GM-EXT-1") if gmail else ("IMAP4REV1",)
        self.hivasok: list[tuple] = []
        self.kivalasztott: str | None = None
        self.kilepett = False

    def login(self, felh, jelszo):
        self.hivasok.append(("login", felh))
        if jelszo != self.jelszo:
            raise imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials (Failure)")
        return "OK", [b"ok"]

    def list(self):
        return "OK", self.list_valasz

    def select(self, mappa, readonly=False):
        self.hivasok.append(("select", mappa, readonly))
        nev = es._idezet_nelkul(mappa)
        if nev not in self.mappak:
            return "NO", [b"nincs"]
        self.kivalasztott = nev
        return "OK", [str(len(self.mappak[nev])).encode()]

    def uid(self, parancs, *args):
        self.hivasok.append(("uid", parancs, *args))
        levelek = self.mappak[self.kivalasztott]
        if parancs == "SEARCH":
            feltetel = " ".join(args).lower()
            talalt = [u for u, nyers in levelek.items()
                      if any(f in self._felado(nyers) for f in _feladok_a_feltetelbol(feltetel))]
            return "OK", [b" ".join(talalt)]
        if parancs == "FETCH":
            uid, mit = args
            assert "PEEK" in mit, "csak BODY.PEEK (a levél ne legyen olvasott)"
            nyers = levelek[uid]
            if "HEADER.FIELDS" in mit:
                nyers = nyers.split(b"\n\n", 1)[0] + b"\n\n"
            return "OK", [(b"1 (UID " + uid + b" BODY[] {%d}" % len(nyers), nyers), b")"]
        raise AssertionError(f"tiltott IMAP-parancs: {parancs}")

    def logout(self):
        self.kilepett = True
        return "BYE", [b""]

    @staticmethod
    def _felado(nyers: bytes) -> str:
        for sor in nyers.split(b"\n"):
            if sor.lower().startswith(b"from:"):
                return sor.decode().lower()
        return ""


def _feladok_a_feltetelbol(feltetel: str) -> list[str]:
    import re

    if "from:(" in feltetel:
        return [x.strip() for x in re.search(r"from:\(([^)]*)\)", feltetel).group(1).split(" or ")]
    return re.findall(r'from "([^"]+)"', feltetel)


GMAIL_LIST = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
    b'(\\All \\HasNoChildren) "/" "[Gmail]/&ANY-sszes lev&AOk-l"',
    b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Kuka"',
    b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Elk&APw-ld&APY-tt"',
]
OSSZES = "[Gmail]/&ANY-sszes lev&AOk-l"


def _pf(**kw):
    return es.Postafiok(sid="PF1", nev="Saját", felhasznalo="valaki@example.com", jelszo="titok", **kw)


def _szuro(sid, mappa, feladok="mvmee.hu", **kw):
    return es.FiokSzuro(sid=sid, nev=sid, mappa=mappa, feladok=es.lista(feladok), **kw)


# --------------------------------------------------------------------------------------------- mappák, keresés


def test_mappak_gmail_osszes_es_kuka_nyelvfuggetlenul():
    assert es.keresendo_mappak(GMAIL_LIST, kuka=True) == [OSSZES, "[Gmail]/Kuka"]
    assert es.keresendo_mappak(GMAIL_LIST, kuka=False) == [OSSZES]


def test_mappak_literalis_nev_es_nem_gmail():
    lit = [(b'(\\HasNoChildren \\Trash) "/" {11}', b"Deleted Box"), b'(\\HasNoChildren) "." INBOX']
    assert es.keresendo_mappak(lit, kuka=True) == ["INBOX", "Deleted Box"]
    assert es.keresendo_mappak([], kuka=True) == ["INBOX"]


def test_kereses_gmail_es_szabvanyos():
    assert es.kereses(["mvmee.hu", "telekom.hu"], 45, MA, True) == ("X-GM-RAW", '"from:(mvmee.hu OR telekom.hu) newer_than:45d"')
    k = es.kereses(["b.hu", "a.hu", "c@d.hu"], 10, MA, False)
    assert k == ("SINCE", "22-Oct-2026", 'OR FROM "a.hu" (OR FROM "b.hu" (FROM "c@d.hu"))')
    assert es.kereses(["a.hu"], 1, date(2026, 1, 2), False)[1] == "01-Jan-2026"


# --------------------------------------------------------------------------------------------- illesztés


def test_felado_cim_es_domain():
    assert es.felado_illeszkedik("onlineugyfelszolgalat@mvmee.hu", "mvmee.hu")
    assert es.felado_illeszkedik("szamla@hirlevel.mvmee.hu", "mvmee.hu")  # aldomain
    assert not es.felado_illeszkedik("valaki@nemmvmee.hu", "mvmee.hu")
    assert es.felado_illeszkedik("Partner@Example.com", "partner@example.com")
    assert not es.felado_illeszkedik("masik@example.com", "partner@example.com")
    assert es.lista("mvmee.hu; @telekom.hu,\n partner@example.com") == ["mvmee.hu", "telekom.hu", "partner@example.com"]
    assert es.felado_cimek('"MVM Next" <OnlineUgyfelszolgalat@mvmee.hu>') == ["onlineugyfelszolgalat@mvmee.hu"]


def test_szuro_targy_szerint():
    s = _szuro("A", None, targy="Villanyszámla")
    assert s.illeszkedik(["x@mvmee.hu"], "Fwd: VILLANYSZÁMLA elkészült")  # kis- és nagybetű mindegy
    assert not s.illeszkedik(["x@mvmee.hu"], "Gázszámla")
    assert not _szuro("B", None, feladok="").illeszkedik(["x@mvmee.hu"], "bármi")  # feladó nélkül nem aktív


def test_irsz_felhasznalasi_hely_elsobb_a_levelezesi_cimnel():
    szoveg = "Levelezesi cim: 9999 Mintavaros, Fo u. 1.\nFelhasznalasi hely cime: 1111 Peldafalu, Kert u. 2."
    assert es.irsz_illeszkedik(szoveg, "1111")
    assert not es.irsz_illeszkedik(szoveg, "9999")
    # Felirat nélkül: sor elején vagy településnév előtt álló irányítószám
    assert es.irsz_illeszkedik("Mintavaros\n2222 Peldafalu, Fo u. 3.", "2222")
    assert not es.irsz_illeszkedik("Ugyfelazonosito: 1222233334", "2222")


def test_fiok_valasztas_mero_irsz_es_egyertelmuseg(tmp_path):
    a = _szuro("A", tmp_path / "a", irszok=["1111"])
    b = _szuro("B", tmp_path / "b", irszok=["2222"])
    c = _szuro("C", tmp_path / "c", merok=["123456789"])
    assert es.fiok_valasztas([a, b], "Felhasznalasi hely cime: 2222 X") == [b]
    assert es.fiok_valasztas([a, b, c], "Gyari szam: 00 1234 56789") == [c]  # szóköz, vezető nulla nem számít
    nincs = _szuro("N", tmp_path / "n")
    assert es.fiok_valasztas([a, nincs], "semmi") == [nincs]  # a megkülönböztető nélküli marad
    assert es.fiok_valasztas([a, b], "semmi") == []  # egyiké sem: nem besorolható
    d1, d2 = _szuro("D1", tmp_path / "x"), _szuro("D2", tmp_path / "y")
    assert es.fiok_valasztas([d1, d2], "") == []  # két fiók, két mappa: nem egyértelmű
    k1, k2 = _szuro("K1", tmp_path / "kozos"), _szuro("K2", tmp_path / "kozos")
    assert es.fiok_valasztas([k1, k2], "") == [k1, k2]  # közös mappa: a mappa-feldolgozás választ


# --------------------------------------------------------------------------------------------- levél-elemek


def test_tovabbitott_mvm_melleklet_neve():
    assert es.mentendo_nev("123456789012.PDF", "Fwd: Villanyszámla") == "Villany_123456789012.pdf"
    assert es.mentendo_nev("Villany_123456789012_20261030.PDF", "Villanyszámla") == "Villany_123456789012_20261030.pdf"
    assert es.mentendo_nev("123456789012.PDF", "Gázszámla") == "123456789012.pdf"
    assert es.mentendo_nev("../../etc/x y.pdf", "") == "x_y.pdf"
    assert es.fajlnev_sorszam("Villany_123456789012.pdf") == "123456789012"


ERTESITO_HTML = """<html><body><table>
<tr><td>Számla sorszáma:</td><td>987654321000</td></tr>
<tr><td>Számla kelte:</td><td>2026.10.05</td></tr>
<tr><td>Elszámolási időszak</td><td>2026.09.01. - 2026.09.30</td></tr>
<tr><td>Számlázott összeg:</td><td>12&nbsp;345 Ft</td></tr>
<tr><td>Beérkezési határidő:</td><td>2026.10.20</td></tr>
</table></body></html>"""


def test_ertesito_szamla_a_level_szovegebol():
    m = EmailMessage()
    m.set_content("HTML levél")
    m.add_alternative(ERTESITO_HTML, subtype="html")
    adat = es.ertesito_szamla(es.torzs_szoveg(m))
    assert adat == {"sorszam": "987654321000", "osszeg": 12345, "kelte": "2026-10-05", "idoszak_tol": "2026-09-01",
                    "idoszak_ig": "2026-09-30", "hatarido": "2026-10-20"}
    assert es.ertesito_szamla("Hírlevél: új készülékek, 9990 Ft") is None


# --------------------------------------------------------------------------------------------- teljes átnézés


def _postafiok_levelekkel():
    a_pdf = pdf(["MVM Next Energiakereskedelmi Zrt.", "Felhasznalasi hely cime: 1111 Peldafalu, Kert u. 2.",
                 "Szamla sorszama: 111122223333"])
    b_pdf = pdf(["MVM Next Energiakereskedelmi Zrt.", "Felhasznalasi hely cime: 2222 Mintavaros, Fo u. 1.",
                 "Szamla sorszama: 444455556666"])
    regi_pdf = pdf(["Felhasznalasi hely cime: 1111 Peldafalu", "Szamla sorszama: 777788889999"])
    l_a = level("MVM Next <onlineugyfelszolgalat@mvmee.hu>", "Elkészült villanyszámlája", "<a@mvm>",
                mellekletek=[("Villany_111122223333_20261030.PDF", a_pdf)])
    l_b = level("Partner <partner@example.com>", "Fwd: Villanyszámla", "<b@fwd>",
                mellekletek=[("444455556666.PDF", b_pdf)])
    l_regi = level("onlineugyfelszolgalat@mvmee.hu", "Villanyszámla", "<regi@mvm>",
                   mellekletek=[("Villany_777788889999.pdf", regi_pdf)])
    l_tk = level("Telekom <ertesito@telekom.hu>", "Számlaértesítő", "<tk@telekom>", html=ERTESITO_HTML)
    l_mas = level("bolt@pelda.hu", "Akció", "<x@bolt>", mellekletek=[("szamla_1234567890.pdf", pdf(["x"]))])
    l_reklam = level("hirlevel@telekom.hu", "Új készülékek", "<r@telekom>", szoveg="Ajánlatunk: 9990 Ft")
    osszes = {b"1": l_a, b"2": l_b, b"3": l_regi, b"4": l_tk, b"5": l_mas, b"6": l_reklam}
    kuka = {b"9": l_a}  # ugyanaz a levél a Kukában is (Gmail: címke)
    return {OSSZES: osszes, "[Gmail]/Kuka": kuka}


def test_atnezes_mentes_besorolas_ismetlodes_es_csak_olvasas(tmp_path):
    imap = HamisImap(_postafiok_levelekkel(), GMAIL_LIST)
    a = _szuro("A", tmp_path / "Szamlak" / "A", irszok=["1111"])
    b = _szuro("B", tmp_path / "Szamlak" / "B", feladok="mvmee.hu, partner@example.com", irszok=["2222"])
    tk = _szuro("TK", tmp_path / "Szamlak" / "TK", feladok="telekom.hu")
    ismert = {"777788889999"}  # ez már rögzítve van
    er = es.atnez(_pf(), [a, b, tk], ismert, {}, MA, gyar=lambda pf: imap)

    assert sorted((x["fiok"], x["fajl"]) for x in er.mentett) == [
        ("A", "Villany_111122223333_20261030.pdf"), ("B", "Villany_444455556666.pdf")]
    assert (tmp_path / "Szamlak" / "A" / "Villany_111122223333_20261030.pdf").read_bytes().startswith(b"%PDF")
    assert (tmp_path / "Szamlak" / "B" / "Villany_444455556666.pdf").exists()
    assert not (tmp_path / "Szamlak" / "TK").exists()  # melléklet nélküli értesítő: nem fájl
    assert [x["adat"]["sorszam"] for x in er.ertesitok] == ["987654321000"]
    assert er.ertesitok[0]["fiok"] == "TK"
    assert er.kihagyva == 1  # a már ismert számla
    assert {"111122223333", "444455556666", "987654321000"} <= ismert
    # Csak olvas: minden mappa readonly, nincs STORE/COPY/EXPUNGE (a hamis kliens ezt kivétellel jelezné), kilépett.
    assert all(h[2] is True for h in imap.hivasok if h[0] == "select")
    assert imap.kilepett
    # A szűrőnek nem megfelelő feladó levele le sem töltődik.
    letoltott = [h[2] for h in imap.hivasok if h[0] == "uid" and h[1] == "FETCH" and "BODY.PEEK[]" in h[3]]
    assert b"5" not in letoltott
    # Ugyanaz a levél a Kukában: egyszer.
    assert len(er.mentett) == 2

    # Második átnézés a „látott” nyilvántartással: semmi új, és a kitörölt fájl sem jön vissza.
    (tmp_path / "Szamlak" / "A" / "Villany_111122223333_20261030.pdf").unlink()
    imap2 = HamisImap(_postafiok_levelekkel(), GMAIL_LIST)
    er2 = es.atnez(_pf(), [a, b, tk], set(), er.latott, MA, gyar=lambda pf: imap2)
    assert er2.mentett == [] and er2.ertesitok == []
    assert not (tmp_path / "Szamlak" / "A" / "Villany_111122223333_20261030.pdf").exists()


def test_ismert_sorszam_a_mappa_fajlneveben(tmp_path):
    mappa = tmp_path / "A"
    mappa.mkdir()
    (mappa / "Villany_111122223333.pdf").write_bytes(b"korabbi")
    imap = HamisImap(_postafiok_levelekkel(), GMAIL_LIST)
    a = _szuro("A", mappa, irszok=["1111"])
    er = es.atnez(_pf(kuka=False), [a], set(), {}, MA, gyar=lambda pf: imap)
    # A mappában már ott a 111122223333 (más néven is): kimarad; a 777788889999 (tárban sincs) bekerül.
    assert [m["sorszam"] for m in er.mentett] == ["777788889999"] and er.kihagyva == 1
    assert sorted(f.name for f in mappa.iterdir()) == ["Villany_111122223333.pdf", "Villany_777788889999.pdf"]


def test_nem_besorolhato_level_nem_vegleges(tmp_path):
    imap = HamisImap(_postafiok_levelekkel(), GMAIL_LIST)
    x = _szuro("X", tmp_path / "x", irszok=["3333"])  # egyik levélben sincs ilyen irányítószám
    er = es.atnez(_pf(kuka=False), [x], set(), {}, MA, gyar=lambda pf: imap)
    assert er.mentett == [] and len(er.nem_besorolhato) >= 1
    assert not (tmp_path / "x").exists()
    # A nem besorolható levél nem kerül a „látott” közé: a beállítás javítása után újra próbálható.
    x.irszok = ["1111"]
    er2 = es.atnez(_pf(kuka=False), [x], {"777788889999"}, er.latott, MA, gyar=lambda pf: HamisImap(_postafiok_levelekkel(), GMAIL_LIST))
    assert [m["sorszam"] for m in er2.mentett] == ["111122223333"]


def test_szabvanyos_imap_inbox(tmp_path):
    mappak = _postafiok_levelekkel()
    imap = HamisImap({"INBOX": mappak[OSSZES]}, [b'(\\HasNoChildren) "/" "INBOX"'], gmail=False)
    a = _szuro("A", tmp_path / "a", irszok=["1111"])
    er = es.atnez(_pf(), [a], {"777788889999"}, {}, MA, gyar=lambda pf: imap)
    assert [m["sorszam"] for m in er.mentett] == ["111122223333"]
    keres = next(h for h in imap.hivasok if h[0] == "uid" and h[1] == "SEARCH")
    assert keres[2] == "SINCE"


def test_latott_regi_bejegyzesek_kimaradnak(tmp_path):
    imap = HamisImap({OSSZES: {}}, GMAIL_LIST)
    er = es.atnez(_pf(napok=10), [_szuro("A", tmp_path)], set(), {"regi": "2026-01-01", "friss": "2026-10-30"}, MA,
                  gyar=lambda pf: imap)
    assert er.latott == {"friss": "2026-10-30"}


# --------------------------------------------------------------------------------------------- hibák


def test_hibas_jelszo_kapcsolat_es_hianyzo_jelszo():
    imap = HamisImap({OSSZES: {}}, GMAIL_LIST, jelszo="masik")
    with pytest.raises(es.HitelesitesiHiba) as e:
        es.bejelentkezes_proba(_pf(), gyar=lambda pf: imap)
    assert "alkalmazásjelszó" in str(e.value) and imap.kilepett

    def nem_elerheto(pf):
        raise OSError("Connection refused")

    with pytest.raises(es.KapcsolatiHiba):
        es.bejelentkezes_proba(_pf(), gyar=nem_elerheto)
    with pytest.raises(es.JelszoHianyzik):
        es.bejelentkezes_proba(es.Postafiok("PF", "x", "valaki@example.com", ""))


def test_gmail_alkalmazasjelszo_szokozok_nelkul():
    pf = es.Postafiok.adatbol("PF", "Saját", {"email_cim": "a@example.com", "jelszo": "abcd efgh ijkl mnop"})
    assert pf.jelszo == "abcdefghijklmnop" and pf.szerver == "imap.gmail.com" and pf.port == 993 and pf.napok == 45
    masik = es.Postafiok.adatbol("PF", "x", {"email_cim": "a", "jelszo": "a b", "imap_szerver": "mail.example.com"})
    assert masik.jelszo == "a b"


def test_szamlamappa_csak_a_konfiguracios_mappan_belul(tmp_path):
    assert es.szamla_mappa_ut(tmp_path, "Szamlak/A") == (tmp_path / "Szamlak" / "A").resolve()
    assert es.szamla_mappa_ut(tmp_path, "../kivul") is None
    assert es.szamla_mappa_ut(tmp_path, "") is None


def test_hibas_postafiok_nem_allitja_meg_a_tobbit(monkeypatch):
    """HA-oldal: az egyik postafiók bejelentkezési hibája csak a saját állapotát és javítandó problémáját érinti."""
    from custom_components.hu_rezsi import email_ha
    from custom_components.hu_rezsi import email_szamlak as pes

    issues = {}
    monkeypatch.setattr(email_ha.ir, "async_create_issue", lambda hass, dom, iid, **kw: issues.__setitem__(iid, kw))
    monkeypatch.setattr(email_ha.ir, "async_delete_issue", lambda hass, dom, iid: issues.pop(iid, None))

    def atnez(pf, szurok, ismert, latott, ma, gyar=None):
        if pf.sid == "ROSSZ":
            raise pes.HitelesitesiHiba("hibás jelszó")
        return pes.Eredmeny(mentett=[{"fiok": "F1", "fiok_nev": "Villany", "fajl": "Villany_1.pdf", "sorszam": "1",
                                      "datum": "2026-10-30"}], latott={"k": "2026-11-01"})

    monkeypatch.setattr(pes, "atnez", atnez)

    async def executor(fn, *args):
        return fn(*args)

    pfk = {sid: SimpleNamespace(subentry_type="postafiok", title=sid, data={"email_cim": "a@example.com", "jelszo": "x"})
           for sid in ("ROSSZ", "JO")}
    fiok = SimpleNamespace(subentry_type="fiok", title="Villany",
                           data={"email_postafiokok": ["ROSSZ", "JO"], "email_feladok": "mvmee.hu", "szamla_mappa": "Szamlak/V"})
    hass = SimpleNamespace(async_add_executor_job=executor, config=SimpleNamespace(config_dir="/tmp/nincs"))
    mentve, frissitve = [], []

    async def ment():
        mentve.append(True)

    async def frissit():
        frissitve.append(True)

    tarolo = SimpleNamespace(adat={"fiokok": {"F1": {"szamlak": {"9": {}}}}}, ment=ment)
    koord = SimpleNamespace(fiokok=lambda: {"F1": fiok}, tarolo=tarolo, async_request_refresh=frissit, _zar=asyncio.Lock())
    entry = SimpleNamespace(subentries={**pfk, "F1": fiok}, title="Otthon", entry_id="E1")
    figyelo = email_ha.EmailFigyelo(hass, entry, koord)
    ki = asyncio.run(figyelo.atnez_mind())

    assert ki["ROSSZ"]["hiba_tipus"] == "hitelesites" and ki["JO"]["mentett"] == 1
    allapot = tarolo.adat["postafiokok"]
    assert allapot["ROSSZ"]["hiba"] == "hibás jelszó" and allapot["JO"]["hiba"] is None
    assert allapot["JO"]["utolso_talalt"] == 1 and allapot["JO"]["latott"] == {"k": "2026-11-01"}
    assert list(issues) == ["email_hiba_ROSSZ"]
    assert issues["email_hiba_ROSSZ"]["translation_placeholders"]["postafiok"] == "ROSSZ"
    assert mentve and frissitve  # mentés és a számlamappák feldolgozása
    panel = figyelo.panel_adat()
    assert {p["nev"]: p["fiokok"] for p in panel["postafiokok"]} == {"ROSSZ": 1, "JO": 1}

    # Ha a hibás postafiók is sikerül, a javítandó probléma eltűnik.
    monkeypatch.setattr(pes, "atnez", lambda *a, **k: pes.Eredmeny())
    asyncio.run(figyelo.atnez_mind())
    assert issues == {} and allapot["ROSSZ"]["hiba"] is None


def test_ismert_sorszamok_fuggo_es_elvetett():
    from custom_components.hu_rezsi.email_ha import ismert_sorszamok

    adat = {"fiokok": {"A": {"szamlak": {"1": {}}, "fuggo": [{"sorszam": "2"}]}, "B": {"elvetett_szamlak": [{"sorszam": "3"}]}}}
    assert ismert_sorszamok(adat) == {"1", "2", "3"}


# --------------------------------------------------------------------------------------------- adatok, mentés, diagnosztika


def test_szolgaltato_feladok_tablazat():
    from motor.dijszabas import DijszabasTar

    tar = DijszabasTar.mappabol(tests.conftest.DIJSZABASOK)
    for k in ("mvm_demasz", "eon", "opus_titasz", "elmu", "elmu_emasz", "mvm_next"):
        assert tar.szolgaltatok[k]["email_feladok"] == ["mvmee.hu"], k
    assert tar.szolgaltatok["telekom"]["email_feladok"] == ["telekom.hu"]
    assert "email_feladok" not in tar.szolgaltatok["dakov"]


def test_mentes_jelszo_nelkul_es_postafiok_atkulcsolas():
    from mentes import atkulcsol, email_hivatkozas_atkulcsol, jelszo_nelkuli_postafiokok, titkok_nelkul

    alar = [{"subentry_id": "P1", "subentry_type": "postafiok", "title": "Saját",
             "data": {"email_cim": "a@example.com", "jelszo": "titok", "imap_szerver": "imap.gmail.com"}},
            {"subentry_id": "F1", "subentry_type": "fiok", "title": "Villany", "data": {"email_postafiokok": ["P1", "TOROLT"]}}]
    ki = titkok_nelkul(alar)
    assert "jelszo" not in ki[0]["data"] and ki[0]["data"]["imap_szerver"] == "imap.gmail.com"
    assert alar[0]["data"]["jelszo"] == "titok"  # az eredeti érintetlen
    assert jelszo_nelkuli_postafiokok(ki) == ["Saját"]
    assert email_hivatkozas_atkulcsol(ki[1]["data"], {"P1": "UJ1"}) == {"email_postafiokok": ["UJ1"]}
    assert email_hivatkozas_atkulcsol({"kozmu": "villany"}, {"P1": "UJ1"}) is None
    tar = atkulcsol({"fiokok": {}, "postafiokok": {"P1": {"osszes_talalt": 3}, "TOROLT": {}}}, {"P1": "UJ1"})
    assert tar["postafiokok"] == {"UJ1": {"osszes_talalt": 3}}


def test_diagnosztika_kitakarja_a_jelszot_es_a_cimet():
    from custom_components.hu_rezsi import diagnostics as DG

    pf = SimpleNamespace(subentry_type="postafiok", title="Saját",
                         data={"email_cim": "titkos@example.com", "jelszo": "abcdefgh", "imap_szerver": "imap.gmail.com"})
    koord = SimpleNamespace(fiokok=lambda: {}, data={}, utolso_szamlalok={},
                            tarolo=SimpleNamespace(fiok=lambda sid: {}, adat={"postafiokok": {"P1": {"latott": {"x": "y"}, "osszes_talalt": 2}}}))
    ki = asyncio.run(DG.async_get_config_entry_diagnostics(None, SimpleNamespace(runtime_data=koord, subentries={"P1": pf})))
    szoveg = repr(ki)
    assert "titkos@example.com" not in szoveg and "abcdefgh" not in szoveg
    assert ki["postafiokok"]["P1"]["beallitas"]["imap_szerver"] == "imap.gmail.com"
    assert ki["postafiokok"]["P1"]["allapot"]["osszes_talalt"] == 2


# --------------------------------------------------------------------------------------------- beállító felület


def _flow_hass(entry=None):
    from custom_components.hu_rezsi.const import DOMAIN
    from motor.dijszabas import DijszabasTar

    async def executor(fn, *args):
        return fn(*args)

    entries = [entry] if entry else []
    return SimpleNamespace(
        async_add_executor_job=executor,
        data={DOMAIN: {"tar": DijszabasTar.mappabol(tests.conftest.DIJSZABASOK)}},
        config_entries=SimpleNamespace(async_get_known_entry=lambda eid: entry, async_entries=lambda dom: entries),
    )


PF_ADAT = {"nev": "Saját", "email_cim": "a@example.com", "jelszo": "abcd efgh ijkl mnop", "imap_szerver": "imap.gmail.com",
           "imap_port": 993.0, "imap_ssl": True, "email_napok": 45.0, "email_kuka": True}


def test_postafiok_flow_hibas_jelszo_es_mentes(monkeypatch):
    from custom_components.hu_rezsi import config_flow as cf, email_szamlak as pes

    def rossz(pf):
        raise pes.HitelesitesiHiba("x")

    monkeypatch.setattr(pes, "bejelentkezes_proba", rossz)
    f = cf.PostafiokFlow()
    f.hass, f.handler, f.context, f.flow_id = _flow_hass(), ("E1", "postafiok"), {"source": "user"}, "1"
    r = asyncio.run(f.async_step_user())
    assert r["type"] == "form" and "jelszo" in [str(k) for k in r["data_schema"].schema]
    r = asyncio.run(f.async_step_user(dict(PF_ADAT)))
    assert r["type"] == "form" and r["errors"] == {"base": "hitelesites_gmail"}

    def nincs_halozat(pf):
        raise pes.KapcsolatiHiba("x")

    monkeypatch.setattr(pes, "bejelentkezes_proba", nincs_halozat)
    assert asyncio.run(f.async_step_user(dict(PF_ADAT)))["errors"] == {"base": "kapcsolat"}
    probalt = []
    monkeypatch.setattr(pes, "bejelentkezes_proba", lambda pf: probalt.append(pf))
    r = asyncio.run(f.async_step_user(dict(PF_ADAT)))
    assert r["type"] == "create_entry" and r["title"] == "Saját"
    assert r["data"]["imap_port"] == 993 and r["data"]["email_napok"] == 45 and "nev" not in r["data"]
    assert probalt[0].jelszo == "abcdefghijklmnop"  # Gmail: szóközök nélkül próbálja


def test_postafiok_flow_ujrakonfiguralas_megtartja_a_jelszot(monkeypatch):
    from custom_components.hu_rezsi import config_flow as cf, email_szamlak as pes

    sub = SimpleNamespace(subentry_id="P1", title="Saját", subentry_type="postafiok",
                          data={"email_cim": "a@example.com", "jelszo": "regi", "imap_szerver": "imap.gmail.com", "imap_port": 993})
    entry = SimpleNamespace(entry_id="E1", subentries={"P1": sub})
    frissitett = {}
    f = cf.PostafiokFlow()
    f.hass, f.handler, f.flow_id = _flow_hass(entry), ("E1", "postafiok"), "1"
    f.context = {"source": "reconfigure", "subentry_id": "P1"}
    monkeypatch.setattr(f, "async_update_and_abort", lambda e, s, **kw: frissitett.update(kw) or {"type": "abort"})
    monkeypatch.setattr(pes, "bejelentkezes_proba", lambda pf: None)
    r = asyncio.run(f.async_step_reconfigure())
    assert r["type"] == "form"
    # A jelszó nem töltődik vissza az űrlapba (nincs alapértéke).
    jelszo_kulcs = next(k for k in r["data_schema"].schema if str(k) == "jelszo")
    assert jelszo_kulcs.default is vol_undefined()
    adat = dict(PF_ADAT, jelszo="")
    asyncio.run(f.async_step_user(adat))
    assert frissitett["data"]["jelszo"] == "regi"


def vol_undefined():
    import voluptuous as vol

    return vol.UNDEFINED


def test_fiok_flow_email_lepes_javasolt_felado_es_alap_mappa():
    from custom_components.hu_rezsi import config_flow as cf

    pf = SimpleNamespace(subentry_id="P1", title="Párom", subentry_type="postafiok", data={})
    masik = SimpleNamespace(subentry_id="F2", title="Másik", subentry_type="fiok", data={"szamla_mappa": "Szamlak/Villany_Haz"})
    entry = SimpleNamespace(entry_id="E1", subentries={"P1": pf, "F2": masik})
    f = cf.FiokFlow()
    f.hass, f.handler, f.context, f.flow_id = _flow_hass(entry), ("E1", "fiok"), {"source": "user"}, "1"
    f._adat = {"nev": "Villany Ház", "kozmu": "villany", "szolgaltato": "mvm_demasz", "dijszabas": "villany/a1"}
    r = asyncio.run(f.async_step_email())
    assert r["type"] == "form" and r["step_id"] == "email"
    halado = next(v for k, v in r["data_schema"].schema.items() if str(k) == "halado")
    assert halado.options["collapsed"] is True  # új fiók: tartalom szerinti besorolás, a kézi szűrők a Haladóban
    auto = next(k for k in r["data_schema"].schema if str(k) == "email_auto")
    assert auto.default() is True
    felado = next(k for k in halado.schema.schema if str(k) == "email_feladok")
    assert felado.description == {"suggested_value": "mvmee.hu"}  # Démász-területen is az MVM Next küldi
    assert r["description_placeholders"]["mappa"] == "Szamlak/Villany_Haz_2"  # a foglalt mappa mellé
    r = asyncio.run(f.async_step_email({"email_postafiokok": ["P1"], "email_auto": False, "halado": {"email_feladok": ""}}))
    assert r["errors"] == {"base": "felado_kell"}  # kézi módban feladó kell
    r = asyncio.run(f.async_step_email({"email_postafiokok": ["P1"], "email_auto": False,
                                        "halado": {"email_feladok": "mvmee.hu", "email_irsz": "1111"}}))
    assert r["type"] == "create_entry"
    assert r["data"]["szamla_mappa"] == "Szamlak/Villany_Haz_2" and r["data"]["email_postafiokok"] == ["P1"]
    assert r["data"]["email_irsz"] == "1111"
