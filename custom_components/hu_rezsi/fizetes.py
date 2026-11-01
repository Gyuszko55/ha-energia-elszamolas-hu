"""Számlák pénzügyi teljesítése: fizetve-e, mikor, a fizetési határidő, lejárt-e.

Forrás (erősségi sorrendben): a kézzel rögzített állapot (tarolt["fizetesek"][sorszám] = {fizetve, datum}), a
Díjnet-integráció kifizetett számlái (számlaszám szerint), végül a számlán megadott fizetési mód: csoportos beszedési
megbízásnál / beszámításnál (kompenzálás) a határidő napján fizetettnek vesszük. Ha a fiókhoz állandó (ütemezett) banki
átutalás tartozik (a hónap N. napján, munkaszüneti napon az utána következő első banki munkanapon), a számla kelte utáni
első ilyen napon fizetettnek vesszük – addig nem lejárt, akkor sem, ha a határidő korábbi. Határidő: a számláról (MVM XML/PDF), különben a Díjnetből.
Nulla vagy mínusz fizetendő (visszatérítés, a folyószámláról rendezett, sztornó): nincs fizetendő."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from .motor.munkarend import munkanap
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from motor.munkarend import munkanap


def _dec(x: Any) -> Decimal | None:
    try:
        return Decimal(str(x)) if x is not None else None
    except InvalidOperation:
        return None


def utemezett_nap(kelte: date, nap: int) -> date:
    """Az állandó átutalás első napja a számla kelte után (aznap is): a hónap `nap`. napja (rövidebb hónapban az
    utolsó napja), ha munkaszüneti napra (hétvége, ünnep, áthelyezett pihenőnap) esik, az utána következő első munkanap."""
    def honap_napja(ev: int, ho: int) -> date:
        return date(ev, ho, min(nap, monthrange(ev, ho)[1]))
    d = honap_napja(kelte.year, kelte.month)
    if d < kelte:
        d = honap_napja(kelte.year + (kelte.month == 12), kelte.month % 12 + 1)
    while not munkanap(d):
        d += timedelta(days=1)
    return d


def allapot(sorszam: str, szamla: dict[str, Any], kezi: dict[str, Any] | None, dijnet: dict[str, dict] | None, ma: date,
            utalas_nap: int | None = None, sztornozva: bool = False) -> dict[str, Any]:
    """{fizetve, datum, forras (kezi | dijnet | beszedes | utemezett | None), hatarido, nincs_fizetendo, lejart, osszeg,
    utemezett (az állandó átutalás napja, ha van), sztornozva}. utalas_nap: a fiók állandó átutalásának napja (1–31).
    sztornozva: a számlát stornó érvénytelenítette – nincs fizetendő, nem lejárt (a helyette kiállítottat kell fizetni)."""
    osszeg = _dec(szamla.get("osszeg"))
    # A ténylegesen fizetendő: MVM közös folyószámlánál a számlaérték a folyószámla-tételekkel (túlfizetés, átvezetés,
    # kötbér) – pl. 991 Ft-os részszámla, −47 138 Ft fizetendő: nincs mit fizetni.
    tetelek = szamla.get("egyeb_tetelek") or []
    if szamla.get("tipus") == "resz" and tetelek and _dec(szamla.get("szamlaertek")) is not None:  # elszámolónál az összeg maga a fizetendő
        osszeg = _dec(szamla["szamlaertek"]) + sum((_dec(o) or Decimal(0) for _, o in tetelek), Decimal(0))
    nincs = sztornozva or szamla.get("tipus") == "storno" or (osszeg is not None and osszeg <= 0)
    dn = (dijnet or {}).get(sorszam) or (dijnet or {}).get(sorszam.lstrip("0"))
    if kezi is not None:
        fizetve, datum, forras = bool(kezi.get("fizetve")), kezi.get("datum"), "kezi"
    elif dn and dn.get("fizetve"):
        fizetve, datum, forras = True, dn["fizetve"], "dijnet"
    else:
        fizetve, datum, forras = False, None, None
    hatarido = szamla.get("hatarido") or (dn or {}).get("hatarido")
    fm = (szamla.get("fizetesi_mod") or "").lower()
    if not fizetve and forras is None and hatarido and fm.startswith(("beszed", "csoportos", "kompenz")) and date.fromisoformat(hatarido) <= ma:
        fizetve, datum, forras = True, hatarido, "beszedes"
    utem = utemezett_nap(date.fromisoformat(str(szamla["kelte"])[:10]), int(utalas_nap)) if utalas_nap and szamla.get("kelte") and not nincs else None
    if utem is not None and not fizetve and forras is None and utem <= ma:
        fizetve, datum, forras = True, utem.isoformat(), "utemezett"
    # Állandó átutalásnál a számla az átutalás napjáig nem lejárt (a banki megbízás akkor teljesíti).
    hatar = max(date.fromisoformat(hatarido), utem) if hatarido and utem else (date.fromisoformat(hatarido) if hatarido else utem)
    lejart = bool(not fizetve and not nincs and hatar and hatar < ma)
    return {"fizetve": fizetve, "datum": datum if fizetve else None, "forras": forras, "hatarido": hatarido,
            "nincs_fizetendo": nincs, "lejart": lejart, "osszeg": int(osszeg) if osszeg is not None else None,
            "utemezett": utem.isoformat() if utem else None, "sztornozva": sztornozva}


def osszesito(allapotok: list[dict[str, Any]], ma: date, napok: int = 90) -> dict[str, Any]:
    """Nyitott (nem fizetett, van fizetendő) és ebből lejárt számlák darabra és forintra – csak a legutóbbi `napok`
    napban esedékesek (a régebbiekről gyakran nincs adat, pl. nem a Díjneten fizették: azokat nem jelezzük)."""
    hatar = ma.toordinal() - napok
    # Állandó átutalásnál a tényleges határnap az átutalás napja, ha az későbbi a számla határidejénél.
    allapotok = [a | {"hatarido": max(x for x in (a["hatarido"], a.get("utemezett")) if x)} if a.get("utemezett") else a for a in allapotok]
    friss = [a for a in allapotok if a["hatarido"] and date.fromisoformat(a["hatarido"]).toordinal() >= hatar]
    nyitott = [a for a in friss if not a["fizetve"] and not a["nincs_fizetendo"] and a["osszeg"]]
    lejart = [a for a in nyitott if a["lejart"]]
    return {"nyitott_db": len(nyitott), "nyitott_ft": sum(a["osszeg"] for a in nyitott),
            "lejart_db": len(lejart), "lejart_ft": sum(a["osszeg"] for a in lejart),
            "kovetkezo_hatarido": min((a["hatarido"] for a in nyitott if a["hatarido"] and not a["lejart"]), default=None)}
