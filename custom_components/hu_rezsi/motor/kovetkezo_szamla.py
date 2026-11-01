"""A következő (még nem érkezett) számla időszaka – a számolómotor közös szabálya minden fiókra.

Elv: a következő számla a legutóbbi számla utolsó (valódi, diktált vagy leolvasott) napja utántól a következő
mérőállásig tart. Amíg ez a mérőállás nincs meg, a díja a saját mérésből számolódik, napi átlaggal a várható
napig kivetítve (lásd motor.elorejelzes.nyitott).

- Mért (diktálásos/leolvasásos) fióknál ez maga a folyó elszámolási időszak.
- Átalányos fióknál csak akkor, ha a szolgáltató valójában diktálás szerint számláz: az utolsó két számla
  elszámoló, vagy az utóbbi időben diktáltál. Különben a következő számla az átalány.
"""

from __future__ import annotations

from datetime import date, timedelta

DIKTALT_NAPOK = 120  # ennyi napon belüli diktálás után a következő számla a diktált állás szerint jön


def _honap_mulva(d: date, n: int) -> date:
    ho = d.month - 1 + n
    ev, ho = d.year + ho // 12, ho % 12 + 1
    napok = [31, 29 if ev % 4 == 0 and (ev % 100 != 0 or ev % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(ev, ho, min(d.day, napok[ho - 1]))


def diktalas_szerint_szamlaz(tipusok: list[str], diktalasok: list[date], ma: date) -> bool:
    """tipusok: a nem stornó számlák típusa az elszámolt időszak szerint időrendben; diktalasok: a saját diktált
    állások napjai. Igaz, ha az utolsó két számla elszámoló (havi diktálásos számlázás), vagy DIKTALT_NAPOK
    napon belül volt diktálás."""
    if len(tipusok) >= 2 and tipusok[-1] == tipusok[-2] == "elszamolo":
        return True
    return any(0 <= (ma - n).days <= DIKTALT_NAPOK for n in diktalasok)


def kovetkezo_szamla_idoszak(
    utolso_vege: date, ma: date, ablak: tuple[int, int] | None, periodus_ho: int = 1, evhatar: date | None = None
) -> tuple[date, date] | None:
    """(tol, ig) – mindkettő benne van az időszakban. tol: a legutóbbi számla utolsó napja utáni nap. ig: a várható
    diktálás napja – a diktálási ablak közepe ebben vagy a következő hónapban (nem a múltban); ablak nélkül a
    legutóbbi számla vége + a számlázási ütem (havi, kéthavi …), szükség szerint továbbléptetve a mai napig."""
    tol = utolso_vege + timedelta(days=1)
    if evhatar and tol <= evhatar:
        # Éves (elszámoló) leolvasás a legutóbbi számla után: az MVM addig külön számlát küld, a leolvasás napjával
        # együtt; az új elszámolási év másnap indul (Kertes ház A1 2025: 09-10 – 10-01, majd 10-02 – 11-10).
        return tol, evhatar
    if ablak:
        kozep = min((ablak[0] + ablak[1]) // 2, 28)
        ig = ma.replace(day=kozep)
        if ma.day > ablak[1]:
            ig = _honap_mulva(ma.replace(day=1), 1).replace(day=kozep)
        ig = max(ig, ma)
        # 20 napon belüli diktálás kimarad (az éves leolvasás után az első ablak – Kertes ház A1 2024, 2025).
        while (ig - utolso_vege).days < 20:
            ig = _honap_mulva(ig.replace(day=1), 1).replace(day=kozep)
    else:
        ig = _honap_mulva(utolso_vege, max(periodus_ho, 1))
        while ig < ma:
            ig = _honap_mulva(ig, max(periodus_ho, 1))
    return (tol, ig) if ig > tol else None
