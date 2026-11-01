"""Új fiók az első számla előtt: a fiókban megadott diktálási ablak, és az éves leolvasás utáni első időszak."""
from datetime import date

from modell import diktalasi_ablak, megadott_diktalasi_ablak
from motor.elorejelzes import idoszak


def test_megadott_ablak_formak():
    for x in ("8-14", "8–14", " 8 - 14. ", "8.-14."):
        assert megadott_diktalasi_ablak({"diktalasi_ablak": x}) == (8, 14)
    for x in ("", None, "14-8", "0-5", "8-40", "nyolc"):
        assert megadott_diktalasi_ablak({"diktalasi_ablak": x}) is None
    assert megadott_diktalasi_ablak(None) is None


def test_szamla_ablaka_erosebb():
    tarolt = {"szamlak": {"1": {"kelte": "2026-09-20", "diktalasi_ablak": [10, 16]}}}
    assert diktalasi_ablak(tarolt, {"diktalasi_ablak": "8-14"}) == (10, 16)
    assert diktalasi_ablak({"szamlak": {}}, {"diktalasi_ablak": "8-14"}) == (8, 14)


def test_eves_leolvasas_utan_a_kovetkezo_ablak_zar():
    # Birtokba vétel szept. 9., éves leolvasás szept. 29., diktálás minden hónap 8–14.: az októberi ablak 20 napon
    # belül van, kimarad – az időszak a novemberi ablakig tart (MVM: Kertes ház A1 2024 és 2025 – leolvasás 10-01, a
    # következő számla 10-02 – 11-11, ill. 10-02 – 11-10; Városi lakás H 2025: 10-14 után 10-15 – 11-15).
    hatarok = [date(2026, 9, 9), date(2026, 9, 29)]
    assert idoszak(date(2026, 10, 5), "diktalas", 1, hatarok, (8, 14)) == (date(2026, 9, 29), date(2026, 11, 14))
    assert idoszak(date(2025, 10, 20), "diktalas", 1, [date(2025, 10, 1)], (8, 14)) == (date(2025, 10, 1), date(2025, 11, 14))
    # Ha egy határ az ablak elején van, a következő hónap ablaka zár (legalább 20 nap).
    assert idoszak(date(2026, 10, 10), "diktalas", 1, [date(2026, 10, 9)], (8, 14)) == (date(2026, 10, 9), date(2026, 11, 14))
