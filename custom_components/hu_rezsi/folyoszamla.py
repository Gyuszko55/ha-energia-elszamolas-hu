"""Fiókonkénti folyószámla (számlakivonat) a könyvelési szabályok szerint.

Nyitó egyenleg, majd időrendben a könyvelési tételek: dátum (számlánál a kiállítás kelte, befizetésnél a fizetés
napja), megnevezés a főbb adatokkal (sorszám, elszámolt időszak, mennyiség), és két összeg-oszlop:
- **Követel** – a szolgáltató követelése: a számla értéke (elszámolónál a részszámlák levonása után), a késedelmi
  kamat, a másik fiókra átvezetett jóváírás;
- **Tartozik** – ami a követelést csökkenti: a befizetés, a jóváíró (mínuszos) számla, a kötbér, a másik fiókról
  átvezetett jóváírás.
Egyenleg = nyitó + Σ követel − Σ tartozik: pozitív = fizetendő hátralék, negatív = túlfizetés (jár vissza).

A számlák „egyéb tételei” (MVM: „Túlfizetés”, „Támogatás”, „Egyéb fizetendőt csökkentő tétel”; ALFÖLDVÍZ:
„figyelembe vett hátralék/túlfizetés”) a számla előtti egyenleget hozzák át – nem új mozgás, az egyenlegben már
benne van; az első számlánál ebből lesz a nyitó egyenleg. Áthozott az a sor, amelynek neve túlfizetés/hátralék, vagy
amelynek összege egy korábbi számla mínuszos fizetendőjével egyezik; minden más (kötbér, késedelmi kamat, új
támogatás) új mozgás. Az MVM-nél egy ügyfél villanyfiókjai (pl. A1 és H) egy közös folyószámlán vannak: ezek együtt könyvelődnek
(a számlán a „fizetendő” a közös egyenleg). A számlán közölt folyószámla-egyenleg (MVM) ellenőrzésként látszik.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from .szamlak import sztornozottak  # közös: a stornóval érvénytelenített számlák (a többi számítás is ezt használja)
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from szamlak import sztornozottak

TIPUS_NEV = {"resz": "Részszámla", "elszamolo": "Elszámoló számla", "vegszamla": "Végszámla", "storno": "Stornó számla",
             "egyeb": "Számla", "eloiras": "Közös költség előírás"}
FIZETES_NEV = {"kezi": "", "dijnet": "Díjnet szerint", "beszedes": "csoportos beszedési megbízás",
               "utemezett": "állandó átutalás",
               "feltetelezett": "feltételezett – nincs róla adat", "egyenleg": "a szolgáltató egyenlege szerint"}
FELTETELEZETT_NAP = 90  # ennyi nappal a határidő után a fizetési adat nélküli számlát kifizetettnek vesszük
# Áthozott egyenleg: a nevéből (túlfizetés, hátralék, …) vagy mert egy korábbi számla mínuszos fizetendőjével egyezik
# (az MVM ezt hol „Egyéb fizetendőt csökkentő tétel”, hol „Támogatás”, hol „Kötbér…” néven hozza át).
# Két tarifás közös MVM-folyószámlánál ez a sor a másik tarifáról hoz át egyenleget (tarifánkénti kivonatban átvezetés).
ATVEZETES_NEVEK = ("fizetendőt csökkentő", "fizetendőt növelő")
ATHOZOTT_NEVEK = ("túlfizetés", "hátralék", "figyelembe vett", "fizetendőt csökkentő", "fizetendőt növelő")
TURES = Decimal(1)  # forint-egyezés tűrése (kerekítés)


def _dec(x: Any) -> Decimal | None:
    try:
        return Decimal(str(x)) if x not in (None, "") else None
    except InvalidOperation:
        return None


def _szam(x: Decimal) -> str:
    return f"{x:.0f}" if x == x.to_integral_value() else f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def mennyiseg(x: dict[str, Any]) -> str | None:
    """A számlán elszámolt mennyiség szövegesen (kWh, m³, MJ, GJ) – ami a számláról ismert."""
    if (v := x.get("elszamolt_viz")) and v.get("ivoviz") is not None:
        s = f"ivóvíz {_szam(Decimal(str(v['ivoviz'])))} m³"
        if v.get("csatorna") is not None and Decimal(str(v["csatorna"])) != Decimal(str(v["ivoviz"])):
            s += f", szennyvíz {_szam(Decimal(str(v['csatorna'])))} m³"
        return s + (" (átalány)" if v.get("atalany") else "")
    if t := x.get("elszamolt_tavho"):
        resz = []
        if _dec(t.get("melegviz")):
            resz.append(f"melegvíz {_szam(Decimal(str(t['melegviz'])))} m³")
        if _dec(t.get("gj")):
            resz.append(f"hődíj {_szam(Decimal(str(t['gj'])))} GJ")
        if _dec(t.get("korrekcio_gj")) is not None:
            resz.append(f"hődíj-korrekció {_szam(Decimal(str(t['korrekcio_gj'])))} GJ")
        return ", ".join(resz) or None
    if g := x.get("elszamolt_gaz"):
        return f"{_szam(Decimal(str(g['m3'])))} m³ ({_szam(Decimal(str(g['mj'])))} MJ)" if g.get("m3") and g.get("mj") else None
    k = _dec(x.get("szamlazott_kwh")) if x.get("tipus") in ("elszamolo", "vegszamla") else None
    k = k if k is not None else _dec(x.get("elszamolt_kwh"))
    return f"{_szam(k)} kWh" if k is not None else None


LM_NEV = {"Becs": "becsült", "Dikt": "diktált", "Leol": "leolvasott", "Ell": "ellenőrző leolvasás"}


def oraallas(x: dict[str, Any], egyseg: str = "") -> str | None:
    """A számlán szereplő induló → záró óraállás szövegesen, mérőnként, a leolvasás módjával
    (pl. „óraállás 64 → 68 m³ (becsült)”)."""
    resz = []
    tobb = len([a for a in x.get("allasok") or [] if a.get("zaro")]) > 1
    for a in x.get("allasok") or []:
        ind, zar = a.get("indulo"), a.get("zaro")
        if not zar:
            continue
        sz = f"{_szam(Decimal(str(ind[1])))} → {_szam(Decimal(str(zar[1])))}" if ind else f"záró {_szam(Decimal(str(zar[1])))}"
        lm = LM_NEV.get((a.get("lm") or "")[:4], a.get("lm") or "")
        resz.append((f"{a.get('mero')}: " if tobb and a.get("mero") else "óraállás ") + f"{sz}{f' {egyseg}' if egyseg else ''}" + (f" ({lm})" if lm else ""))
    return "; ".join(resz) or None


def ertek(x: dict[str, Any]) -> Decimal:
    """A számla saját értéke (követelés): a bruttó számlaérték (elszámolónál a részszámlák már levonva), ennek híján a
    fizetendő az egyéb (folyószámla-) tételek nélkül. MVM-gáz elszámolón a számlaérték nem az egész időszaké – ott a
    fizetendő."""
    if x.get("forras") == "mvm_gaz" and x.get("tipus") in ("elszamolo", "vegszamla"):
        return _dec(x.get("osszeg")) or Decimal(0)
    if (e := _dec(x.get("szamlaertek"))) is not None:
        return e
    return (_dec(x.get("osszeg")) or Decimal(0)) - sum((_dec(o) or Decimal(0) for _, o in x.get("egyeb_tetelek") or []), Decimal(0))


# A szolgáltató ennyi napon belül könyveli le a befizetést (DAKÖV: 1–7 nap, Kertes ház 2023–2026).
KONYVELESI_NAP = 10


def _kozel(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= TURES


def _befizetes(x: dict[str, Any], f: dict[str, Any], ma: date) -> tuple[str | None, str | None]:
    """A számla befizetésének napja és forrása (kézi, Díjnet, beszedés), ill. feltételezett befizetés a határidőn, ha a
    határidő több mint FELTETELEZETT_NAP napja lejárt, és nincs róla fizetési adat."""
    hat = f.get("hatarido") or x.get("hatarido")
    hatar = date.fromisoformat(hat) if hat else date.fromisoformat(x.get("kelte")) + timedelta(days=15)
    if f.get("fizetve"):
        return f.get("datum") or hatar.isoformat(), f.get("forras")
    if f.get("forras") is None and (ma - hatar).days > FELTETELEZETT_NAP:
        return hatar.isoformat(), "feltetelezett"
    return None, None


def _van_adat(f: dict[str, Any]) -> bool:
    return bool(f.get("fizetve")) or f.get("forras") is not None


def _osszeg_adat(f: dict[str, Any]) -> bool:
    """Van-e a befizetett összegre is adat. A kézi jelölés csak a fizetés tényét és napját rögzíti: az összeg a
    szolgáltató egyenlegéből jön (a jóváírással fedezett részt nem kellett befizetni)."""
    return _van_adat(f) and f.get("forras") != "kezi"


def _egyenleg_befizetesek(szamlak: list[tuple], fizetesek: dict[str, dict[str, Any]]) -> tuple[dict, dict, str | None]:
    """A számlán közölt folyószámla-egyenlegből (DAKÖV: „egyenlege a számla kibocsátásakor”) visszafejtett befizetések
    a fizetési adat nélküli számlákra. Két egyenleget közlő számla között a befizetés = az előző egyenleg + a közben
    kiállított számlák fizetendője − az új egyenleg. Felosztás időrendben: előbb a befizetés, a maradékot a jóváírások
    (mínuszos fizetendők, korábbi többletbefizetés) fedezik, ha a számlát teljesen kiegyenlítik – a szolgáltató a
    jóváírást így, a befizetésnél számítja be. Kimenet: ({sorszám: {datum, osszeg}}, {jóváírás sorszáma: ahol
    beszámították}, az utolsó egyenleget közlő számla kelte – utána nincs visszafejtés)."""
    sor = [(x.get("kelte") or "", k, x) for k, x, *_ in szamlak if x.get("tipus") != "storno"]
    if sum(1 for *_, x in sor if _dec(x.get("folyoszamla")) is not None) < 2:
        return {}, {}, None
    fizetett: dict[str, dict[str, Any]] = {}
    hol: dict[str, str] = {}
    nyitott: list[list] = []  # [sorszám, maradék, határidő, kelte]
    jovairas: list[list] = []  # [sorszám | None, maradék]
    varhato = None  # az előző egyenleg + azóta kiállított fizetendők
    utolso = None  # az előző egyenleget közlő számla kelte: a befizetés ez után, de a következő előtt érkezett
    for kelte, k, x in sor:
        fiz = _dec(x.get("osszeg")) or Decimal(0)
        e = _dec(x.get("folyoszamla"))
        if e is not None and varhato is not None:
            p = varhato + fiz - e
            vege = date.fromisoformat(kelte) - timedelta(days=1)
            for n in list(nyitott):
                if _osszeg_adat(fizetesek.get(n[0]) or {}):  # saját fizetési adata van (Díjnet, beszedés): azzal rendezett
                    p -= n[1]
                    nyitott.remove(n)
                    continue
                t = min(max(p, Decimal(0)), n[1])
                if t:
                    hat = date.fromisoformat(n[2]) if n[2] else date.fromisoformat(n[3]) + timedelta(days=15)
                    d = max(min(hat, vege), date.fromisoformat(n[3]), date.fromisoformat(utolso))
                    elozo = fizetett.get(n[0], {"osszeg": Decimal(0)})
                    fizetett[n[0]] = {"datum": d.isoformat(), "osszeg": elozo["osszeg"] + t}
                    p -= t
                    n[1] -= t
                if n[1] > 0 and n[1] <= sum(j[1] for j in jovairas):
                    for j in jovairas:
                        v = min(j[1], n[1])
                        if v:
                            j[1] -= v
                            n[1] -= v
                            if j[0]:
                                hol[j[0]] = n[0]
                    jovairas = [j for j in jovairas if j[1] > 0]
                if n[1] <= 0:
                    nyitott.remove(n)
                    fizetett.setdefault(n[0], {"datum": vege.isoformat(), "osszeg": Decimal(0)})
                else:
                    break
            if p > TURES:  # többletbefizetés: a legutóbb rendezett számla befizetéséhez, jóváírásként tovább
                cel = max((kk for kk in fizetett), key=lambda kk: fizetett[kk]["datum"], default=None)
                if cel:
                    fizetett[cel]["osszeg"] += p
                    jovairas.append([None, p])
        if e is not None:
            varhato = e
            utolso = kelte
        elif varhato is not None:
            varhato += fiz
        if fiz > 0:
            nyitott.append([k, fiz, x.get("hatarido"), kelte])
        elif fiz < 0:
            jovairas.append([k, -fiz])
    return fizetett, hol, utolso


def _kozos_atvezetesek(sid: str, kozos: list[str], haztartas: dict[str, tuple[str, dict[str, dict[str, Any]]]],
                       fizetesek: dict[str, dict[str, Any]], ma: date) -> list[dict[str, Any]]:
    """Két tarifás közös (MVM) folyószámla tarifánkénti kivonatához: a számlák áthozott egyenlegéből (túlfizetés,
    csökkentő tétel, áthozott támogatás …) a saját rész a tarifa saját egyenlege a számla előtt; a többi a másik
    tarifáról jön – ez átvezetés (itt és ott ellentétes oldalon). A két tarifát időrendben, a befizetésekkel együtt
    szimuláljuk; a kimenet a sid átvezetés-tételei."""
    if len(kozos) != 2:
        return []
    esemenyek = []
    for s in kozos:
        for k, x in haztartas[s][1].items():
            esemenyek.append((x.get("kelte") or "", 0, s, k, x))
            fiz = _dec(x.get("osszeg"))
            if fiz is not None and fiz > 0 and x.get("tipus") != "storno":
                nap, _ = _befizetes(x, fizetesek.get(k) or {}, ma)
                if nap:
                    esemenyek.append((nap, 1, s, k, fiz))
    esemenyek.sort(key=lambda e: (e[0], e[1], e[3]))
    bal = {s: Decimal(0) for s in kozos}
    negativ: list[Decimal] = []
    elso = True
    sorok: list[dict[str, Any]] = []
    for datum, fajta, s, k, x in esemenyek:
        if fajta == 1:
            bal[s] -= x
            continue
        mas = next(t for t in kozos if t != s)
        athozott, mozgas = Decimal(0), Decimal(0)
        # A stornó „egyéb” sorai az eredeti számla áthozott egyenlegét fordítják vissza – nem új átvezetés.
        for tnev, o in [] if x.get("tipus") == "storno" else x.get("egyeb_tetelek") or []:
            o = _dec(o)
            if not o:
                continue
            atvitt = next((n for n in negativ if _kozel(n, o)), None) if o < 0 else None
            if atvitt is not None:
                negativ.remove(atvitt)
                athozott += o
            elif any(m in tnev.lower() for m in ATHOZOTT_NEVEK + ATVEZETES_NEVEK):
                athozott += o
            else:
                mozgas += o
        elotte = bal[s]
        bal[s] += ertek(x) + mozgas
        fiz = _dec(x.get("osszeg"))
        if fiz is not None and fiz < 0:
            negativ.append(fiz)
        if elso or not athozott:
            elso = False
            continue
        atvezet = (athozott - elotte).quantize(Decimal(1))
        if abs(atvezet) < 1:
            continue
        bal[s] += atvezet
        bal[mas] -= atvezet
        for kinek, osszeg, szoveg in ((s, atvezet, f"Átvezetés a(z) {haztartas[mas][0]} fiókról – a(z) {k} számlán beszámított közös egyenleg"),
                                      (mas, -atvezet, f"Átvezetés a(z) {haztartas[s][0]} {k} számlájára – beszámított közös egyenleg")):
            if kinek == sid:
                sorok.append({"datum": datum, "fajta": "egyeb", "sorszam": k, "fiok": None, "megnevezes": szoveg,
                              "kovetel": float(osszeg) if osszeg > 0 else 0.0, "tartozik": float(-osszeg) if osszeg < 0 else 0.0})
    return sorok


def kiegyenlites(tetelek: list[dict[str, Any]]) -> None:
    """A terhelések (követel) kiegyenlítésének napja – mint a szolgáltató folyószámla-kimutatásán. A jóváírások
    (befizetés, jóváíró számla, kötbér) időrendben a legrégebbi nyitott terhelést fedezik – a befizetés előbb a saját
    számláját, a stornó a sztornózott számlát. A már meglévő túlfizetésből fedezett terhelés a saját napján egyenlítődik ki.
    A tételekre: kiegyenlitve (nap) a teljesen fedezett terheléseken."""
    nyitott: list[list] = []  # [tétel, fennmaradó]
    keszlet: list[list] = []  # [nap, fennmaradó jóváírás]
    storno_cel = {t["sztornozott"] for t in tetelek if t.get("sztornozott")}  # ezeket a saját stornójuk egyenlíti ki
    for t in sorted(tetelek, key=lambda t: t["datum"]):  # stabil: a napon belüli sorrend marad
        if t["kovetel"] > 0:
            marad = Decimal(str(t["kovetel"]))
            while marad > 0 and keszlet and t.get("sorszam") not in storno_cel:
                v = min(marad, keszlet[0][1])
                marad -= v
                keszlet[0][1] -= v
                if keszlet[0][1] <= 0:
                    keszlet.pop(0)
            if marad <= 0:
                t["kiegyenlitve"] = t["datum"]
            else:
                nyitott.append([t, marad])
        if t["tartozik"] > 0:
            marad = Decimal(str(t["tartozik"]))
            # A stornó a sztornózott számlát, a befizetés (közleményben a számlaszám) előbb a saját számláját fedezi.
            sajat = t.get("sztornozott") or (t.get("sorszam") if t["fajta"] == "befizetes" else None)
            cel = [n for n in nyitott if sajat and n[0].get("sorszam") == sajat and n[0]["fajta"] == "szamla"] + [
                n for n in nyitott if n[0].get("sorszam") not in storno_cel]
            for n in cel:
                if marad <= 0:
                    break
                if n[1] <= 0:
                    continue
                v = min(marad, n[1])
                n[1] -= v
                marad -= v
                if n[1] <= 0:
                    n[0]["kiegyenlitve"] = t["datum"]
            nyitott = [n for n in nyitott if n[1] > 0]
            if marad > 0:
                keszlet.append([t["datum"], marad])


def kozos_csoport(sid: str, haztartas: dict[str, tuple[str, dict[str, dict[str, Any]]]]) -> list[str]:
    """A fiókkal közös folyószámlán lévő fiókok (önmagát is beleértve): MVM-villanynál az azonos ügyfél-azonosító."""
    def ids(s: str) -> set[str]:
        return {(x.get("ugyfel") or {}).get("azonosito") for x in haztartas[s][1].values()
                if x.get("forras") == "mvm_aram" and (x.get("ugyfel") or {}).get("azonosito")}
    sajat = ids(sid)
    return [s for s in haztartas if s == sid or (sajat and ids(s) & sajat)]


def kivonat(
    sid: str, haztartas: dict[str, tuple[str, dict[str, dict[str, Any]]]], fizetesek: dict[str, dict[str, Any]],
    nyito_kezi: dict[str, Any] | None, ma: date, kezi_tetelek: list[dict[str, Any]] | None = None,
    egysegek: dict[str, str] | None = None, egyutt: bool = True,
) -> dict[str, Any]:
    """A fiók (MVM közös folyószámlánál a csoport) folyószámlája. kezi_tetelek: kézi könyvelési tételek (pl. egyeztetés a
    szolgáltató folyószámlájával) – {id, datum, megnevezes, kovetel, tartozik}. haztartas: {sid: (fióknév, számlák)}; fizetesek: a
    számlák pénzügyi teljesítése sorszám szerint (fizetes.allapot, a csoport összes fiókjáé); nyito_kezi: kézzel
    megadott nyitó egyenleg {datum, osszeg}. Kimenet: {nev, fiokok, nyito, tetelek, zaro}."""
    kozos = kozos_csoport(sid, haztartas)
    # egyutt=False: tarifánként külön kivonat (a panel így mutatja); a közös MVM-folyószámla csak tájékoztatásul.
    csoport = kozos if egyutt else [sid]
    tobb = len(csoport) > 1
    szamlak = [(k, x, haztartas[s][0], (egysegek or {}).get(s, "")) for s in csoport for k, x in haztartas[s][1].items()]
    szamlak.sort(key=lambda t: (t[1].get("kelte") or "", t[0]))
    tetelek: list[dict[str, Any]] = []
    nyito: dict[str, Any] | None = None
    negativ: list[Decimal] = []  # korábbi számlák mínuszos fizetendői (még át nem hozva)
    # A számlán közölt egyenlegből visszafejtett befizetések (fizetési adat nélkül, pl. DAKÖV) – egy fióknál. A közös
    # (két tarifás) MVM-folyószámlánál nem: ott a számlán közölt egyenleg a két tarifáé együtt.
    egy_fiz, egy_hol, egy_utolso = ({}, {}, None) if tobb or len(kozos) > 1 else _egyenleg_befizetesek(szamlak, fizetesek)
    # Tarifánkénti (külön) kivonatnál a közös MVM-folyószámla többi fiókjának mínuszos fizetendői: ha egy saját számla
    # „egyéb” sora ilyet hoz át, az átvezetés (a másik tarifa jóváírása itt számítódik be).
    szimulalt = not egyutt and len(kozos) == 2
    # Tarifánkénti módban a közös folyószámla másik fiókjának mínuszos fizetendői is áthozhatók (pl. „Kötbér” néven).
    csoport_neg = [] if egyutt else [(x.get("kelte") or "", kk, _dec(x.get("osszeg"))) for s in kozos if s != sid
                                     for kk, x in haztartas[s][1].items() if (_dec(x.get("osszeg")) or Decimal(0)) < 0]
    masik = [] if egyutt or szimulalt else [(x.get("kelte") or "", haztartas[s][0], kk, _dec(x.get("osszeg")))
                                            for s in kozos if s != sid for kk, x in haztartas[s][1].items()
                                            if (_dec(x.get("osszeg")) or Decimal(0)) < 0]
    sztornozott = sztornozottak(x for _, x, *_ in szamlak)
    # A stornó kelte a sztornózott számlánként: a stornó ELŐTT kifizetett eredeti befizetése valódi pénz (a szolgáltató
    # túlfizetésként viszi tovább, pl. az újra kiállított számlán „túlfizetés miatt levont”) – az számít.
    storno_kelte = {str(x["sztornozott"]).lstrip("0"): x.get("kelte") or "" for _, x, *_ in szamlak
                    if x.get("tipus") == "storno" and x.get("sztornozott")}
    fedezett: set[str] = set()  # a folyószámla jóváírásából rendezett számlák (nincs befizetés)
    for i, (k, x, fnev, egyseg) in enumerate(szamlak):
        kelte = x.get("kelte") or ""
        tip = x.get("tipus") or "egyeb"
        e = ertek(x)  # stornónál mínusz: a sztornózott számla jóváírása
        tetelek.append({
            "datum": kelte, "fajta": "szamla", "sorszam": k, "tipus": tip, "idoszak": x.get("idoszak"),
            "mennyiseg": mennyiseg(x), "fiok": fnev if tobb else None, "allasok": oraallas(x, egyseg),
            "megnevezes": f"{TIPUS_NEV.get(tip, 'Számla')} {k}" + (" (kézi)" if x.get("kezi") else "")
            + (f" – a(z) {x['sztornozott']} számla stornója" if tip == "storno" and x.get("sztornozott") else ""),
            "kovetel": float(e) if e > 0 else 0.0, "tartozik": float(-e) if e < 0 else 0.0, "hatarido": x.get("hatarido"), "megjegyzes": x.get("javitas_megjegyzes"),
            "sztornozott": x.get("sztornozott") if tip == "storno" else None,
            "szolgaltato_egyenleg": float(_dec(x["folyoszamla"])) if _dec(x.get("folyoszamla")) is not None else None,
        })
        athozott = Decimal(0)
        for tnev, o in x.get("egyeb_tetelek") or []:
            o = _dec(o)
            if not o:
                continue
            # Az MVM néha „kötbér” néven hozza át egy korábbi számla mínuszos fizetendőjét: ha az összeg egy korábbi
            # mínuszos fizetendővel egyezik, áthozott egyenleg.
            atvitt = next((n for n in negativ if _kozel(n, o)), None) if o < 0 else None
            if atvitt is None and szimulalt and o < 0:
                cs = next((c for c in csoport_neg if c[2] is not None and _kozel(c[2], o) and c[0] <= kelte), None)
                if cs is not None:
                    csoport_neg.remove(cs)
                    athozott += o
                    continue
            honnan = None if atvitt is not None or o >= 0 else next(
                (m for m in masik if m[3] is not None and _kozel(m[3], o) and m[0] <= kelte), None)
            if atvitt is not None:
                negativ.remove(atvitt)
                athozott += o
            elif honnan is not None:
                masik.remove(honnan)
                tetelek.append({"datum": kelte, "fajta": "egyeb", "sorszam": k, "fiok": None,
                                "megnevezes": f"Átvezetés: a(z) {honnan[1]} {honnan[2]} számla jóváírása itt beszámítva",
                                "kovetel": 0.0, "tartozik": float(-o)})
            elif any(m in tnev.lower() for m in ATHOZOTT_NEVEK + ATVEZETES_NEVEK):
                athozott += o
            else:  # új mozgás: kötbér, késedelmi kamat, támogatás (jóváírás) …
                tetelek.append({"datum": kelte, "fajta": "egyeb", "sorszam": k, "megnevezes": tnev, "fiok": fnev if tobb else None,
                                "kovetel": float(o) if o > 0 else 0.0, "tartozik": float(-o) if o < 0 else 0.0})
        if i == 0 and athozott:
            nyito = {"datum": (date.fromisoformat(kelte) - timedelta(days=1)).isoformat(), "osszeg": float(athozott),
                     "forras": f"a(z) {k} számlán áthozott egyenleg szerint"}
        # Befizetés: a számla fizetendője (közös folyószámlánál a teljes esedékes összeg).
        f = fizetesek.get(k) or {}
        fiz = _dec(x.get("osszeg"))
        if fiz is not None and fiz < 0:
            negativ.append(fiz)
        if fiz is None or fiz <= 0 or tip == "storno":
            continue
        if k in sztornozott and not (f.get("fizetve") and f.get("datum") and f["datum"] < storno_kelte.get(str(k).lstrip("0"), "")):
            continue  # a sztornózott, nem (vagy csak a stornó után, beszámítással) „fizetett” számla nem befizetés
        if f.get("nincs_fizetendo") and f.get("forras") != "kezi" and not f.get("fizetve"):
            fedezett.add(k)
            continue  # a számla fizetendője a közös folyószámla túlfizetéséből rendezett (pl. 991 Ft-os részszámla, −47 138 Ft fizetendő)
        if not _osszeg_adat(f) and egy_utolso and kelte < egy_utolso:
            # A szolgáltató egyenlegéből: a befizetett összeg (a jóváírással fedezett rész nélkül); kézi jelölésnél a
            # fizetés napja a jelölésé.
            b = egy_fiz.get(k)
            kezi_ = f.get("forras") == "kezi" and f.get("fizetve")
            if f.get("forras") == "kezi" and not f.get("fizetve"):
                continue  # kézzel „nincs fizetve”
            if b and b["osszeg"] > 0:
                tetelek.append({"datum": (f.get("datum") or b["datum"]) if kezi_ else b["datum"], "fajta": "befizetes", "sorszam": k,
                                "forras": "kezi" if kezi_ else "egyenleg", "fiok": None,
                                "megnevezes": f"Befizetés – {k}" + ("" if kezi_ else f" ({FIZETES_NEV['egyenleg']})"), "kovetel": 0.0,
                                "tartozik": float(b["osszeg"])})
            continue
        nap, forras = _befizetes(x, f, ma)
        if nap:
            tetelek.append({"datum": nap, "fajta": "befizetes", "sorszam": k, "forras": forras, "fiok": fnev if tobb else None,
                            "megnevezes": f"Befizetés – {k}" + (f" ({FIZETES_NEV[forras]})" if FIZETES_NEV.get(forras) else ""),
                            "kovetel": 0.0, "tartozik": float(fiz)})

    if szimulalt:
        tetelek += _kozos_atvezetesek(sid, kozos, haztartas, fizetesek, ma)
    for t in kezi_tetelek or []:
        tetelek.append({"datum": t["datum"], "fajta": "kezi", "id": t["id"], "megnevezes": t.get("megnevezes") or "Kézi tétel",
                        "kovetel": float(t.get("kovetel") or 0), "tartozik": float(t.get("tartozik") or 0), "fiok": None})
    if nyito_kezi and nyito_kezi.get("osszeg") is not None:
        nyito = {"datum": nyito_kezi.get("datum"), "osszeg": float(nyito_kezi["osszeg"]), "forras": "kézzel megadva"}
    if nyito is None:
        nyito = {"datum": (date.fromisoformat(szamlak[0][1]["kelte"]) - timedelta(days=1)).isoformat() if szamlak else ma.isoformat(),
                 "osszeg": 0.0, "forras": "nincs adat az első számla előtti egyenlegről"}
    rend = {"szamla": 0, "egyeb": 1, "kezi": 2, "befizetes": 3}
    tetelek.sort(key=lambda t: (t["datum"], rend[t["fajta"]]))
    egyenleg = Decimal(str(nyito["osszeg"]))
    for t in tetelek:
        egyenleg += Decimal(str(t["kovetel"])) - Decimal(str(t["tartozik"]))
        t["egyenleg"] = float(egyenleg)
    # A számlán közölt folyószámla-egyenleg (MVM) a nap végi egyenleggel vethető össze (egy napon több számla is jöhet).
    nap_vege = {t["datum"]: t["egyenleg"] for t in tetelek if t["fajta"] != "befizetes"}
    utolso = {t["datum"]: i for i, t in enumerate(tetelek) if t.get("szolgaltato_egyenleg") is not None}
    for i, t in enumerate(tetelek):
        if t.get("szolgaltato_egyenleg") is not None:
            # Az eltérés a nap utolsó, egyenleget közlő számláján jelenik meg (egy napon több számla is jöhet).
            t["elteres"] = round(nap_vege[t["datum"]] - t["szolgaltato_egyenleg"]) if utolso[t["datum"]] == i else 0
            if t["elteres"]:
                # Könyvelési csúszás: a szolgáltató a befizetést néhány nap késéssel könyveli (vagy a nálunk rögzített nap
                # későbbi a valódinál). Ha az eltérés pontosan a számla előtti / utáni KONYVELESI_NAP nap befizetéseinek
                # összege, nem valódi eltérés.
                nap = date.fromisoformat(t["datum"])
                elott = sum(x["tartozik"] for x in tetelek if x["fajta"] == "befizetes"
                            and nap - timedelta(days=KONYVELESI_NAP) < date.fromisoformat(x["datum"]) <= nap)
                utan = sum(x["tartozik"] for x in tetelek if x["fajta"] == "befizetes"
                           and nap < date.fromisoformat(x["datum"]) <= nap + timedelta(days=KONYVELESI_NAP))
                if elott and abs(t["elteres"] + elott) < 1:
                    t["konyveles"] = {"irany": "meg_nem_konyvelt", "osszeg": elott}
                    t["elteres"] = 0
                elif utan and abs(t["elteres"] - utan) < 1:
                    t["konyveles"] = {"irany": "korabban_erkezett", "osszeg": utan}
                    t["elteres"] = 0
    kiegyenlites(tetelek)
    if not egyutt and len(kozos) > 1:
        # A számlán közölt folyószámla-egyenleg a közös (több tarifás) egyenleg – egy tarifa kivonatával nem vethető össze.
        for t in tetelek:
            t.pop("elteres", None)
    return {"nev": " + ".join(haztartas[s][0] for s in csoport), "fiokok": csoport, "kozos": tobb,
            "kozos_fiokok": [haztartas[s][0] for s in kozos if s != sid] if not egyutt else [],
            "nyito": nyito, "tetelek": tetelek, "zaro": float(egyenleg),
            "teljesites": teljesites(szamlak, tetelek, ma, [(kk, x, haztartas[s][0]) for s in kozos for kk, x in haztartas[s][1].items()],
                                     {kk for kk in egy_fiz} | fedezett, egy_hol, sztornozott)}


ALLAPOT_NEV = {"fizetve": "fizetve", "nyitott": "nyitott", "lejart": "lejárt", "tulfizetes": "túlfizetés",
               "beszamitva": "beszámítva", "nincs": "nincs fizetendő", "storno": "sztornó",
               "sztornozva": "sztornózva"}


def teljesites(szamlak: list[tuple], tetelek: list[dict[str, Any]], ma: date, kozos_szamlak: list[tuple] | None = None,
               rendezve: set[str] | None = None, beszamitas_hol: dict[str, str] | None = None,
               sztornozott: set[str] | None = None) -> dict[str, Any]:
    """A számlák pénzügyi teljesítése: soronként egy számla a fizetendőjével és a befizetésével, állapottal; összesítő.
    A fizetendő a szolgáltató szerinti (a beszámításokkal együtt), ezért közvetlenül a befizetéssel vethető össze.
    rendezve / beszamitas_hol: a szolgáltató egyenlegéből visszafejtve rendezett számlák, ill. a jóváírások helye."""
    befiz = {t["sorszam"]: t for t in tetelek if t["fajta"] == "befizetes"}
    # Mínuszos fizetendő beszámítása egy későbbi számlán (egyéb tételként, azonos összeggel).
    kesobbi = [(x.get("kelte") or "", k if fn == szamlak[0][2] else f"{fn} {k}", _dec(o))
               for k, x, fn in (kozos_szamlak or [(k, x, fn) for k, x, fn, *_ in szamlak]) for _, o in x.get("egyeb_tetelek") or []] if szamlak else []
    sorok, ossz = [], {"szamlazva": 0.0, "fizetve": 0.0, "nyitott": 0.0, "lejart": 0.0, "tulfizetes": 0.0}
    for k, x, fnev, egyseg in szamlak:
        fiz = _dec(x.get("osszeg"))
        tip = x.get("tipus") or "egyeb"
        b = befiz.get(k)
        hat = x.get("hatarido")
        if tip == "storno":
            allapot = "storno"
        elif k in (sztornozott or ()):
            allapot = "sztornozva"
        elif fiz is not None and fiz < 0:
            hol = (beszamitas_hol or {}).get(k) or next(
                (kk for kel, kk, o in kesobbi if o is not None and _kozel(o, fiz) and kel >= (x.get("kelte") or "") and kk != k), None)
            if not hol:
                # Részletekben beszámítva: a következő számlák mínuszos beszámításai együtt (pl. MVM gáz: −14 482 Ft
                # jóváírásból 11 165 az első, 3 317 a második részszámlán).
                gyujt, hol_ = Decimal(0), []
                for kel, kk, o in sorted(kesobbi):
                    if o is None or o >= 0 or kk == k or kel < (x.get("kelte") or ""):
                        continue
                    gyujt += o
                    hol_.append(kk)
                    if gyujt <= fiz + TURES:
                        break
                if len(hol_) > 1 and _kozel(gyujt, fiz):
                    hol = ", ".join(hol_)
            allapot = "beszamitva" if hol else "tulfizetes"
        elif not fiz:
            allapot = "nincs"
        elif b or k in (rendezve or ()):
            allapot = "fizetve"
        else:
            allapot = "lejart" if hat and hat < ma.isoformat() else "nyitott"
        sor = {
            "sorszam": k, "kelte": x.get("kelte"), "tipus": tip, "megnevezes": f"{TIPUS_NEV.get(tip, 'Számla')} {k}" + (" (kézi)" if x.get("kezi") else ""),
            "fiok": fnev, "idoszak": x.get("idoszak"), "mennyiseg": mennyiseg(x), "allasok": oraallas(x, egyseg), "hatarido": hat,
            "fizetendo": float(fiz) if fiz is not None else None, "szamlaertek": float(_dec(x.get("szamlaertek"))) if _dec(x.get("szamlaertek")) is not None else None,
            "fizetve": {"datum": b["datum"], "osszeg": b["tartozik"], "forras": b.get("forras")} if b else None,
            "allapot": allapot, "allapot_nev": ALLAPOT_NEV[allapot],
            "beszamitva": hol if allapot == "beszamitva" else None,
        }
        sorok.append(sor)
        if fiz and fiz > 0 and tip != "storno" and allapot != "sztornozva":
            ossz["szamlazva"] += float(fiz)
            if b:
                ossz["fizetve"] += b["tartozik"]
            elif k in (rendezve or ()):
                pass  # a jóváírás fedezte
            else:
                ossz["nyitott"] += float(fiz)
                if allapot == "lejart":
                    ossz["lejart"] += float(fiz)
    # Túlfizetés: a legutóbbi, még be nem számított mínuszos fizetendő.
    nyitott_tulf = [s for s in sorok if s["allapot"] == "tulfizetes"]
    if nyitott_tulf:
        ossz["tulfizetes"] = -nyitott_tulf[-1]["fizetendo"]
    return {"sorok": sorok, "osszesen": ossz}
