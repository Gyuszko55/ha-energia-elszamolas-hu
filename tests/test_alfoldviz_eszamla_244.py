"""2.4.4: az ALFÖLDVÍZ aláírt e-számlája (2026 ősz) – az oldal tartalma beágyazott űrlap (TCPDF/FPDI „/TPL0 Do”),
és a számlarészletező elrendezése is más (szintetikus, anonimizált minták; HA nélkül)."""

from datetime import date

import tests.conftest  # noqa: F401 – a csomag mappáját a path-ra teszi
from szamlak import alfoldviz_szoveg, pdf_szoveg

_ELSZ_UJ = """ALFÖLDVÍZ Zrt.
                                                                     Víziközmű-szolgáltatás elszámoló számla
        Elszámolási időszak:                     2025.12.01-2026.11.10             Felhasználó neve: Teszt Elek
        Fizetendő összeg:                                    4 301 Ft            Felhasználó címe: 1234 Példaváros, Minta
        Fizetési határidő:                                2026.12.11             utca 1.
                                                                                 Felhasználási hely címe: 1234 Példaváros, Minta
                                                                                 utca 1. 2.em 3.

 Vevő (fizető) azonosító száma: 100000000001
 Számla sorszáma:          900005LV26                                      Számla kelte:            2026.11.18
       Elszámolt mennyiség:                     Ivóvíz 4 m3
       Elszámolt mennyiség:                     Szennyvíz 10 m3
         12345678 számú vízmérőn               2026.02.10-2026.11.10                62-74                        12 m3              234,00 Ft/m3           2 808,00     27              3 566,16
         mért ivóvíz fogyasztással
         arányos díj
         Elvezetett mennyiséggel               2026.02.10-2026.03.31                   -                       2,19 m3              240,30 Ft/m3             526,26     27                 668,35
         arányos szennyvízdíj
         87654321 Elvezetett                   2025.12.01-2026.03.31                18-30                      4,21 m3              240,30 Ft/m3           1 011,66     27              1 284,81
         mennyiséggel arányos
         szennyvízdíj
         Bruttó számlaérték                                                                                                                                                                 4 301
         összesen*:
         Fizetendő összeg:                                                                                                                                                                  4 301
Következő leolvasás várható időpontja: 2026.11.09-2026.11.13
Leolvasás módja (LM) jelen számlában:   Leol
Következő mérőállás bejelentés időpontja: 2026.12.10-2026.12.15
Az elszámoló számlában elszámolt részszámlák sorszáma és a számla végösszege:
               Sorszám                             Számla végösszeg(Ft)
             900003LV26                                      1 209
             900004LV26                                      1 850
"""

_RESZ_UJ = """ALFÖLDVÍZ Zrt.
                                                                     Víziközmű-szolgáltatás 3. részszámla
        Elszámolt időszak:                     2026.09.01-2026.10.31
        Fizetendő összeg:                                    1 850 Ft
        Fizetési határidő:                                2026.11.25
 Számla sorszáma:          900004LV26                                      Számla kelte:            2026.11.04
       Elszámolt mennyiség:                     Ivóvíz 2 m3
       Elszámolt mennyiség:                     Szennyvíz 4 m3
         12345678 számú vízmérőn               2026.09.01-2026.10.31                68-70                         2 m3              234,00 Ft/m3             468,00     27                 594,36
         mért ivóvíz fogyasztással
         arányos díj
         Bruttó számlaérték                                                                                                                                                                 1 850
         összesen*:
Fogyasztás megállapításának módja: kalkulált
"""


