"""Időszak-határok és előrejelzés a nyitott időszakra."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

from .dijszabas import DijszabasTar
from .elszamolas import szamol
from .szamlalo import BECSLESI_HEZAG, NincsAdat, Pont, Szamlalo, nap_kezdete
from .tipusok import Fiok, IdoszakEredmeny

ATLAG_NAPOK = 7
UTEM_NAP = 20  # szenzor nélkül ennél hosszabb leolvasási szakasz üteméből becsülünk


def idoszak(
    nap: date, mod: str = "naptari_honap", kezdo_nap: int = 1, hatarok: list[date] | None = None,
    ablak: tuple[int, int] | None = None,
) -> tuple[date, date]:
    """A naphoz tartozó [tol, ig) elszámolási időszak.

    „diktalas”: a határok a diktálások napjai ([előző diktálás, diktálás) – a számlán „előző diktálás másnapja –
    diktálás napja”, ugyanannyi nap). Az utolsó határ után a következőt a diktálási ablak utolsó napjára várjuk
    (MVM: ha nem diktálnak, az ablak végén zárul az időszak, pl. minden hónap 8–14. → 14.), legalább 20 nappal
    az előző után; ablak nélkül havonta ugyanarra a napra. Újabb diktálás vagy számla nélkül havonta új időszak kezdődik.
    """
    if mod in ("diktalas", "leolvasas"):
        # „leolvasas”: két leolvasás között; a következő leolvasásig nyitva marad (nincs havi „becsült” lezárás).
        return _diktalasi_idoszak(nap, sorted(set(hatarok or [])), kezdo_nap, ablak, gorget=mod == "diktalas")
    if mod == "negyedev":
        # Naptári negyedév (jan., ápr., júl., okt. 1.) – pl. a negyedévente számlázott hulladékdíj.
        tol = date(nap.year, (nap.month - 1) // 3 * 3 + 1, 1)
        ig = date(tol.year + (tol.month == 10), (tol.month + 2) % 12 + 1, 1)
        return tol, ig
    if mod == "naptari_honap":
        kezdo_nap = 1
    elif mod != "egyedi_nap":
        raise ValueError(f"nem támogatott időszakmód: {mod}")
    kezdo_nap = max(1, min(kezdo_nap, 28))
    tol = nap.replace(day=kezdo_nap) if nap.day >= kezdo_nap else _honap_vissza(nap).replace(day=kezdo_nap)
    ig = (tol.replace(day=1) + timedelta(days=32)).replace(day=kezdo_nap)
    return tol, ig


def _honap_elore(d: date) -> date:
    import calendar  # noqa: PLC0415

    ev, ho = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return d.replace(year=ev, month=ho, day=min(d.day, calendar.monthrange(ev, ho)[1]))


def _diktalasi_idoszak(
    nap: date, hatarok: list[date], kezdo_nap: int, ablak: tuple[int, int] | None = None, gorget: bool = True
) -> tuple[date, date]:
    """[előző határ, következő határ) – ha nincs határ a nap előtt, a hónap kezdőnapjától havonta."""
    elotte = [h for h in hatarok if h <= nap]
    utana = [h for h in hatarok if h > nap]
    if not elotte:
        tol = nap.replace(day=1) if not utana else _honap_vissza(utana[0]).replace(day=min(utana[0].day, 28))
        if tol > nap:
            tol = nap.replace(day=1)
    else:
        tol = elotte[-1]
    if utana:
        return tol, utana[0]
    if ablak:
        ig = tol.replace(day=min(ablak[1], 28))  # az ablak utolsó napja
        while (ig - tol).days < 20:  # MVM, Kertes ház 2025: éves leolvasás 10-01 után az októberi diktálás kimaradt, a számla 10-02 – 11-10
            ig = _honap_elore(ig)
    else:
        ig = _honap_elore(tol)
    while ig <= nap:  # nincs újabb diktálás/számla: havonta új időszak (a szolgáltató havonta számláz, becsülve)
        tol, ig = (ig if gorget else tol), _honap_elore(ig)
    return tol, ig


def _honap_vissza(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _h_regiszter_elorejelzes(
    fiok: Fiok, tar: DijszabasTar, szamlalok: list[Szamlalo], szerepek: list[str], napi: Decimal, most: datetime, vege: datetime
) -> list[Szamlalo]:
    from .elszamolas import _hozzarendeles, idenyszak  # noqa: PLC0415

    idenyek = tar.felold(_hozzarendeles(fiok, most.date()), most.date(), fiok.szolgaltato, fiok.feluliras).szabalyok.get("idenyszak") or []
    pontok = {sz: [p for p in s.pontok if p.ido <= most] + [Pont(most, s.ertek(most)[0], False)] for sz, s in zip(szerepek, szamlalok)}
    ertek = {sz: pontok[sz][-1].ertek for sz in szerepek}
    t = most
    while t < vege:
        kov = min(vege, datetime.combine(t.date() + timedelta(days=1), datetime.min.time()))
        aktiv = f"h_{(idenyszak(t.date(), idenyek) or {}).get('nev')}"
        resz = Decimal((kov - t).total_seconds()) / Decimal(86400)
        if aktiv in ertek:
            ertek[aktiv] += napi * resz
        for sz in szerepek:
            pontok[sz].append(Pont(kov, ertek[sz], False))
        t = kov
    return [Szamlalo(pontok[sz]) if sz in ("h_teli", "h_nyari") else s for sz, s in zip(szerepek, szamlalok)]


def _elavult(szamlalo: Szamlalo, most: datetime) -> bool:
    """Nincs friss adat: az utolsó pont (leolvasás vagy szenzorérték) régebbi a becslési hézagnál."""
    return bool(szamlalo.pontok) and most - szamlalo.pontok[-1].ido > BECSLESI_HEZAG


def _leolvasasi_utem(szamlalo: Szamlalo) -> Decimal:
    """Az utolsó, legalább UTEM_NAP napos szakasz napi üteme (szenzor nélküli fióknál a leolvasások közt)."""
    utolso = szamlalo.pontok[-1]
    korabbiak = [p for p in szamlalo.pontok if utolso.ido - p.ido >= timedelta(days=UTEM_NAP)]
    if not korabbiak:
        return Decimal(0)
    p = korabbiak[-1]
    napok = Decimal((utolso.ido - p.ido).total_seconds()) / Decimal(86400)
    return max(utolso.ertek - p.ertek, Decimal(0)) / napok


def _szezonalis_hosszabbitas(fiok: Fiok, tar: DijszabasTar, s: Szamlalo, napi: Decimal, most: datetime, vege: datetime) -> Szamlalo:
    """Idényszakos díjszabásnál (H-tarifa) az előrejelzés: a mostanival azonos idényű napokra a mostani napi átlag, a
    másik idényre eső napokra a tavalyi ugyanazon napok napi fogyasztása (ha a számláló egy évre visszanyúlik) –
    a fűtési idényben a H-kör fogyasztása a nyárinak a sokszorosa."""
    from .elszamolas import _hozzarendeles, idenyszak  # noqa: PLC0415

    idenyek = tar.felold(_hozzarendeles(fiok, most.date()), most.date(), fiok.szolgaltato, fiok.feluliras).szabalyok.get("idenyszak") or []
    if not idenyek or not s.pontok:
        return s.meghosszabbitva(most, napi, vege)
    mai = (idenyszak(most.date(), idenyek) or {}).get("nev")
    kezdo, _ = s.ertek(most)
    pontok = [p for p in s.pontok if p.ido <= most]
    if not pontok or pontok[-1].ido != most:
        pontok.append(Pont(most, kezdo, False))
    ertek, t = kezdo, most
    while t < vege:
        kov = min(nap_kezdete(t.date() + timedelta(days=1)), vege)
        rata = napi
        if (idenyszak(t.date(), idenyek) or {}).get("nev") != mai:
            ev_elott = nap_kezdete(t.date()) - timedelta(days=365)
            if s.pontok[0].ido <= ev_elott:
                try:
                    q, _ = s.fogyasztas(ev_elott, ev_elott + timedelta(days=1))
                    rata = max(q, Decimal(0))
                except NincsAdat:
                    pass
        ertek += rata * Decimal((kov - t).total_seconds()) / Decimal(86400)
        pontok.append(Pont(kov, ertek, False))
        t = kov
    return Szamlalo(pontok)


def napi_atlag(szamlalo: Szamlalo, most: datetime, napok: int = ATLAG_NAPOK) -> Decimal:
    """Az utolsó `napok` nap napi átlagfogyasztása (ha rövidebb az adatsor, annyiból).

    Ha nincs friss adat (szenzor nélküli fiók az utolsó leolvasás után), az utolsó leolvasási szakasz üteme –
    különben az előrejelzés 0 fogyasztással, csak az alapdíjjal számolna."""
    if not szamlalo.pontok:
        return Decimal(0)
    if _elavult(szamlalo, most):
        return _leolvasasi_utem(szamlalo)
    tol = max(most - timedelta(days=napok), szamlalo.pontok[0].ido)
    hossz = Decimal((most - tol).total_seconds()) / Decimal(86400)
    if hossz <= 0:
        return Decimal(0)
    try:
        q, _ = szamlalo.fogyasztas(tol, most)
    except NincsAdat:
        return Decimal(0)
    return max(q, Decimal(0)) / hossz


@dataclass
class NyitottIdoszak:
    eddig: IdoszakEredmeny
    varhato: IdoszakEredmeny
    napi_atlag: list[Decimal]  # csatornánként
    eltelt_nap: Decimal
    hatralevo_nap: Decimal
    hatralevo_keret: Decimal | None
    varhato_keretatlepes: date | None


def nyitott(
    fiok: Fiok,
    tar: DijszabasTar,
    tol: date,
    ig: date,
    szamlalok: list[Szamlalo],
    most: datetime,
    extra_hatarok: set[date] | None = None,
) -> NyitottIdoszak:
    atlagok = [napi_atlag(s, most) for s in szamlalok]
    # Szenzor nélkül (vagy ha a szenzor kiesett) az utolsó leolvasás óta a leolvasási ütemmel becsülünk,
    # becsültként – a mért adat ott véget ér.
    becsles = any(_elavult(s, most) for s in szamlalok)
    szamlalok = [
        s.meghosszabbitva(s.pontok[-1].ido, n, most) if _elavult(s, most) else s
        for s, n in zip(szamlalok, atlagok, strict=True)
    ]
    eddig = szamol(fiok, tar, tol, ig, szamlalok, meres_vege=most, extra_hatarok=extra_hatarok, alapdij_eddig=True)
    if becsles:
        eddig = replace(eddig, becsult=True)
    vege = nap_kezdete(ig)
    if most < vege:
        szerepek = [c.szerep for c in fiok.csatornak]
        if szerepek == ["vetelezes"]:
            hosszabb = [_szezonalis_hosszabbitas(fiok, tar, szamlalok[0], atlagok[0], most, vege)]
        else:
            hosszabb = [s.meghosszabbitva(most, n, vege) for s, n in zip(szamlalok, atlagok, strict=True)]
        if "h_teli" in szerepek and "h_nyari" in szerepek:
            # H-tarifa két regiszterrel: a hőszivattyú együttes napi átlaga naptár szerint oszlik el –
            # okt. 15-től a téli, ápr. 15-től a nyári regiszter nő (ahogy a mérő is vált).
            hosszabb = _h_regiszter_elorejelzes(fiok, tar, szamlalok, szerepek, sum(atlagok, Decimal(0)), most, vege)
        varhato = szamol(fiok, tar, tol, ig, hosszabb, extra_hatarok=extra_hatarok)
    else:
        varhato = eddig

    eltelt = Decimal(max((min(most, vege) - nap_kezdete(tol)).total_seconds(), 0)) / Decimal(86400)
    hatra = Decimal(max((vege - most).total_seconds(), 0)) / Decimal(86400)

    # Keret: az első olyan csatornára, amelyen van keret (H-tarifánál a nyári regiszter).
    fo = next((s.csatorna for s in eddig.szeletek if s.keret is not None), None)
    keretes = [s for s in eddig.szeletek if s.csatorna == fo and s.keret is not None]
    hatralevo = None
    atlepes = None
    if keretes:
        mai = [s for s in keretes if nap_kezdete(s.tol) <= most < nap_kezdete(s.ig)] or keretes[-1:]
        s = mai[0]
        felhasznalt = s.elszamolt if s.elszamolt is not None else s.mennyiseg  # gáznál MJ
        keret_most = s.keret
        if not s.keret_eves:
            # Időszakos keret: a teljes időszak (minden szelete, pl. az éves leolvasásnál kettévált időszak két fele)
            # kerete mínusz az időszakban eddig felhasznált – A2-nél a két zóna együtt.
            tars = [x for x in eddig.szeletek if x.keret is not None
                    and (x.csatorna == fo or (fo.startswith("zona_") and x.csatorna.startswith("zona_")))]
            keret_most = sum((x.keret for x in tars), Decimal(0))
            felhasznalt = sum(((x.elszamolt if x.elszamolt is not None else x.mennyiseg) for x in tars), Decimal(0))
        hatralevo = max(keret_most - felhasznalt, Decimal(0))
        n = atlagok[[c.szerep for c in fiok.csatornak].index(fo)] if fo in [c.szerep for c in fiok.csatornak] else atlagok[0]
        if s.elszamolt is not None and s.mennyiseg > 0:
            n = n * s.elszamolt / s.mennyiseg  # napi átlag elszámolási egységben
        if s.piaci == 0 and n > 0:
            hatar = eddig.ig if not s.keret_eves else s.ig  # időszakos keretnél az időszak végéig
            napok = hatralevo / n
            # Igen kicsi napi átlagnál a napok száma a dátumtartományon is túl lehet: az időszakon túl nincs átlépés.
            if napok < Decimal((nap_kezdete(hatar) - most).total_seconds()) / Decimal(86400):
                nap = (most + timedelta(days=float(napok))).date()
                if nap < hatar:
                    atlepes = nap
    return NyitottIdoszak(eddig, varhato, atlagok, eltelt, hatra, hatralevo, atlepes)
