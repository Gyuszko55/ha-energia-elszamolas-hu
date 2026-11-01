"""modell.py: a tárolt adatokból számolt időpontok."""
from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from modell import utem_szerinti_diktalas


def test_utem_szerinti_diktalas_negyhavi():
    """ALFÖLDVÍZ: négyhavi időszakok (máj.–aug., szept.–dec., jan.–ápr.), diktálás az időszak vége utáni hónap 10–15-én."""
    vege = date(2026, 8, 31)
    assert utem_szerinti_diktalas(vege, 4, (10, 15), date(2026, 9, 1)) == (date(2026, 9, 10), date(2026, 9, 15))
    assert utem_szerinti_diktalas(vege, 4, (10, 15), date(2026, 9, 15)) == (date(2026, 9, 10), date(2026, 9, 15))
    assert utem_szerinti_diktalas(vege, 4, (10, 15), date(2026, 10, 6)) == (date(2027, 1, 10), date(2027, 1, 15))
    assert utem_szerinti_diktalas(vege, 4, (10, 15), date(2027, 1, 16)) == (date(2027, 5, 10), date(2027, 5, 15))


def test_utem_szerinti_diktalas_ketthavi_zaro_honap():
    """DAKÖV (2026 márciusától kéthavonta): diktálás a záró hónap 20–25-én, a számla zárása előtt."""
    vege = date(2026, 9, 30)  # aug.–szept. időszak
    assert utem_szerinti_diktalas(vege, 2, (20, 25), date(2026, 10, 6), "zaro") == (date(2026, 11, 20), date(2026, 11, 25))
    assert utem_szerinti_diktalas(vege, 2, (20, 25), date(2026, 11, 26), "zaro") == (date(2027, 1, 20), date(2027, 1, 25))
