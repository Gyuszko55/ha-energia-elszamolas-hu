"""A következő számla időszaka és a diktálásos számlázás felismerése (motor.kovetkezo_szamla)."""

from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from motor.kovetkezo_szamla import diktalas_szerint_szamlaz, kovetkezo_szamla_idoszak

MA = date(2026, 10, 5)


def test_diktalasos_szamlazas_felismerese():
    assert diktalas_szerint_szamlaz(["resz", "resz", "elszamolo", "elszamolo"], [], MA)  # Kertes ház A1
    assert not diktalas_szerint_szamlaz(["resz", "elszamolo", "resz"], [], MA)  # átalány (H, gáz)
    assert not diktalas_szerint_szamlaz(["elszamolo"], [], MA)  # egy számlából nem dönthető el
    assert diktalas_szerint_szamlaz(["resz"], [date(2026, 9, 9)], MA)  # friss saját diktálás
    assert not diktalas_szerint_szamlaz(["resz"], [date(2026, 3, 1)], MA)


def test_idoszak_a_diktalasi_ablak_kozepeig():
    # Utolsó számla szept. 9-én zárult, ablak 8–14: szept. 10. – okt. 11.
    assert kovetkezo_szamla_idoszak(date(2026, 9, 9), MA, (8, 14)) == (date(2026, 9, 10), date(2026, 10, 11))
    # Az ablak után már a következő hónap közepe.
    assert kovetkezo_szamla_idoszak(date(2026, 10, 10), date(2026, 10, 20), (8, 14)) == (date(2026, 10, 11), date(2026, 11, 11))
    # Az ablakon belül, a közepe után: ma.
    assert kovetkezo_szamla_idoszak(date(2026, 9, 9), date(2026, 10, 13), (8, 14))[1] == date(2026, 10, 13)


def test_idoszak_ablak_nelkul_az_utem_szerint():
    assert kovetkezo_szamla_idoszak(date(2026, 8, 31), MA, None, 2) == (date(2026, 9, 1), date(2026, 10, 31))
    assert kovetkezo_szamla_idoszak(date(2026, 6, 30), MA, None, 1) == (date(2026, 7, 1), date(2026, 10, 30))


def test_eves_leolvasas_kulon_szamla_es_20_nap():
    # Kertes ház A1, valódi MVM-számlák: 2025-09-09-ig számlázva, éves leolvasás 10-01 → számla 09-10 – 10-01;
    # utána 10-02 – 11-10 (az októberi, 20 napon belüli diktálás kimaradt).
    assert kovetkezo_szamla_idoszak(date(2025, 9, 9), date(2025, 10, 5), (8, 14), 1, date(2025, 10, 1)) == (
        date(2025, 9, 10), date(2025, 10, 1))
    tol, ig = kovetkezo_szamla_idoszak(date(2025, 10, 1), date(2025, 10, 13), (8, 14), 1)
    assert tol == date(2025, 10, 2) and ig.month == 11
    # 2026: utolsó számla 09-09-ig, éves leolvasás 09-29 → 09-10 – 09-29 (nem nyúlik át az új évbe).
    assert kovetkezo_szamla_idoszak(date(2026, 9, 9), MA, (8, 14), 1, date(2026, 9, 29)) == (date(2026, 9, 10), date(2026, 9, 29))
    # Az évhatár a legutóbbi számla előtt: nem számít.
    assert kovetkezo_szamla_idoszak(date(2026, 9, 9), MA, (8, 14), 1, date(2025, 10, 1))[1] == date(2026, 10, 11)
