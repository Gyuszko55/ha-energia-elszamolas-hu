"""A beállításokból és a tárolt adatokból motor-objektumok (Fiok, Szamlalo) építése."""

from __future__ import annotations

import re
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from .const import (
        CONF_DIKT_ABLAK,
        CONF_FORRAS,
        CONF_H_NYARI,
        CONF_H_TELI,
        CONF_A2_CSUCS,
        CONF_A2_VOLGY,
        CONF_ALMERO,
        CONF_ALMERO_BEEPITVE,
        CONF_ALMERO_KEZDO,
        CONF_BEEPITVE,
        CONF_CSATORNADIJ,
        CONF_DIJSZABAS,
        CONF_DIJSZABAS_TOL,
        CONF_GYARI_SZAM,
        CONF_KERET_AKTIV,
        CONF_KEZDO_ALLAS,
        CONF_KOZMU,
        CONF_SZOLGALTATO,
    )
    from .motor.tipusok import (
        Csatorna,
        DijszabasHozzarendeles,
        Feluliras,
        Fiok,
        Kozmu,
        Leolvasas,
        LeolvasasTipus,
        Mero,
    )
    from .gaz_atalany import havi_mj
except ImportError:  # tesztek: a csomag HA nélkül, közvetlenül
    from const import (
        CONF_DIKT_ABLAK,
        CONF_FORRAS,
        CONF_H_NYARI,
        CONF_H_TELI,
        CONF_A2_CSUCS,
        CONF_A2_VOLGY,
        CONF_ALMERO,
        CONF_ALMERO_BEEPITVE,
        CONF_ALMERO_KEZDO,
        CONF_BEEPITVE,
        CONF_CSATORNADIJ,
        CONF_DIJSZABAS,
        CONF_DIJSZABAS_TOL,
        CONF_GYARI_SZAM,
        CONF_KERET_AKTIV,
        CONF_KEZDO_ALLAS,
        CONF_KOZMU,
        CONF_SZOLGALTATO,
    )
    from motor.tipusok import (
        Csatorna,
        DijszabasHozzarendeles,
        Feluliras,
        Fiok,
        Kozmu,
        Leolvasas,
        LeolvasasTipus,
        Mero,
    )
    from gaz_atalany import havi_mj


def d(x: Any) -> date | None:
    if x is None or x == "":
        return None
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def dec(x: Any) -> Decimal | None:
    return None if x is None or x == "" else Decimal(str(x))


