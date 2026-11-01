"""Mérő nélküli (átalánydíjas) gázfogyasztók havi MJ-mennyisége.

Forrás: MVM „Földgázdíjak mérő nélküli (átalánydíjas) ügyfeleknek 2023. október 1-jétől” (Átalány_országos_2023/1),
minden földgázelosztó területén egységes. A díj: MJ/hó × 2,465 Ft/MJ nettó (bruttó 3,131), a díjszabás
gaz/mero_nelkuli szerint.
"""

from __future__ import annotations

from decimal import Decimal

TUZHELYEK = ("2_langu", "3_4_langu", "4_langu_elektromos_sutovel", "5_langu", "garzon")
SZOBASZAMOK = ("1", "1.5", "2", "2.5", "3", "3.5", "4")

# szobaszám → tűzhely → MJ/hó
MJ_HO: dict[str, dict[str, int]] = {
    "1": {"2_langu": 210, "3_4_langu": 300, "4_langu_elektromos_sutovel": 240, "5_langu": 315, "garzon": 250},
    "1.5": {"2_langu": 300, "3_4_langu": 370, "4_langu_elektromos_sutovel": 310, "5_langu": 390, "garzon": 310},
    "2": {"2_langu": 350, "3_4_langu": 450, "4_langu_elektromos_sutovel": 390, "5_langu": 475, "garzon": 390},
    "2.5": {"2_langu": 410, "3_4_langu": 520, "4_langu_elektromos_sutovel": 460, "5_langu": 545, "garzon": 450},
    "3": {"2_langu": 470, "3_4_langu": 600, "4_langu_elektromos_sutovel": 540, "5_langu": 630, "garzon": 520},
    "3.5": {"2_langu": 530, "3_4_langu": 690, "4_langu_elektromos_sutovel": 630, "5_langu": 725, "garzon": 600},
    "4": {"2_langu": 610, "3_4_langu": 750, "4_langu_elektromos_sutovel": 690, "5_langu": 790, "garzon": 660},
}


def havi_mj(szobaszam: str | float | None, tuzhely: str | None) -> Decimal | None:
    """A havi átalány-mennyiség (MJ), ha a szobaszám és a tűzhely érvényes."""
    if szobaszam is None or tuzhely is None:
        return None
    kulcs = f"{float(szobaszam):g}"
    sor = MJ_HO.get(kulcs)
    return Decimal(sor[tuzhely]) if sor and tuzhely in sor else None
