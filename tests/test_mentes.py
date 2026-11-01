"""Rezsikövető mentés és visszaállítás (mentes.py): zip oda-vissza, átkulcsolás, számlák, biztonság."""

import json
import zipfile

import pytest
from mentes import (
    FORMATUM,
    MentesHiba,
    OtthonMentes,
    atkulcsol,
    egyedi_nev,
    fajlnev,
    mentesek_listaja,
    negyed_atkulcsol,
    otthon_szamlai,
    regiek_torlese,
    szamla_fajlok,
    szamla_mappak,
    szamlak_kicsomagol,
    zip_ir,
    zip_olvas,
)

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi


def _otthon():
    alar = [
        {"subentry_id": "A1", "subentry_type": "fiok", "title": "Villany A1", "data": {"kozmu": "villany", "szamla_mappa": "Dijnet /mvm"}},
        {"subentry_id": "GZ", "subentry_type": "fiok", "title": "Gáz", "data": {"kozmu": "gaz", "szamla_mappa": "Dijnet /mvm"}},
        {"subentry_id": "SZ", "subentry_type": "sziget", "title": "Sziget", "data": {"szerepek": ["pv"]}},
    ]
    tar = {"fiokok": {"A1": {"merok": [{"gyari_szam": "1"}], "szamlak": {"111": {"osszeg": "100"}}}, "GZ": {"merok": []},
                      "TOROLT": {"merok": []}},
           "szigetek": {"SZ": {"leolvasasok": {"fogyasztas": [{"ido": "2026-01-01T00:00:00", "allas": "5"}]}}}}
    return OtthonMentes("Kertes ház", "E1", alar, tar, {"A1": {"2026-10-01T00:00": 0.1}},
                        beallitas={"futes": "climate.futes", "kulso_homerseklet": "sensor.kinti"})


def test_oda_vissza(tmp_path):
    cfg = tmp_path / "config"
    (cfg / "Dijnet /mvm" / "2026").mkdir(parents=True)
    (cfg / "Dijnet /mvm" / "a.pdf").write_bytes(b"%PDF-1")
    (cfg / "Dijnet /mvm" / "2026" / "b.xml").write_bytes(b"<x/>")
    (cfg / "Dijnet /mvm" / "megjegyzes.txt").write_text("nem számla")
    o = _otthon()
    sz = szamla_fajlok(cfg, szamla_mappak(o.alarendeltek))
    assert [r for r, _ in sz] == ["Dijnet /mvm/2026/b.xml", "Dijnet /mvm/a.pdf"]
    cel = tmp_path / "m" / fajlnev("2026-10-06T12:34:56", "Kertes ház otthon")
    assert cel.name == "rezsikoveto_mentes_kertes-haz-otthon_20261006-123456.zip"
    assert zip_ir(cel, [o], sz, "2.1.0", "2026-10-06T12:34:56") > 0
    man, otthonok, szamlak = zip_olvas(cel)
    assert man["formatum"] == FORMATUM and man["szamlak"] == 2 and otthonok[0].dict() == o.dict()
    assert otthonok[0].beallitas == {"futes": "climate.futes", "kulso_homerseklet": "sensor.kinti"}  # az otthon beállításai is
    assert otthon_szamlai(otthonok[0], szamlak) == szamlak
    # visszaírás üres konfigurációba, majd ismét: másodszor minden már megvan (nem ír felül)
    cel_cfg = tmp_path / "uj"
    assert szamlak_kicsomagol(cel, cel_cfg) == (2, 0)
    assert (cel_cfg / "Dijnet /mvm" / "a.pdf").read_bytes() == b"%PDF-1"
    assert szamlak_kicsomagol(cel, cel_cfg) == (0, 2)
    lista = mentesek_listaja(cel.parent)
    assert lista[0]["otthonok"] == ["Kertes ház"] and lista[0]["szamlak"] == 2


def test_atkulcsolas():
    o = _otthon()
    terkep = {"A1": "uj1", "GZ": "uj2", "SZ": "uj3"}
    t = atkulcsol(o.tar, terkep)
    assert set(t["fiokok"]) == {"uj1", "uj2"} and set(t["szigetek"]) == {"uj3"}  # a törölt fiók maradványa kimarad
    assert t["fiokok"]["uj1"]["szamlak"]["111"]["osszeg"] == "100"
    assert negyed_atkulcsol(o.negyedek, terkep) == {"uj1": {"2026-10-01T00:00": 0.1}}


def test_zip_slip_es_idegen_fajl(tmp_path):
    rossz = tmp_path / "rossz.zip"
    with zipfile.ZipFile(rossz, "w") as z:
        z.writestr("manifest.json", json.dumps({"formatum": FORMATUM, "otthonok": []}))
        z.writestr("szamlak/../../kiszokik.pdf", b"x")
        z.writestr("/szamlak/abszolut.pdf", b"x")
        z.writestr("szamlak/ok.pdf", b"x")
        z.writestr("szamlak/futtathato.sh", b"x")
    _, _, szamlak = zip_olvas(rossz)
    assert szamlak == ["szamlak/ok.pdf"]
    assert szamlak_kicsomagol(rossz, tmp_path / "cfg") == (1, 0)
    assert not (tmp_path / "kiszokik.pdf").exists()
    with pytest.raises(MentesHiba):
        zip_olvas(tmp_path / "nincs.zip")
    nem = tmp_path / "nem.zip"
    with zipfile.ZipFile(nem, "w") as z:
        z.writestr("valami.txt", "x")
    with pytest.raises(MentesHiba):
        zip_olvas(nem)