def test_eszamla_elszamolo():
    """Az új elrendezés: egysoros mérősor (időszak, induló–záró állás), kétsoros elszámolt mennyiség, a számlaérték
    az „összesen*:” fölötti sorban, a kétsorba tördelt felhasználási hely; a melegvízmérő szennyvízsora nem mérőállás."""
    sz = alfoldviz_szoveg(_ELSZ_UJ, "es900005LV26_signed.pdf")
    assert sz.tipus == "elszamolo" and sz.sorszam == "900005LV26" and sz.kelte == date(2026, 11, 18)
    assert sz.osszeg == 4301 and sz.szamlaertek == 4301 and sz.hatarido == date(2026, 12, 11)
    assert sz.idoszak == (date(2026, 2, 10), date(2026, 11, 10))
    assert [(m.mero, m.datum, m.allas, m.leolvasott) for m in sz.meroallasok] == [
        ("12345678", date(2026, 2, 10), 62, True), ("12345678", date(2026, 11, 10), 74, True)]
    assert sz.elszamolt_viz["ivoviz"] == 4 and sz.elszamolt_viz["csatorna"] == 10 and not sz.elszamolt_viz["atalany"]
    assert sz.levont_szamlak == [("900003LV26", 1209), ("900004LV26", 1850)]
    assert sz.kovetkezo_diktalas == (date(2026, 12, 10), date(2026, 12, 15))
    assert sz.ugyfel["hely"] == "1234 Példaváros, Minta utca 1. 2.em 3." and sz.ugyfel["mero"] == "12345678"


def test_eszamla_reszszamla():
    sz = alfoldviz_szoveg(_RESZ_UJ)
    assert sz.tipus == "resz" and sz.idoszak == (date(2026, 9, 1), date(2026, 10, 31)) and sz.szamlaertek == 1850
    assert [(m.allas, m.valodi) for m in sz.meroallasok] == [(68, False), (70, False)]
    assert sz.elszamolt_viz == {"ivoviz": 2, "csatorna": 4, "atalany": True, "idoszak": ["2026-09-01", "2026-10-31"]}


def _pdf_urlappal(szoveg_sorok: list[str], urlapban: bool = True) -> bytes:
    """Egyoldalas PDF, amelynek tartalma csak egy beágyazott űrlapot rajzol ki (mint a TCPDF/FPDI aláírt számlán);
    urlapban=False: ugyanaz a szöveg közvetlenül az oldal tartalmában."""
    urlap = "BT /F1 10 Tf " + " ".join(f"1 0 0 1 40 {800 - 14 * i} Tm ({s}) Tj" for i, s in enumerate(szoveg_sorok)) + " ET"
    oldal = "q 1 0 0 1 0 0 cm /TPL0 Do Q" if urlapban else urlap
    obj = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /TPL0 5 0 R >> "
        "/Font << /F1 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(oldal)} >>\nstream\n{oldal}\nendstream",
        f"<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] /Resources << /Font << /F1 6 0 R >> >> /Length {len(urlap)} >>\nstream\n{urlap}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, hely = b"%PDF-1.4\n", []
    for i, o in enumerate(obj, 1):
        hely.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(obj) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{h:010d} 00000 n \n".encode() for h in hely)
    out += f"trailer\n<< /Size {len(obj) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_pdf_szoveg_beagyazott_urlapbol(tmp_path):
    """A layout-mód az űrlap szövegét is visszaadja (eddig csak az üres oldaltartalmat látta)."""
    f = tmp_path / "eszamla.pdf"
    f.write_bytes(_pdf_urlappal(["ALFOLDVIZ teszt", "Szamla sorszama: 900004LV26", "Fizetendo osszeg: 1 850 Ft"]))
    t = pdf_szoveg(f)
    assert "Szamla sorszama: 900004LV26" in t and "Fizetendo osszeg: 1 850 Ft" in t
    assert "900004LV26" in pdf_szoveg(f, "plain")


def test_pdf_szoveg_sima_oldal_valtozatlan(tmp_path):
    """Rendes szöveges oldal: ugyanaz a szöveg jön, mint a kibontással (és nem dupla)."""
    sorok = ["Szamla sorszama: 900004LV26", "Fizetendo osszeg: 1 850 Ft"]
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(_pdf_urlappal(sorok, urlapban=False))
    b.write_bytes(_pdf_urlappal(sorok))
    assert pdf_szoveg(a).count("900004LV26") == 1 and pdf_szoveg(a).split() == pdf_szoveg(b).split()