def szenzor_ertek(allapot: Any) -> Decimal | None:
    """Egy szenzor állapota számként; „unavailable”, „unknown”, üres, valamint „nan”/„inf” (nem véges) esetén None –
    a NaN különben csendben végigfutna a számoláson, vagy egy összehasonlításnál InvalidOperation-t dobna."""
    try:
        ertek = Decimal(str(allapot).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return ertek if ertek.is_finite() else None


FORRAS_PROBAK = 10  # ennyiszer próbáljuk percenként a hiányzó forrás-szenzort (kb. az indulás utáni 10 perc)


def frissitesi_perc(hianyzik: bool, probak: int, normal: int) -> int:
    """A következő frissítésig hátralévő percek: hiányzó forrásnál az első FORRAS_PROBAK alkalommal percenként
    (induláskor a szenzor hamarosan megjön), utána a szokásos ütemben – különben egy végleg hiányzó szenzor miatt
    percenként futna a teljes újraszámolás (csatornánként ≥366 napnyi statisztikával)."""
    return 1 if hianyzik and probak <= FORRAS_PROBAK else normal


def kezdopont(
    beallitas: dict[str, Any], cel: date, stat_ertek: Decimal | None, aktualis: Decimal | None, ma: date
) -> tuple[date, Decimal, str] | None:
    """Az első mérő kezdőnapja, kezdőállása és forrása (új fióknál, vagy ha a kezdőállást kiürítették).

    Sorrend: a kézzel megadott kezdőállás mindig nyer → a szenzor HA-statisztikája a kezdőnapra (ha a kezdőnap
    üres: a folyó időszak elejére) → a szenzor mostani értéke a mai nappal („a követés ma indul”) → None
    (a szenzor még nem kész; később újra próbáljuk). Mesterséges 0 óraállást csak szenzor nélkül veszünk fel,
    ott a leolvasások úgyis felülírják. cel: a kezdőnap, ill. üres kezdőnapnál a folyó időszak eleje.
    """
    allas = beallitas.get(CONF_KEZDO_ALLAS)
    if allas not in (None, ""):
        return d(beallitas.get(CONF_BEEPITVE)) or ma, Decimal(str(allas)), "megadott"
    if not beallitas.get(CONF_FORRAS):
        return d(beallitas.get(CONF_BEEPITVE)) or ma, Decimal(0), "nincs_forras"
    if stat_ertek is not None:
        return cel, stat_ertek, "statisztika"
    if aktualis is not None:
        return ma, aktualis, "aktualis"
    return None


def kezdo_mero(beallitas: dict[str, Any], beepitve: date | None = None, kezdo_allas: Decimal | None = None) -> dict[str, Any]:
    """Az első mérő a fiók beállításából (új fióknál); a kezdőnap/-állás felülírható (automatikus kezdőpont)."""
    return {
        "gyari_szam": beallitas.get(CONF_GYARI_SZAM) or "",
        "beepitve": str(beepitve or beallitas[CONF_BEEPITVE]),
        "kezdo_allas": str(kezdo_allas if kezdo_allas is not None else beallitas.get(CONF_KEZDO_ALLAS) or 0),
        "kiszerelve": None,
        "zaro_allas": None,
        "leolvasasok": [],
    }


def _ures_vagy(x: Any, szam: bool = False) -> str:
    """Beállítás-érték a szinkron-ujjlenyomatba: üres → "", szám → a korábbi formában (str(x or 0))."""
    if x in (None, ""):
        return ""
    return str(x or 0) if szam else str(x)


def mero_szinkron(tarolt: dict[str, Any], beallitas: dict[str, Any]) -> bool:
    """A fiók szerkesztésekor módosított mérőadatok (kezdőnap, kezdőállás, gyári szám) átvezetése a tárolt mérőre.

    Csak ha a fióknak egyetlen mérője van (mérőcsere után a csere szolgáltatás kezeli). Az első futáskor csak
    feljegyzi a beállítást – a korábbi (pl. v1-ből átvett) mérőadatokat nem írja felül. Igaz, ha változott.
    """
    valtozott = False
    for kulcs, lista, uj in (
        ("mero_beallitas", tarolt.get("merok") or [], {
            "beepitve": _ures_vagy(beallitas.get(CONF_BEEPITVE)), "kezdo_allas": _ures_vagy(beallitas.get(CONF_KEZDO_ALLAS), szam=True),
            "gyari_szam": str(beallitas.get(CONF_GYARI_SZAM) or ""),
        }),
        ("almero_beallitas", tarolt.get("almero_merok") or [], {
            "beepitve": str(beallitas.get(CONF_ALMERO_BEEPITVE) or beallitas.get(CONF_BEEPITVE)),
            "kezdo_allas": str(beallitas.get(CONF_ALMERO_KEZDO) or 0), "gyari_szam": "",
        }),
    ):
        if not lista:
            continue
        elozo = tarolt.get(kulcs)
        if elozo is not None and elozo != uj and len(lista) == 1:
            m = lista[0]
            if kulcs == "mero_beallitas" and (elozo.get("beepitve") != uj["beepitve"] or elozo.get("kezdo_allas") != uj["kezdo_allas"]):
                # Módosított kezdőnap/kezdőállás: a lezárt időszakokat a korábbi napról újraszámoljuk (koordinátor).
                napok = [x for x in (d(elozo.get("beepitve")), d(uj["beepitve"]), d(m.get("beepitve"))) if x]
                if napok:
                    tarolt["lezart_ujra"] = min(napok).isoformat()
            # Üres (automatikus) mező nem írja felül a tárolt értéket; ha a kezdőállást most ürítették ki,
            # a koordinátor újra meghatározza (kezdes_ujra).
            if uj["beepitve"]:
                m["beepitve"] = uj["beepitve"]
            if uj["kezdo_allas"]:
                m["kezdo_allas"] = uj["kezdo_allas"]
                if kulcs == "mero_beallitas":
                    tarolt.pop("kezdes", None)
            elif kulcs == "mero_beallitas" and elozo.get("kezdo_allas"):
                tarolt["kezdes_ujra"] = True
            if uj["gyari_szam"]:
                m["gyari_szam"] = uj["gyari_szam"]
        if elozo != uj:
            tarolt[kulcs] = uj
            valtozott = True
    return valtozott


def kezdo_origo_szinkron(tarolt: dict[str, Any], beallitas: dict[str, Any]) -> bool:
    """A fiók létrehozásakor vagy módosításakor megadott kezdő óraállás (a kezdőnapon) az elszámolások origója: éves
    elszámoló leolvasásként számít (évkezdet, „Ha ma lenne az elszámolás” kezdete), amíg egy későbbi éves leolvasás
    át nem veszi a helyét; a panel mérőállásai között „Kezdő óraállás” bejegyzésként látszik. Üresen hagyott
    (automatikus) kezdőállás nem origó. Igaz, ha változott."""
    allas = beallitas.get(CONF_KEZDO_ALLAS)
    nap = beallitas.get(CONF_BEEPITVE) or (tarolt["merok"][0]["beepitve"] if tarolt.get("merok") else None)
    uj = {"datum": str(nap)[:10], "allas": str(Decimal(str(allas)))} if allas not in (None, "") and nap else None
    if tarolt.get("kezdo_origo") == uj:
        return False
    if uj is None:
        tarolt.pop("kezdo_origo", None)
    else:
        tarolt["kezdo_origo"] = uj
    return True


def kezdo_almero(beallitas: dict[str, Any], fo_beepitve: str | None = None) -> dict[str, Any]:
    """Víz: a locsolási almérő első mérője a fiók beállításából."""
    return {
        "gyari_szam": "",
        "beepitve": str(beallitas.get(CONF_ALMERO_BEEPITVE) or beallitas.get(CONF_BEEPITVE) or fo_beepitve),
        "kezdo_allas": str(beallitas.get(CONF_ALMERO_KEZDO) or 0),
        "kiszerelve": None,
        "zaro_allas": None,
        "leolvasasok": [],
    }


def mero_motorba(m: dict[str, Any], csatorna: str = "vetelezes", honapvege: bool = False) -> Mero:
    """Egy mérő egy regisztere (csatornája): vételezés (1.8.0) vagy betáplálás (2.8.0).

    honapvege: naptári havi fióknál a hónap utolsó napjára rögzített saját (kézi, diktált) állás a nap VÉGÉT jelenti –
    a hónap zárása –, ezért a következő nap elejére kerül (a számlálóban a leolvasás a nap elején áll)."""
    fo = csatorna == "vetelezes"

    def nap(lo: dict[str, Any]) -> date:
        x = d(lo["datum"])
        if lo.get("ido"):
            return x  # időponttal rögzített állás: pontosan ott áll, nem kell a nap végére tolni
        # Csak a saját (kézi, diktált) állás: a számlából átvett szolgáltatói állás a számla szerinti napra szól.
        if (honapvege and lo.get("tipus", "kezi") == "kezi" and "számlá" not in str(lo.get("megjegyzes", "")).lower().replace("számla ", "számlá")
                and (x + timedelta(days=1)).day == 1):
            return x + timedelta(days=1)
        return x

    kezdo = dec(m.get("kezdo_allas" if fo else f"kezdo_{csatorna}"))
    if kezdo is None and not fo:
        # Mellékregiszter (betáplálás, H téli/nyári, zóna) kezdőállása a varázslóban nem adható meg: a legkorábbi
        # leolvasása – különben a 0-s kezdőpont a beépítés napján a teljes óraállást fogyasztásnak venné.
        sajat = [lo for lo in m.get("leolvasasok", []) if lo.get("csatorna", "vetelezes") == csatorna]
        if sajat:
            kezdo = dec(min(sajat, key=lambda lo: lo["datum"])["allas"])
    return Mero(
        gyari_szam=m.get("gyari_szam", ""),
        beepitve=d(m["beepitve"]),
        kezdo_allas=kezdo or Decimal(0),
        kiszerelve=d(m.get("kiszerelve")),
        zaro_allas=dec(m.get("zaro_allas" if fo else f"zaro_{csatorna}")),
        leolvasasok=[
            Leolvasas(
                datum=nap(lo),
                allas=dec(lo["allas"]),
                tipus=LeolvasasTipus(lo.get("tipus", "kezi")),
                elszamolasi=bool(lo.get("elszamolasi")),
                megjegyzes=lo.get("megjegyzes", ""),
                ido=time.fromisoformat(lo["ido"]) if lo.get("ido") else None,
            )
            for lo in m.get("leolvasasok", [])
            if lo.get("csatorna", "vetelezes") == csatorna
        ],
    )


EVES_MIN_NAP = 300  # két éves elszámoló leolvasás között legalább ennyi nap (~10 hónap)
EVES_TURES_NAP = 31  # egy elszámolási év legfeljebb 12 hónap + ennyi nap (a leolvasás napja évről évre csúszhat)


def _ev_mulva(nap: date) -> date:
    """Egy évvel később (febr. 29. → febr. 28.)."""
    try:
        return nap.replace(year=nap.year + 1)
    except ValueError:
        return nap.replace(year=nap.year + 1, day=28)


def _eves_napok(tarolt: dict[str, Any]) -> list[date]:
    """Az éves elszámoló leolvasások napjai. A jelölt (elszámolási) leolvasások közül a legutóbbitól visszafelé csak
    azok, amelyek legalább ~10 hónappal az utána következő előtt vannak – egy évközi végszámla, sztornó vagy
    szerződésváltás „Leol” állása így nem lesz évkezdet."""
    # Kényszerített évkezdet (pl. MVM végszámla után új szerződéses év): a 10 hónapos szabálytól függetlenül.
    kenyszer = {d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("evkezdet")}
    napok = {d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("elszamolasi")} - kenyszer
    if origo := tarolt.get("kezdo_origo"):
        # A fiókban megadott kezdő óraállás (pl. a mérő felszerelése – előtte nincs mérés): az elszámolások origója,
        # mindig évkezdet (a 10 hónapos szabálytól függetlenül).
        kenyszer.add(d(origo["datum"]))
    napok = sorted(napok, reverse=True)
    out: list[date] = []
    for x in napok:
        if not out or (out[-1] - x).days >= EVES_MIN_NAP:
            out.append(x)
    valodi = sorted(set(out) | kenyszer)
    # Az elszámolási év legfeljebb 12 hónap (+ tűrés): ha egy éves leolvasás kimaradt (vagy még nincs rögzítve), az
    # évfordulón virtuális évhatár – így a keret nem csúszhat át a következő évbe.
    teljes: list[date] = []
    for x, y in zip(valodi, valodi[1:] + [date.today() + timedelta(days=1)]):
        teljes.append(x)
        k = _ev_mulva(x)
        while (y - k).days > EVES_TURES_NAP:
            teljes.append(k)
            k = _ev_mulva(k)
    return teljes


def eves_bazis(tarolt: dict[str, Any]) -> date | None:
    """Az utolsó elszámoló (éves) leolvasás napja; ha nincs, az első mérő beépítése."""
    napok = _eves_napok(tarolt)
    if napok:
        return napok[-1]
    if not tarolt["merok"]:
        return None
    # Éves leolvasás nélkül az első mérő beépítése – de az elszámolási év legfeljebb 12 hónap (+ tűrés): évfordulónként.
    b = d(tarolt["merok"][0]["beepitve"])
    while (date.today() - _ev_mulva(b)).days > EVES_TURES_NAP:
        b = _ev_mulva(b)
    return b


def elszamolasi_napok(tarolt: dict[str, Any]) -> set[date]:
    return set(_eves_napok(tarolt))


def diktalasi_hatarok(tarolt: dict[str, Any], minden_leolvasas: bool = False) -> list[date]:
    """Diktálásos/átalányos villanyfiók időszakhatárai: maga a DIKTÁLÁS NAPJA (a leolvasás a nap elején áll a
    számlálóban, így a két diktált állás pontosan az időszak két végén van; a számlán ez „előző diktálás
    másnapja – diktálás napja”).

    Határ: a számlákból jött mérőállások, a számlák elszámolt időszakának vége (és kezdete, ha nem egy előző
    időszak vége után következik), és a „diktáltam” jelölésű saját leolvasások. Egy ellenőrzésre rögzített
    saját leolvasás nem határ.

    minden_leolvasas (tiszta diktálás): MINDEN mérőállás határ (a mérő kezdőállása és a fiók kezdő óraállása is), a
    számlák időszaka viszont nem – a lezárt időszak két leolvasás között tart, ami a számlától eltérhet.
    """
    egy_nap = timedelta(days=1)
    hatarok: set[date] = set()
    if minden_leolvasas:
        for m in tarolt.get("merok") or []:
            hatarok.add(d(m["beepitve"]))
            # A korrekciós leolvasás (csak a szenzor igazítása) nem időszakhatár.
            hatarok |= {d(lo["datum"]) for lo in m.get("leolvasasok", [])
                        if (lo.get("csatorna") or "vetelezes") == "vetelezes" and not lo.get("korrekcio")}
        if origo := tarolt.get("kezdo_origo"):
            hatarok.add(d(origo["datum"]))
        return sorted(hatarok)
    for m in tarolt.get("merok") or []:
        for lo in m.get("leolvasasok", []):
            if (lo.get("csatorna") or "vetelezes") != "vetelezes":
                continue
            if lo.get("diktalt") or lo.get("elszamolasi") or str(lo.get("megjegyzes", "")).startswith("számla "):
                hatarok.add(d(lo["datum"]))
    idoszakok = [
        (d(x["idoszak"][0]), d(x["idoszak"][1]))
        for x in (tarolt.get("szamlak") or {}).values() if x.get("idoszak") and x.get("tipus") != "storno"
    ]
    hatarok |= {v for _, v in idoszakok}
    hatarok |= {k for k, _ in idoszakok if k - egy_nap not in hatarok}  # az első időszak kezdete
    return sorted(hatarok)


def diktalasi_ablak(tarolt: dict[str, Any], beall: dict[str, Any] | None = None) -> tuple[int, int] | None:
    """A legutóbbi számlán szereplő diktálási ablak (pl. minden hónap 8–14.); számla híján a fiókban megadott
    („8-14”) – új fióknál, az első számla előtt."""
    ablakok = [(x["kelte"], x["diktalasi_ablak"]) for x in (tarolt.get("szamlak") or {}).values() if x.get("diktalasi_ablak")]
    if not ablakok:
        return megadott_diktalasi_ablak(beall)
    _, (eleje, vege) = max(ablakok)
    return int(eleje), int(vege)


def megadott_diktalasi_ablak(beall: dict[str, Any] | None) -> tuple[int, int] | None:
    """A fiókban megadott diktálási ablak („8-14”, „8–14”, „8 - 14.”) – érvénytelen értéknél None."""
    m = re.fullmatch(r"\s*(\d{1,2})\.?\s*[-–—]\s*(\d{1,2})\.?\s*", str((beall or {}).get(CONF_DIKT_ABLAK) or ""))
    if not m:
        return None
    eleje, vege = int(m[1]), int(m[2])
    return (eleje, vege) if 1 <= eleje <= vege <= 31 else None


def utem_szerinti_diktalas(utolso_vege: date, periodus: int, ablak: tuple[int, int], ma: date, mod: str = "utana") -> tuple[date, date]:
    """Több havonta számlázó szolgáltató: a legközelebbi, még el nem múlt diktálási ablak. utolso_vege: a legutóbbi
    számla időszakának utolsó napja. mod (a díjszabás „diktalas.honap” szabálya):
    - „utana”: az elszámolási időszak vége utáni hónapban (pl. ALFÖLDVÍZ, négyhavonta, 10–15.);
    - „zaro”: az időszak utolsó hónapjában, a számla zárása előtt (pl. DAKÖV, kéthavonta, 20–25.)."""
    import calendar  # noqa: PLC0415

    def elore(ev: int, ho: int, n: int) -> tuple[int, int]:
        k = ev * 12 + ho - 1 + n
        return k // 12, k % 12 + 1

    ev, ho = utolso_vege.year, utolso_vege.month  # egy időszak záró hónapja
    while True:
        ev, ho = elore(ev, ho, periodus) if mod == "zaro" else elore(ev, ho, 1)
        utolso = calendar.monthrange(ev, ho)[1]
        tol, ig = date(ev, ho, min(ablak[0], utolso)), date(ev, ho, min(ablak[1], utolso))
        if ig >= ma:
            return tol, ig
        if mod != "zaro":
            ev, ho = elore(ev, ho, periodus - 1)  # a következő időszak záró hónapja


def kovetkezo_idopont(tarolt: dict[str, Any], kulcs: str) -> tuple[date, date] | None:
    """A legutóbbi számlán közölt következő időpont (pl. DAKÖV: „kovetkezo_leolvasas”, „kovetkezo_diktalas”)."""
    jeloltek = [(x["kelte"], x[kulcs]) for x in (tarolt.get("szamlak") or {}).values() if x.get(kulcs)]
    if not jeloltek:
        return None
    _, (tol, ig) = max(jeloltek)
    return d(tol), d(ig)


def fiok_motorba(beallitas: dict[str, Any], tarolt: dict[str, Any]) -> Fiok:
    return Fiok(
        kozmu=Kozmu(beallitas[CONF_KOZMU]),
        szolgaltato=beallitas[CONF_SZOLGALTATO],
        dijszabasok=[DijszabasHozzarendeles(beallitas[CONF_DIJSZABAS], d(beallitas[CONF_DIJSZABAS_TOL]))],
        csatornak=h_regiszterek(beallitas, tarolt) or zona_regiszterek(beallitas, tarolt) or [
            Csatorna(
                merok=[mero_motorba(m, honapvege=honapvegi_zaras(beallitas)) for m in tarolt["merok"]],
                keret_aktiv=bool(beallitas.get(CONF_KERET_AKTIV, True)),
                csatornadij_aktiv=bool(beallitas.get(CONF_CSATORNADIJ, True)),
            ),
            *(
                [
                    Csatorna(
                        szerep="almero",
                        merok=[mero_motorba(m) for m in tarolt.get("almero_merok", [])],
                        keret_aktiv=False,
                        csatornadij_aktiv=False,
                        levonas_fobol=True,
                    )
                ]
                if beallitas.get(CONF_ALMERO) and tarolt.get("almero_merok")
                else []
            ),
        ],
        feluliras=[
            Feluliras(f["kulcs"], Decimal(str(f["ertek"])), d(f["ervenyes_tol"])) for f in tarolt.get("feluliras", [])
        ],
        eves_bazis=eves_bazis(tarolt),
        reszszamlas=reszszamlas_mod(beallitas),
        keret_szorzo=keret_szorzo(beallitas),
        szorzok=szorzok(beallitas),
        elszamolasi_napok=tuple(sorted(elszamolasi_napok(tarolt))),
        futoertekek={k: Decimal(str(v)) for k, v in (tarolt.get("futoertekek") or {}).items()},
        korrekciok={k: Decimal(str(v)) for k, v in (tarolt.get("korrekciok") or {}).items()},
        **_szamlazasi_hatarok(beallitas, tarolt),
        szamla_honap=_egesz(beallitas.get("szamlazas_honap")),
        minimum_mentes=beallitas.get("hasznalat") == "nyaralo",
        szunetel=szunetel_idoszakok(beallitas),
    )


def szunetel_idoszakok(beallitas: dict[str, Any]) -> tuple[tuple[date, date | None], ...]:
    """A fiók szüneteltetett számlázása: „Szünetel ettől” (– „eddig”, kizárólagos napig; üresen: tart)."""
    tol = d(beallitas.get("szunetel_tol")) if beallitas.get("szunetel_tol") else None
    if tol is None:
        return ()
    ig = d(beallitas.get("szunetel_ig")) if beallitas.get("szunetel_ig") else None
    return ((tol, ig + timedelta(days=1) if ig else None),)


def _egesz(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def _szamlazasi_hatarok(beallitas: dict[str, Any], tarolt: dict[str, Any]) -> dict[str, Any]:
    """A keret kerekítési pontjai a fiók számlázási időszakai szerint (lásd Fiok.szamlazasi_hatarok)."""
    try:
        from .beallitas import idoszak_mod  # noqa: PLC0415
    except ImportError:  # tesztek: a csomag HA nélkül – a kerekítési pontokat a teszt adja meg
        return {}
    mod, _ = idoszak_mod(beallitas)
    if mod in ("diktalas", "leolvasas"):
        return {"szamlazasi_hatarok": tuple(diktalasi_hatarok(tarolt, mod == "leolvasas"))}
    return {"szamlazas_havi": mod == "naptari_honap"}


def reszszamlas_mod(beallitas: dict[str, Any]) -> bool:
    """Átalányos (egyenletes részszámlás) fiók-e – a beallitas.reszszamlas tükre (HA nélküli tesztekhez itt)."""
    if beallitas.get(CONF_KOZMU) == "villany" and beallitas.get("elszamolas_mod") in ("diktalas", "atalany", "tavleolvasas"):
        return beallitas.get("elszamolas_mod") == "atalany"
    return beallitas.get("fizetesi_mod") == "reszszamla"


def szorzok(beallitas: dict[str, Any]) -> dict[str, Decimal]:
    """A díjszabás „alapdij.szorzo”-jához a fiók adatai: gáz B1 – mérő-teljesítmény (m³/h); gáz mérő nélkül – a
    szobaszám és a tűzhely szerinti havi átalány (MJ)."""
    ds = beallitas.get(CONF_DIJSZABAS)
    if beallitas.get(CONF_KOZMU) == "tavho":  # távhő: légtérfogat (lm³) és havi hődíj-átalány (GJ)
        return {k: Decimal(str(beallitas[k])) for k in ("legterfogat", "futes_gj_ho") if beallitas.get(k) not in (None, "")}
    if ds == "gaz/lakossagi_b1" and beallitas.get("gazmero_teljesitmeny"):
        return {"gazmero_teljesitmeny": Decimal(str(beallitas["gazmero_teljesitmeny"]))}
    if ds == "gaz/mero_nelkuli":
        mj = havi_mj(beallitas.get("szobaszam"), beallitas.get("tuzhely"))
        return {"atalany_mj": mj} if mj is not None else {}
    return {}


def honapvegi_zaras(beallitas: dict[str, Any]) -> bool:
    """Naptári havi elszámolású fiók (gáz/víz naptári hónappal, villany távleolvasással): a hónap utolsó napjára
    rögzített saját állás a hónap zárása."""
    kozmu = beallitas.get(CONF_KOZMU)
    if kozmu == "villany":
        return beallitas.get("elszamolas_mod") == "tavleolvasas"
    return kozmu in ("gaz", "viz") and (beallitas.get("idoszak_mod") or "naptari_honap") == "naptari_honap"


def keret_szorzo(beallitas: dict[str, Any]) -> Decimal:
    """Gáz fogyasztói közösség (A3): társasház / lakásszövetkezet (lakásszám + 1) × 63 645 MJ, családi fogyasztói
    közösség lakásszám × 63 645 MJ. Más díjszabásnál 1."""
    if beallitas.get(CONF_DIJSZABAS) != "gaz/fogyasztoi_kozosseg" or not beallitas.get("lakasszam"):
        return Decimal(1)
    n = Decimal(int(beallitas["lakasszam"]))
    return n if beallitas.get("kozosseg_tipus") == "csaladi" else n + 1


def h_regiszter_mod(beallitas: dict[str, Any]) -> bool:
    return bool(beallitas.get(CONF_H_TELI) and beallitas.get(CONF_H_NYARI))


def h_regiszterek(beallitas: dict[str, Any], tarolt: dict[str, Any]) -> list[Csatorna] | None:
    """H-tarifa két regiszterrel: téli (1.81) és nyári (1.82) külön csatorna, külön mérés és elszámolás."""
    if not h_regiszter_mod(beallitas):
        return None
    return [
        Csatorna(szerep="h_teli", merok=[mero_motorba(m, "h_teli") for m in tarolt["merok"]], keret_aktiv=False),
        Csatorna(
            szerep="h_nyari",
            merok=[mero_motorba(m, "h_nyari") for m in tarolt["merok"]],
            keret_aktiv=bool(beallitas.get(CONF_KERET_AKTIV, True)),
        ),
    ]


def zona_regiszterek(beallitas: dict[str, Any], tarolt: dict[str, Any]) -> list[Csatorna] | None:
    """A2 kétzónás tarifa két regiszterrel: csúcs (1.8.1) és völgy (1.8.2) külön csatorna, saját árral, közös kerettel."""
    if beallitas.get(CONF_DIJSZABAS) != "villany/a2" or not (beallitas.get(CONF_A2_CSUCS) and beallitas.get(CONF_A2_VOLGY)):
        return None
    aktiv = bool(beallitas.get(CONF_KERET_AKTIV, True))
    return [
        Csatorna(szerep=sz, merok=[mero_motorba(m, sz) for m in tarolt["merok"]], keret_aktiv=aktiv)
        for sz in ("zona_csucs", "zona_volgy")
    ]


def betaplalas_csatorna(tarolt: dict[str, Any]) -> Csatorna:
    """Napelemes fiók: az ad-vesz mérő betáplálási regisztere (2.8.0), keret nélkül."""
    return Csatorna(szerep="betaplalas", merok=[mero_motorba(m, "betaplalas") for m in tarolt["merok"]], keret_aktiv=False)


def elozo_bazis(tarolt: dict[str, Any], ciklus_honap: int = 12) -> date | None:
    """Az előző elszámolási év kezdete: a legutóbbi elszámoló leolvasásnál legalább ~10 hónappal korábbi
    elszámoló leolvasás (évközi, pl. szerződésváltáskori elszámolás nem számít évkezdetnek)."""
    napok = sorted({d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("elszamolasi")})
    if len(napok) < 2:
        return None
    korabbiak = [x for x in napok[:-1] if (napok[-1] - x).days >= ciklus_honap * 25]
    return korabbiak[-1] if korabbiak else None


def eredmeny_tarolhato(e) -> dict[str, Any]:
    """IdoszakEredmeny → JSON-barát dict (a lezárt időszakokhoz)."""
    return {
        "tol": e.tol.isoformat(),
        "ig": e.ig.isoformat(),
        "mennyiseg": format(e.mennyiseg.quantize(Decimal("0.001")).normalize(), "f"),
        "energia_ft": int(e.energia_ft),
        "alapdij_ft": int(e.alapdij_ft),
        "osszesen_ft": int(e.osszesen_ft),
        "becsult": e.becsult,
        "szeletek": [szelet_dict(s) for s in e.szeletek],
    }


def szelet_dict(s) -> dict[str, Any]:
    return {
        "tol": s.tol.isoformat(),
        "ig": s.ig.isoformat(),
        "dijszabas": s.dijszabas_verzio,
        "idenyszak": s.idenyszak,
        "mennyiseg": round(float(s.mennyiseg), 3),
        "elszamolt": None if s.elszamolt is None else round(float(s.elszamolt), 3),
        "egyseg": s.egyseg,
        "csatorna_ft": float(s.csatorna_ft),
        "kedvezmenyes": round(float(s.kedvezmenyes), 3),
        "piaci": round(float(s.piaci), 3),
        "savkorrekcio": round(float(s.savkorrekcio), 3),
        "keret": None if s.keret is None else round(float(s.keret), 3),
        "energia_ft": float(s.energia_ft),
        "alapdij_ft": float(s.alapdij_ft),
        "ar_kedvezmenyes": float(s.egysegar_kedvezmenyes),
        "ar_piaci": float(s.egysegar_piaci),
        "becsult": s.becsult,
    }