def test_egyedi_nev_es_regiek(tmp_path):
    assert egyedi_nev("Kertes ház", {"Városi lakás"}) == "Kertes ház"
    assert egyedi_nev("Kertes ház", {"Kertes ház", "Kertes ház (visszaállítva)"}) == "Kertes ház (visszaállítva 2)"
    import os
    for i in range(5):
        f = tmp_path / f"rezsikoveto_mentes_osszes_2026100{i}-000000.zip"
        f.write_bytes(b"x")
        os.utime(f, (1000 + i, 1000 + i))
    (tmp_path / "mas.zip").write_bytes(b"x")
    assert regiek_torlese(tmp_path, 3) == ["rezsikoveto_mentes_osszes_20261000-000000.zip", "rezsikoveto_mentes_osszes_20261001-000000.zip"]
    assert (tmp_path / "mas.zip").exists() and regiek_torlese(tmp_path, 0) == []


def _ha_mentes(tmp_path):
    """Kitalált Home Assistant mentés: külső tar → homeassistant.tar.gz → data/…"""
    import io
    import tarfile

    ce = {"data": {"entries": [
        {"domain": "hu_rezsi", "entry_id": "E1", "title": "Kertes ház", "subentries": [
            {"subentry_id": "A1", "subentry_type": "fiok", "title": "Villany A1",
             "data": {"forras_entitas": "sensor.shelly_energia", "szamla_mappa": "Dijnet /mvm"}},
            {"subentry_id": "SZ", "subentry_type": "sziget", "title": "Sziget",
             "data": {"szerepek": ["pv"], "forras_fogyasztas": ["sensor.load"], "forras_pv": ["sensor.pv1", "sensor.pv2"]}}]},
        {"domain": "masik", "entry_id": "X", "title": "Más", "subentries": []}]}}
    reg = {"data": {"entities": [{"entity_id": "sensor.shelly_energia", "name": None, "original_name": "Shelly összes energia",
                                  "unit_of_measurement": "kWh"}]}}
    fajlok = {
        "data/.storage/core.config_entries": json.dumps(ce).encode(),
        "data/.storage/core.entity_registry": json.dumps(reg).encode(),
        "data/.storage/hu_rezsi.E1": json.dumps({"data": {"fiokok": {"A1": {"merok": []}}, "szigetek": {"SZ": {}}}}).encode(),
        "data/.storage/hu_rezsi.E1.bak-2026": b"{}",
        "data/.storage/hu_rezsi_negyedek.E1": json.dumps({"data": {"A1": {"t": 1}}}).encode(),
        "data/Dijnet /mvm/a.pdf": b"%PDF",
        "data/www/kep.pdf": b"nem szamla",
        "data/configuration.yaml": b"x",
    }
    belso = io.BytesIO()
    with tarfile.open(fileobj=belso, mode="w:gz") as t:
        for n, b in fajlok.items():
            i = tarfile.TarInfo(n)
            i.size = len(b)
            t.addfile(i, io.BytesIO(b))
    kulso = tmp_path / "ha.tar"
    with tarfile.open(kulso, "w") as t:
        i = tarfile.TarInfo("homeassistant.tar.gz")
        i.size = len(belso.getvalue())
        t.addfile(i, io.BytesIO(belso.getvalue()))
        j = tarfile.TarInfo("./backup.json")
        j.size = 2
        t.addfile(j, io.BytesIO(b"{}"))
    return kulso


def test_ha_mentesbol(tmp_path):
    from mentes import ha_mentes_olvas, ha_mentesbol_otthonok

    with _ha_mentes(tmp_path).open("rb") as f:
        t = ha_mentes_olvas(f, tmp_path / "tmp")
    assert set(t.tarolok) == {"hu_rezsi.E1", "hu_rezsi_negyedek.E1"} and list(t.szamlak) == ["Dijnet /mvm/a.pdf"]
    [o] = ha_mentesbol_otthonok(t)
    assert o.nev == "Kertes ház" and o.tar["fiokok"] == {"A1": {"merok": []}} and o.negyedek == {"A1": {"t": 1}}
    assert o.szenzorok["sensor.shelly_energia"] == {"nev": "Shelly összes energia", "egyseg": "kWh"}
    assert o.szenzorok["sensor.pv2"]["nev"] == "sensor.pv2"  # nincs a nyilvántartásban: az azonosító marad


def test_szenzor_hivatkozasok_es_csere():
    from mentes import szenzor_csere, szenzor_hivatkozasok

    alar = [{"subentry_id": "A1", "subentry_type": "fiok", "title": "H", "data": {"forras_entitas": "sensor.a", "h_teli_forras": "sensor.t"}},
            {"subentry_id": "SZ", "subentry_type": "sziget", "title": "S", "data": {"forras_pv": ["sensor.p1", "sensor.p2"]}}]
    h = szenzor_hivatkozasok(alar)
    assert [(x["kulcs"], x["idx"], x["entity_id"], x["szerep"]) for x in h] == [
        ("forras_entitas", None, "sensor.a", "mérőállás / fogyasztás"), ("h_teli_forras", None, "sensor.t", "H téli regiszter (1.81)"),
        ("forras_pv", 0, "sensor.p1", "szigetüzem: PV-termelés"), ("forras_pv", 1, "sensor.p2", "szigetüzem: PV-termelés")]
    assert szenzor_csere(alar[0]["data"], "forras_entitas", None, "sensor.uj")["forras_entitas"] == "sensor.uj"
    assert "h_teli_forras" not in szenzor_csere(alar[0]["data"], "h_teli_forras", None, "")
    assert szenzor_csere(alar[1]["data"], "forras_pv", 1, "sensor.p9")["forras_pv"] == ["sensor.p1", "sensor.p9"]
    assert szenzor_csere(alar[1]["data"], "forras_pv", 0, None)["forras_pv"] == ["sensor.p2"]
