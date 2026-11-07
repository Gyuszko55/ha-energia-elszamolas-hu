"""Az elszámoló motor: egy fiók egy időszakának költsége szeletekre bontva.

Lépések (docs/terv/03_ELSZAMOLO_MOTOR.md): szeletelés → fogyasztás → keret → díjak.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

from .dijszabas import DijszabasHiba, DijszabasTar, Ervenyes
from .szamlalo import NincsAdat, Szamlalo, kezdo_allas, nap_kezdete
from .tipusok import Fiok, IdoszakEredmeny, SzeletEredmeny
from .rugalmas import rugalmas_ar
from .zona import volgy_resz

EGY = Decimal(1)
FILLER = Decimal("0.01")


def kerekit(x: Decimal) -> Decimal:
    """Forintra kerekítés – csak az időszak végösszegein, hogy a szeletek ne csússzanak el."""
    return x.quantize(EGY, rounding=ROUND_HALF_UP)


def fillerre(x: Decimal) -> Decimal:
    return x.quantize(FILLER, rounding=ROUND_HALF_UP)


def _honap_napok(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def honap_aranya(tol: date, ig: date) -> Decimal:
    """Hány „hónapnyi” a [tol, ig) szakasz: minden nap 1 / az adott hónap napjai."""
    osszeg = Decimal(0)
    d = tol
    while d < ig:
        kov = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        vege = min(kov, ig)
        osszeg += Decimal((vege - d).days) / Decimal(_honap_napok(d))
        d = vege
    return osszeg


def honap_kezdetek(tol: date, ig: date) -> set[date]:
    """Minden hónap 1-je a (tol, ig) nyílt szakaszban."""
    napok: set[date] = set()
    d = (tol.replace(day=1) + timedelta(days=32)).replace(day=1)
    while d < ig:
        napok.add(d)
        d = (d + timedelta(days=32)).replace(day=1)
    return napok


def futoertek(nap: date, atv: dict[str, Any], fiok: Fiok) -> tuple[Decimal, bool]:
    """A nap hónapjának fűtőértéke (MJ/m³) és hogy becsült-e (nincs megadva arra a hónapra)."""
    kulcs = f"{nap.year:04d}-{nap.month:02d}"
    if kulcs in fiok.futoertekek:
        return Decimal(fiok.futoertekek[kulcs]), False
    return Decimal(atv.get("futoertek_alap", 0)), True


def korrekcio(nap: date, atv: dict[str, Any], fiok: Fiok) -> Decimal:
    """Gáz korrekciós tényező (hőmérséklet/nyomás): az elszámoló számla szerinti a hónapra; más hónapra a legutóbbi
    elszámolóé (az MVM az éves elszámolón alkalmazza, pl. 1,018; a részszámlák 1,0-val számolnak), ennek híján az
    alapérték."""
    kulcs = f"{nap.year:04d}-{nap.month:02d}"
    if kulcs in fiok.korrekciok:
        return Decimal(fiok.korrekciok[kulcs])
    if fiok.korrekciok:
        return Decimal(fiok.korrekciok[max(fiok.korrekciok)])
    return Decimal(atv.get("korrekcios_tenyezo_alap", 1))


def atvalt(q: Decimal, nap: date, atv: dict[str, Any] | None, fiok: Fiok) -> tuple[Decimal, bool]:
    """Mért mennyiség → elszámolási mennyiség. Gáz: m³ × korrekció × fűtőérték, egész MJ-ra kerekítve."""
    if not atv:
        return q, False
    if atv.get("tipus") != "gaz_mj":
        raise DijszabasHiba(f"ismeretlen átváltás: {atv.get('tipus')}")
    fe, becsult = futoertek(nap, atv, fiok)
    korr = korrekcio(nap, atv, fiok)
    return kerekit(q * korr * fe), becsult


def elszamolt_mennyiseg(szamlalo: Szamlalo, tol: date, ig: date, atv: dict[str, Any] | None, fiok: Fiok) -> Decimal:
    """[tol, ig) fogyasztása elszámolási egységben, hónaponkénti fűtőértékkel."""
    if ig <= tol:
        return Decimal(0)
    hatarok = sorted({tol, ig} | (honap_kezdetek(tol, ig) if atv else set()))
    osszeg = Decimal(0)
    for a, b in zip(hatarok, hatarok[1:]):
        q, _ = szamlalo.fogyasztas(nap_kezdete(a), nap_kezdete(b))
        osszeg += atvalt(max(q, Decimal(0)), a, atv, fiok)[0]
    return osszeg


def _md(s: str) -> tuple[int, int]:
    h, n = str(s).split("-")
    return int(h), int(n)


def idenyszak(nap: date, idenyszakok: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A naphoz tartozó idényszak. A tol/ig nélküli szakasz a „maradék” (pl. nyár)."""
    if not idenyszakok:
        return None
    md = (nap.month, nap.day)
    maradek = None
    for sz in idenyszakok:
        if "tol" not in sz:
            maradek = sz
            continue
        tol, ig = _md(sz["tol"]), _md(sz["ig"])
        bent = (tol <= md < ig) if tol < ig else (md >= tol or md < ig)
        if bent:
            return sz
    return maradek


def _idenyhatarok(tol: date, ig: date, idenyszakok: list[dict[str, Any]]) -> set[date]:
    napok: set[date] = set()
    for sz in idenyszakok:
        for kulcs in ("tol", "ig"):
            if kulcs in sz:
                h, n = _md(sz[kulcs])
                for ev in range(tol.year, ig.year + 1):
                    napok.add(date(ev, h, n))
    return napok


def _hozzarendeles(fiok: Fiok, nap: date) -> str:
    for h in sorted(fiok.dijszabasok, key=lambda x: x.ervenyes_tol, reverse=True):
        if h.ervenyes_tol <= nap and (h.ervenyes_ig is None or nap < h.ervenyes_ig):
            return h.dijszabas
    raise DijszabasHiba(f"nincs díjszabás hozzárendelve {nap} napra")


def _napi_keret(keret: dict[str, Any]) -> Decimal:
    if "napi_mennyiseg" in keret:
        return Decimal(keret["napi_mennyiseg"])
    return Decimal(keret["ev_mennyiseg"]) / Decimal(365)


HALMOZOTT_TIPUSOK = ("napi_aranyos", "havi_sulyozott")
ZONA = "zona_"  # A2: a csúcs- és völgyidőszaki regiszter csatornája („zona_csucs”, „zona_volgy”), közös kerettel


def _keret_nyers(keret: dict[str, Any], a: date, b: date) -> Decimal:
    """Az [a, b) napjaira járó keret kerekítés nélkül. „havi_sulyozott”: hónaponként rögzített mennyiség (pl. MVM
    gáz: január 12 365 MJ … július 512 MJ), a hónap napjai között egyenletesen – a hónap napjainak számával osztva,
    így szökőévben a februári napi rész kisebb, a havi összeg ugyanannyi."""
    if keret.get("tipus") != "havi_sulyozott":
        return _napi_keret(keret) * Decimal((b - a).days)
    havi = keret["havi"]
    osszeg = Decimal(0)
    d = a
    while d < b:
        kov = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        vege = min(kov, b)
        osszeg += Decimal(str(havi[d.month - 1])) * Decimal((vege - d).days) / Decimal(_honap_napok(d))
        d = vege
    return osszeg


def _kerekit_keret(keret: dict[str, Any], k: Decimal) -> Decimal:
    if keret.get("kerekites") is not None:  # pl. MVM: egész kWh-ra
        return k.quantize(Decimal(1).scaleb(-int(keret["kerekites"])), rounding=ROUND_HALF_UP)
    return k


def _ev_mulva(d: date, ev: int) -> date:
    """Ugyanaz a nap ev évvel később (február 29. → 28.)."""
    return d.replace(year=d.year + ev, day=min(d.day, calendar.monthrange(d.year + ev, d.month)[1]))


def eves_keret_kezdete(bazis: date, nap: date) -> date:
    """Az éves keret évének kezdete a napon: az éves bázis legutóbbi (≤ nap) évfordulója – a keret az évfordulón
    megújul akkor is, ha az új éves leolvasást (bázist) még nem rögzítették."""
    ev = max(nap.year - bazis.year, 0)
    while ev > 0 and _ev_mulva(bazis, ev) > nap:
        ev -= 1
    return _ev_mulva(bazis, ev)


def _evkezdet_napok(keret: dict[str, Any], tol: date, ig: date) -> set[date]:
    """A keret „ev_kezdet” (HH-NN, pl. gáz: 08-01 – a kedvezményes év kezdete) napjai a [tol, ig] szakaszban."""
    if not keret.get("ev_kezdet"):
        return set()
    h, n = _md(keret["ev_kezdet"])
    return {x for x in (date(ev, h, n) for ev in range(tol.year - 1, ig.year + 1)) if tol <= x <= ig}


def aram_ev_kezdete(sajat: Ervenyes, nap: date) -> date | None:
    """Az áramfiók jogszabály szerinti évének kezdete a napon: H-tarifa: a legutóbbi nyári idény eleje (ápr. 16.),
    különben a kedvezményes év (aug. 1.) – 4/2011. NFM rendelet 6. §. None: a díjszabásban nincs ilyen év."""
    if idenyek := sajat.szabalyok.get("idenyszak"):
        return max((x for x in _idenyhatarok(date(nap.year - 1, 1, 1), nap, idenyek)
                    if x <= nap and (idenyszak(x, idenyek) or {}).get("nev") == "nyari"), default=None)
    return max(_evkezdet_napok(sajat.szabalyok.get("keret") or {}, date(nap.year - 1, 1, 1), nap), default=None)


def _egesz_kulonbseg(csatorna: Any, szamlalo: Szamlalo, ta: datetime, tb: datetime) -> Decimal:
    """Az [ta, tb) szakasz fogyasztása egész egységre (lefelé) kerekített óraállásokból. A számláló a kezdőállástól
    mér, ezért a mérő kezdőállását hozzáadjuk (mérőcsere után az előző mérők záróállásával eltolva, ami egész)."""
    alap = kezdo_allas(min(csatorna.merok, key=lambda m: m.beepitve)) if csatorna.merok else Decimal(0)
    ea = (szamlalo.ertek(ta)[0] + alap).to_integral_value(rounding=ROUND_FLOOR)
    eb = (szamlalo.ertek(tb)[0] + alap).to_integral_value(rounding=ROUND_FLOOR)
    return max(eb - ea, Decimal(0))


def _szamla_minimum(fiok: Fiok, tar: DijszabasTar, tol: date, ig: date, meres_vege: datetime | None) -> Decimal:
    """A díjszabás számlánkénti minimális mennyisége („mennyiseg_minimum”, egész mennyiségű számlázásnál), ha a
    [tol, ig) egy teljes számlázási időszak (hossza a fiók számlázási üteme) – folyó („eddig”) számításnál és sajátos
    számlázásnál (üdülő) nem."""
    if meres_vege is not None or fiok.minimum_mentes or fiok.szamla_honap <= 0:
        return Decimal(0)
    if any(a < ig and (b is None or b > tol) for a, b in fiok.szunetel):  # szüneteltetés az időszakban
        return Decimal(0)
    if round((ig - tol).days / Decimal("30.44")) != fiok.szamla_honap:
        return Decimal(0)
    nap = ig - timedelta(days=1)
    try:
        sajat = tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
    except (DijszabasHiba, KeyError):
        return Decimal(0)
    if not sajat.szabalyok.get("mennyiseg_egesz"):
        return Decimal(0)
    return Decimal(str(sajat.szabalyok.get("mennyiseg_minimum") or 0))


def _modhoz(fiok: Fiok, keret: dict[str, Any] | None) -> dict[str, Any] | None:
    """A fiókra érvényes keret-szabály: átalányos (részszámlás) fióknál a „reszszamla” változat, ha a díjszabás megad
    ilyet; fogyasztói közösségnél a mennyiségek a fiók keret-szorzójával."""
    if keret and fiok.reszszamlas and keret.get("reszszamla"):
        keret = keret["reszszamla"]
    if keret and fiok.keret_szorzo != 1:
        sz = fiok.keret_szorzo
        keret = dict(keret)
        for k in ("ev_mennyiseg", "napi_mennyiseg"):
            if k in keret:
                keret[k] = Decimal(str(keret[k])) * sz
        if "havi" in keret:
            keret["havi"] = [Decimal(str(x)) * sz for x in keret["havi"]]
    return keret


def alapdij_ho(sajat: Ervenyes, fiok: Fiok) -> Decimal:
    """A havi (nettó vagy bruttó) alapdíj; „alapdij.szorzo”-nál a fiók adatával szorozva (gáz B1: m³/h)."""
    havi = sajat.dijak.get("alapdij_ho") or Decimal(0)
    szorzo = (sajat.szabalyok.get("alapdij") or {}).get("szorzo")
    if szorzo:
        havi = havi * fiok.szorzok.get(szorzo, Decimal(1))
    return havi


def kiegeszito_tetelek(sajat: Ervenyes, fiok: Fiok, elsok: set[date], kr: Any = None) -> list[tuple[Decimal, int, Decimal, str]]:
    """A díjszabás „kiegeszito” havi tételei (pl. távhő: fűtési alapdíj légköbméterre, hődíj-átalány GJ-ra) – csak
    „alapdij.mod: idoszakonkent” mellett: (havi nettó díj, hónapok száma, ÁFA %, név) a szelet számlázott hónapjaira
    (elsok: a hónapok 1-jei), a tétel „honapok” listája szerint szűrve. Díj: dijak[dij] × fiók-szorzó[szorzo]."""
    out = []
    for k in sajat.szabalyok.get("kiegeszito") or []:
        db = sum(1 for x in elsok if not k.get("honapok") or x.month in k["honapok"])
        ar = sajat.dijak.get(k["dij"])
        if not db or not ar:
            continue
        havi = Decimal(ar) * (fiok.szorzok.get(k["szorzo"], Decimal(0)) if k.get("szorzo") else Decimal(1))
        if not havi:
            continue
        out.append(((kr or fillerre)(havi), db, Decimal(k.get("afa", sajat.dijak.get("afa") or 0)), k["nev"]))
    return out


def _keretes_nap(fiok: Fiok, tar: DijszabasTar, szerep: str, nap: date) -> dict[str, Any] | None:
    """A nap összesített (halmozott) napi arányos keret-szabálya az adott csatornán, ha jár rá keret – különben None.
    H-tarifa: a fűtési idényben (téli ár) nincs keret, a nyári (1.82) regiszterre csak az idényén kívül gyűlik."""
    sajat = tar.felold(_hozzarendeles(fiok, nap), nap, fiok.szolgaltato, fiok.feluliras)
    _, keret_szabaly, _, idx = _szabaly(sajat, nap, tar, fiok, szerep)
    k = keret_szabaly or {}
    if k.get("tipus") not in HALMOZOTT_TIPUSOK or not k.get("osszesitett"):
        return None
    if szerep.startswith("h_"):
        datum_idx = (idenyszak(nap, sajat.szabalyok.get("idenyszak") or []) or {}).get("nev")
        if datum_idx != idx:
            return None
    return k


def _szakaszhatarok(fiok: Fiok, tar: DijszabasTar, tol: date, ig: date) -> list[date]:
    """[tol, ig] felbontása díjszabás-, díjváltozás- és idényhatárok szerint (rendezett, a két véggel)."""
    hatarok = {tol, ig}
    for h in fiok.dijszabasok:
        hatarok.add(h.ervenyes_tol)
        if h.ervenyes_ig:
            hatarok.add(h.ervenyes_ig)
        hatarok |= tar.valtozasi_napok(h.dijszabas)
        for v in tar[h.dijszabas].verziok:
            hatarok |= _idenyhatarok(tol, ig, v.szabalyok.get("idenyszak") or [])
    return sorted(d for d in hatarok if tol <= d <= ig)


def _osszesitett_kedvezmenyes(
    fiok: Fiok, tar: DijszabasTar, szerep: str, szamlalok: list[Szamlalo], keret_szabaly: dict[str, Any],
    a: date, b: date, elsz: Decimal, atv: dict[str, Any] | None,
) -> Decimal | None:
    """Összesített (elszámolási évre halmozott) keret: az év elejétől a kedvezményes mennyiség a halmozott fogyasztás
    és a halmozott keret kisebbike, a szelet ennek a növekményét kapja (MVM: „sávkorrekció”). Így a korábban ki nem
    használt keret később piaci helyett kedvezményes áron jár, és fordítva.

    Az év kezdete: a keret „ev_kezdet”-e (a kedvezményes év, 08-01: 4/2011. NFM rendelet 6. § (3)), ennek híján az
    éves elszámoló leolvasás. H-tarifa nyári regiszterén a rendelet 6. § (1) szerint a keret a fűtési idényen kívüli
    időszakra szól: az év kezdete az idény eleje. A keret csak ezen belül csoportosítható át, a következő évre nem
    vihető át. Csak a keretre jogosult napok számítanak (H-tarifa: a nyári
    1.82-es regiszter az idényén kívül; a fűtési idény téli fogyasztása és napjai kimaradnak). Több számláló (A2:
    csúcs + völgy) közös keretnél: a fogyasztásuk összege számít.
    None: nincs évhatár a szelet előtt, vagy nincs adat az év elejétől – ilyenkor szeletenkénti a keret."""
    if keret_szabaly.get("ev_kezdet"):
        sajat = tar.felold(_hozzarendeles(fiok, a), a, fiok.szolgaltato, fiok.feluliras)
        if idenyek := sajat.szabalyok.get("idenyszak"):  # H-tarifa: az idény eleje
            evkezdet = max((x for x in _idenyhatarok(date(a.year - 1, 1, 1), a, idenyek) if x <= a), default=None)
        else:
            evkezdet = max(_evkezdet_napok(keret_szabaly, date(a.year - 1, 1, 1), a), default=None)
        # Év közben indult mérés (új fiók, első adat aug. 1. után): a keret az első adattól, időarányosan jár. Csak
        # visszamenőleges keretnél: a gáz „csak előre átvihető” kerete marad a kedvezményes évhez kötve.
        if evkezdet and keret_szabaly.get("visszamenoleges") is not False:
            elso = [p.ido.date() for sz in szamlalok for p in sz.pontok[:1]]
            if elso and max(elso) > evkezdet:
                evkezdet = max(elso)
    else:
        evkezdet = max((x for x in fiok.elszamolasi_napok if x <= a), default=None)
    if evkezdet is None:
        return None
    # MVM: a keret számlánként (tételenként) kerekítve jár – az év elejétől a kerekített részek összege. A kerekítési
    # pontok: a számlázási időszakok határai, ill. naptári havi számlázásnál a hónapok, és a díjszabás „tetel_hatar”
    # napja (villany: aug. 1., ott a számla két tételre bomlik). Ezek nélkül a halmozott keret egyben kerekítve.
    tetel = keret_szabaly.get("tetel_hatar")
    kerek_pontok: set[date] = set(fiok.szamlazasi_hatarok)
    if fiok.szamlazas_havi:
        kerek_pontok |= honap_kezdetek(evkezdet - timedelta(days=1), b + timedelta(days=1))
    if tetel and kerek_pontok:
        ho, nap = _md(tetel)
        kerek_pontok |= {date(ev, ho, nap) for ev in range(evkezdet.year, b.year + 1)}
    szamlankent = bool(kerek_pontok) and not keret_szabaly.get("visszamenoleges") is False
    jogosult = Decimal(0)  # az év elejétől a szeletig járó keret (számlánként kerekítve, ill. kerekítetlenül)
    elotte = Decimal(0)
    felhasznalt_keret = Decimal(0)  # csak előre átvihető keretnél: az eddig kedvezményesen elszámolt mennyiség
    csak_elore = keret_szabaly.get("visszamenoleges") is False
    # Előre átvihető keretnél hónaponként haladunk (a számlák havonta mennek), hogy a túllépés ne fogyassza a később
    # járó keretet; visszamenőlegesnél elég a díjszabás-/idényhatár.
    pontok = sorted(set(_szakaszhatarok(fiok, tar, evkezdet, a)) | (honap_kezdetek(evkezdet, a) if csak_elore else set())
                    | ({p for p in kerek_pontok if evkezdet < p < a} if szamlankent else set()))
    try:
        for x, y in zip(pontok, pontok[1:]):
            try:
                if _keretes_nap(fiok, tar, szerep, x) is None:
                    continue
            except DijszabasHiba:  # az évkezdet még a fiók első díjszabása előtt van
                continue
            nyers = _keret_nyers(keret_szabaly, x, y)
            jogosult += _kerekit_keret(keret_szabaly, nyers) if szamlankent else nyers
            q = sum((elszamolt_mennyiseg(sz, x, y, atv, fiok) for sz in szamlalok), Decimal(0))
            elotte += q
            if csak_elore:
                felhasznalt_keret += max(min(max(q, Decimal(0)), _kerekit_keret(keret_szabaly, jogosult) - felhasznalt_keret), Decimal(0))
    except NincsAdat:
        return None
    elotte = max(elotte, Decimal(0))
    if szamlankent:
        ig_a = jogosult
        resz = sorted({a, b} | {p for p in kerek_pontok if a < p < b})
        ig_b = jogosult + sum((_kerekit_keret(keret_szabaly, _keret_nyers(keret_szabaly, x, y)) for x, y in zip(resz, resz[1:])),
                              Decimal(0))
    else:
        ig_a = _kerekit_keret(keret_szabaly, jogosult)
        ig_b = _kerekit_keret(keret_szabaly, jogosult + _keret_nyers(keret_szabaly, a, b))
    if csak_elore:
        # A ki nem használt keret később jár, de a korábbi túllépést nem írja jóvá (gáz, MVM GYIK).
        return min(elsz, max(ig_b - felhasznalt_keret, Decimal(0)))
    return min(elotte + elsz, ig_b) - min(elotte, ig_a)


def _osszesitett_van(fiok: Fiok, tar: DijszabasTar) -> bool:
    """Van-e a fiók díjszabásaiban (az idényszakok által hivatkozottakat is beleértve) összesített keret."""
    def vizsgal(azon: str, latott: set[str]) -> bool:
        if azon in latott:
            return False
        latott.add(azon)
        for v in tar[azon].verziok:
            if (v.szabalyok.get("keret") or {}).get("osszesitett"):
                return True
            for sz in v.szabalyok.get("idenyszak") or []:
                if sz.get("dijszabas") and sz.get("sajat_keret", True) and vizsgal(sz["dijszabas"], latott):
                    return True
        return False

    return any(vizsgal(h.dijszabas, set()) for h in fiok.dijszabasok)


def szamol(
    fiok: Fiok,
    tar: DijszabasTar,
    tol: date,
    ig: date,
    szamlalok: list[Szamlalo],
    meres_vege: datetime | None = None,
    extra_hatarok: set[date] | None = None,
    alapdij_eddig: bool = False,
) -> IdoszakEredmeny:
    """A [tol, ig) időszak elszámolása.

    szamlalok: csatornánként egy számláló, a fiok.csatornak sorrendjében.
    meres_vege: eddig van mért fogyasztás (nyitott időszaknál „most”). A keret és az alapdíj
    ettől függetlenül a teljes szeletre jár, ahogy a számlán is – kivéve, ha alapdij_eddig: akkor az alapdíj csak a
    meres_vege napjáig elmúlt hónapfordulókra (a panel „Eddig” értéke ne tartalmazzon jövőbeli havi alapdíjat).
    """
    vege = min(meres_vege, nap_kezdete(ig)) if meres_vege else nap_kezdete(ig)

    hatarok = {tol, ig} | (extra_hatarok or set())
    for h in fiok.dijszabasok:
        hatarok.add(h.ervenyes_tol)
        if h.ervenyes_ig:
            hatarok.add(h.ervenyes_ig)
        hatarok |= tar.valtozasi_napok(h.dijszabas)
        for v in tar[h.dijszabas].verziok:
            hatarok |= _idenyhatarok(tol, ig, v.szabalyok.get("idenyszak") or [])
    hatarok |= {f.ervenyes_tol for f in fiok.feluliras}
    hatarok |= {x for sz in fiok.szunetel for x in sz if x is not None}  # szüneteltetés eleje / vége
    if any(c.levonas_fobol for c in fiok.csatornak):  # a locsolási idény határai (almérő-levonás)
        for h in fiok.dijszabasok:
            for v in tar[h.dijszabas].verziok:
                if v.szabalyok.get("almero_idoszak"):
                    hatarok |= _idenyhatarok(tol, ig, [v.szabalyok["almero_idoszak"]])
    if _osszesitett_van(fiok, tar):
        hatarok |= set(fiok.elszamolasi_napok)  # összesített keretnél egy szelet ne nyúljon át évhatáron
    for h in fiok.dijszabasok:  # a kedvezményes év fordulója (gáz: 08-01) – a számla is külön soron bontja
        for v in tar[h.dijszabas].verziok:
            hatarok |= _evkezdet_napok(_modhoz(fiok, v.szabalyok.get("keret")) or {}, tol, ig)
    if fiok.eves_bazis and any(
        (_modhoz(fiok, v.szabalyok.get("keret")) or {}).get("tipus") == "eves" for h in fiok.dijszabasok for v in tar[h.dijszabas].verziok
    ):  # az éves keret a bázis évfordulóin megújul: ott szelethatár
        hatarok |= {_ev_mulva(fiok.eves_bazis, k) for k in range(1, ig.year - fiok.eves_bazis.year + 1)}
    if any(v.szabalyok.get("atvaltas") for h in fiok.dijszabasok for v in tar[h.dijszabas].verziok):
        hatarok |= honap_kezdetek(tol, ig)  # a fűtőérték havonta változik: a számla is hónaponként bont
    napok = sorted(d for d in hatarok if tol <= d <= ig)

    szeletek: list[SzeletEredmeny] = []
    becsult_ossz = False
    zonak = [sz for c, sz in zip(fiok.csatornak, szamlalok, strict=True) if c.szerep.startswith(ZONA)]
    zona_idx = [c.szerep for c in fiok.csatornak if c.szerep.startswith(ZONA)]
    minimum = _szamla_minimum(fiok, tar, tol, ig, meres_vege)
    for ci, (csatorna, szamlalo) in enumerate(zip(fiok.csatornak, szamlalok, strict=True)):
        # Számlánkénti minimális mennyiség (pl. víz, távhős melegvíz: 1 m³): a teljes számlázási időszak egészre
        # kerekített fogyasztása alatt a hiányt az utolsó szelet kapja.
        hiany = Decimal(0)
        if minimum and csatorna.szerep == "vetelezes" and len(napok) > 1:
            try:
                hiany = max(minimum - _egesz_kulonbseg(csatorna, szamlalo, nap_kezdete(tol), vege), Decimal(0))
            except NincsAdat:  # hónap közben felvett fiók: a minimum nem jár (töredék időszak)
                hiany = Decimal(0)
        # Hónap közben felvett fiók: ha a mérő kezdőnapja az időszakon belül van, előtte nincs fogyasztás.
        # (A teljesen a kezdőnap előtti időszak továbbra is NincsAdat – azt nem zárjuk le.)
        elso = szamlalo.pontok[0].ido if szamlalo.pontok else None
        kezdes_benne = elso is not None and nap_kezdete(tol) < elso < vege
        for a, b in zip(napok, napok[1:]):
            sajat = tar.felold(_hozzarendeles(fiok, a), a, fiok.szolgaltato, fiok.feluliras)
            if fiok.szunetel_nap(a):  # szüneteltetett számlázás: erre a szeletre semmi nem jár
                szeletek.append(SzeletEredmeny(
                    tol=a, ig=b, napok=Decimal((b - a).days), dijszabas_verzio=sajat.cimke, idenyszak=None,
                    mennyiseg=Decimal(0), kedvezmenyes=Decimal(0), piaci=Decimal(0), keret=None, energia_ft=Decimal(0),
                    alapdij_ft=Decimal(0), egysegar_kedvezmenyes=Decimal(0), egysegar_piaci=Decimal(0), becsult=False,
                    csatorna=csatorna.szerep, elszamolt=Decimal(0), egyseg=tar[sajat.azonosito].egyseg))
                continue
            arak, keret_szabaly, ar_kulcs, idx = _szabaly(sajat, a, tar, fiok, csatorna.szerep)

            ta, tb = nap_kezdete(a), min(nap_kezdete(b), vege)
            if kezdes_benne and ta < elso:
                ta = min(elso, tb)
            if ta < tb:
                q, becsult = szamlalo.fogyasztas(ta, tb)
            else:
                q, becsult = Decimal(0), False
            q = max(q, Decimal(0))
            atv = sajat.szabalyok.get("atvaltas")
            elsz, becsult_fe = atvalt(q, a, atv, fiok)
            egesz = bool(sajat.szabalyok.get("mennyiseg_egesz"))
            if egesz:
                # A szolgáltató egész m³-re (lefelé) kerekített óraállások különbségével számláz (víz): a szelet a két
                # határán vett kerekített állás különbsége – így a szeletek összege pontosan a számla mennyisége.
                elsz = _egesz_kulonbseg(csatorna, szamlalo, ta, tb) if ta < tb else Decimal(0)
            if hiany and b == napok[-1]:
                elsz += hiany
            becsult = becsult or becsult_fe or sajat.verzio_elott  # díjszabás első verziója előtt: annak díjaival
            becsult_ossz |= becsult

            napszam = Decimal((b - a).days)
            keret: Decimal | None
            tipus = (keret_szabaly or {}).get("tipus", "nincs")
            if not csatorna.keret_aktiv and tipus != "nincs":
                keret = Decimal(0)
            elif tipus in HALMOZOTT_TIPUSOK:
                keret = _kerekit_keret(keret_szabaly, _keret_nyers(keret_szabaly, a, b))
            elif tipus == "eves":
                if fiok.eves_bazis is None:
                    raise DijszabasHiba("éves kerethez meg kell adni a fiók éves bázisdátumát")
                felhasznalt = elszamolt_mennyiseg(szamlalo, eves_keret_kezdete(fiok.eves_bazis, a), a, atv, fiok)
                keret = max(Decimal(keret_szabaly["ev_mennyiseg"]) - felhasznalt, Decimal(0))
            else:
                keret = None
            if keret is not None and csatorna.szerep.startswith("h_"):
                # H-regiszter: a saját idényén kívül nem gyűlik kerete (pl. télen a nyári 1.82-es regiszteré).
                datum_idx = (idenyszak(a, sajat.szabalyok.get("idenyszak") or []) or {}).get("nev")
                if datum_idx != idx:
                    keret = Decimal(0)

            savk = Decimal(0)
            if keret is None:
                kedv, piaci = elsz, Decimal(0)
                ar_k, ar_p = arak.get(ar_kulcs, Decimal(0)), arak.get("energia_piaci", Decimal(0))  # fix díjnál nincs egységár
            else:
                ar_k, ar_p = arak[ar_kulcs if csatorna.szerep.startswith(ZONA) else "energia_kedvezmenyes"], arak["energia_piaci"]
                zona = csatorna.szerep.startswith(ZONA) and len(zonak) > 1
                if zona:
                    # A2: a mérési pont egy kerete a két zóna között a fogyasztásuk arányában oszlik meg.
                    zq = [max(zsz.fogyasztas(ta, tb)[0], Decimal(0)) if ta < tb else Decimal(0) for zsz in zonak]
                    ossz_q = sum(zq, Decimal(0))
                    suly = zq if ossz_q > 0 else [Decimal(1)] * len(zonak)  # fogyasztás nélkül egyenlő arányban
                    j = zona_idx.index(csatorna.szerep)

                    def resz(osszeg: Decimal) -> Decimal:
                        """A zóna része: kumulatív kerekítéssel, hogy a zónák részeinek összege pontosan az egész legyen."""
                        def ig(k: int) -> Decimal:
                            return _kerekit_keret(keret_szabaly, osszeg * sum(suly[:k], Decimal(0)) / sum(suly, Decimal(0)))
                        return ig(j + 1) - ig(j)

                    keret = resz(keret)
                kedv, piaci = min(elsz, keret), max(elsz - keret, Decimal(0))
                if (
                    tipus in HALMOZOTT_TIPUSOK and keret_szabaly.get("osszesitett") and keret
                    and csatorna.keret_aktiv and (csatorna.szerep in ("vetelezes", "h_nyari") or zona)
                ):
                    # Folyó időszakban a halmozott keret csak a mért (eltelt) napokig jár – különben a hónap
                    # elején a teljes havi keret egyszerre jóváírná a korábbi túllépést.
                    b_meres = b if tb >= nap_kezdete(b) else max(a, tb.date())
                    osszesitett = _osszesitett_kedvezmenyes(
                        fiok, tar, csatorna.szerep, zonak if zona else [szamlalo], keret_szabaly, a, b_meres,
                        ossz_q if zona else elsz, atv,
                    )
                    if osszesitett is not None and not zona and osszesitett < kedv and b_meres < b:
                        # Levonás (negatív korrekció) csak akkor, ha a TELJES időszak keretével is túllépés van: hogy a
                        # folyó időszakban a fogyasztás az eltelt napok kereténél gyorsabban nő, még nem túllépés – a
                        # szolgáltató az időszak végén számol (pl. az év első időszakában nincs mit visszarendezni).
                        teljes = _osszesitett_kedvezmenyes(
                            fiok, tar, csatorna.szerep, [szamlalo], keret_szabaly, a, b, elsz, atv,
                        )
                        if teljes is not None:
                            osszesitett = max(osszesitett, min(kedv, teljes))
                    if osszesitett is not None:
                        if zona:
                            osszesitett = resz(osszesitett)
                        savk = osszesitett - kedv
                        kedv, piaci = osszesitett, elsz - osszesitett

            # D árszabás: a keret feletti rész a szakasz fogyasztásával súlyozott rugalmas egységáron (nettó, ÁFA nélkül).
            if sajat.szabalyok.get("rugalmas") and keret is not None:
                d_ar, d_becsult = rugalmas_ar(fiok, a, b)
                if d_ar is not None:
                    ar_p = d_ar
                if piaci > 0:
                    becsult = becsult or d_becsult or d_ar is None
                    becsult_ossz |= becsult

            # A2 egy csatornán (regiszter-szenzorok nélkül): a fogyasztás csúcs/völgy aránya órák szerint; a keret közös,
            # a kedvezményes rész a zónák között fogyasztásarányosan, mindkettő a saját árán.
            volgy_arany: Decimal | None = None
            volgy_ft = Decimal(0)
            zonak_sz = sajat.szabalyok.get("zonak")
            if zonak_sz and csatorna.szerep == "vetelezes" and keret is not None:
                volgy_arany, zona_becsult = volgy_resz(fiok.zona_napok, a, b)
                becsult = becsult or zona_becsult
                becsult_ossz |= becsult
                ar_c = arak[next(z["ar"] for z in zonak_sz if z["nev"] == "csucs")]
                ar_v = arak[next(z["ar"] for z in zonak_sz if z["nev"] == "volgy")]
                ar_k = ar_c * (1 - volgy_arany) + ar_v * volgy_arany

            q_szamla = elsz if egesz else q  # a csatornadíj alapja (almérőnél a levonandó mennyiség is)
            # Víz: csatornadíj a mért mennyiség után (csatornánként kikapcsolható, pl. locsolási almérő).
            csat_ar = arak.get("csatorna_m3") if sajat.szabalyok.get("csatornadij") and csatorna.csatornadij_aktiv else None
            if csatorna.levonas_fobol:
                # A főmérő mögötti almérő: a vize már a főmérőn szerepel, a csatornadíjból viszont levonódik
                # (DAKÖV: „Főmérő(k)ből almérő(kö)n mért vízhasználat levonása”) – de csak a locsolási idényben
                # (58/2013. Korm. rendelet: május 1. – szeptember 30.); azon kívül nem jár levonás, és nem is számoljuk.
                kedv = piaci = elsz = Decimal(0)
                idenyben = idenyszak(a, [sajat.szabalyok["almero_idoszak"]]) if sajat.szabalyok.get("almero_idoszak") else True
                csat_ar = -arak["csatorna_m3"] if sajat.szabalyok.get("csatornadij") and idenyben else None
                if not idenyben:
                    q_szamla = Decimal(0)
            rhd = arak.get("rendszerhasznalati") or Decimal(0)

            alapdij = Decimal(0)
            havi_ervenyes = Decimal(0)  # a ténylegesen alkalmazott havi alapdíj (H-tarifánál nyáron az A1-é)
            fix_elsok: set[date] = set()  # a szelet számlázott hónapjai (a kiegészítő havi tételekhez)
            if ci == 0:  # az alapdíj a fiókot terheli, nem csatornánként
                havi = alapdij_ho(sajat, fiok)
                if (sajat.szabalyok.get("alapdij") or {}).get("mod") == "idoszakonkent":
                    # MVM: annyi teljes havi alapdíj, ahány hónap 1-je esik az elszámolt időszakba (a szelet [a, b)
                    # napjai közé) – egyhavi számlán egy, a 07.10–07.31-i töredéken nulla, a 08.01–09.08-in kettő, az
                    # éves gázelszámolón tizenkettő (valódi számlákkal ellenőrizve).
                    # Diktálásnál a [a, b) szelet a számlán „a másnapja – b napja”: a hónap 1-jei az (a, b] napok közül
                    # (a 10.01-i diktálás az addigi számlához tartozik); naptári időszaknál az [a, b) napjai.
                    if fiok.szamlazasi_hatarok:
                        elsok = set(honap_kezdetek(a, b)) | ({b} if b.day == 1 else set())
                    else:
                        elsok = set(honap_kezdetek(a, b)) | ({a} if a.day == 1 else set())
                    if alapdij_eddig and meres_vege:
                        elsok = {x for x in elsok if x <= meres_vege.date()}
                    fix_elsok = elsok
                    # Csak bizonyos hónapokban járó alapdíj (pl. távhő: a fűtési idény szept.–máj. hónapjaiban).
                    if honapok := (sajat.szabalyok.get("alapdij") or {}).get("honapok"):
                        elsok = {x for x in elsok if x.month in honapok}
                    db = len(elsok)
                    # Idényszakos díjszabásnál (H-tarifa) az alapdíj a hónap 1-jén érvényes idényé: télen a H saját
                    # (39,50), nyáron – amikor az A1 szabályai érvényesek – az A1 alapdíja (120,50; számlával ellenőrizve).
                    idenyek = sajat.szabalyok.get("idenyszak") or []
                    if db and idenyek:
                        jeloltek = honap_kezdetek(a, b) | ({b} if fiok.szamlazasi_hatarok and b.day == 1 else set()) \
                            | ({a} if not fiok.szamlazasi_hatarok and a.day == 1 else set())
                        elso = min(jeloltek)
                        isz = idenyszak(elso, idenyek)
                        if isz and isz.get("dijszabas"):
                            havi = alapdij_ho(tar.felold(isz["dijszabas"], elso, fiok.szolgaltato, fiok.feluliras), fiok)
                    alapdij = havi * db
                else:
                    b_ad = min(b, meres_vege.date() + timedelta(days=1)) if alapdij_eddig and meres_vege else b
                    alapdij = havi * honap_aranya(a, b_ad) if b_ad > a else Decimal(0)
                havi_ervenyes = havi

            afa = arak.get("afa")
            if afa is not None:
                # Nettó díjak: a számla tételsoronként forintra kerekít, az ÁFA a nettóra jön.
                szorzo = 1 + Decimal(afa) / 100
                # „tetel”: tételsoronként forintra (MVM); „vegosszeg”: fillérre, csak a végösszeg forintra (pl. DAKÖV).
                kr = kerekit if sajat.szabalyok.get("szamla_kerekites", "tetel") == "tetel" else fillerre
                ny = (idx or "").replace("teli", "téli").replace("nyari", "nyári")
                cimke = f" ({'H ' if 'h_' in csatorna.szerep or ny else ''}{ny})" if ny else ""
                tetelek = []
                if volgy_arany is not None:  # A2: csúcs és völgy külön tételsor
                    kv = kedv * volgy_arany
                    netto = kr((kedv - kv) * ar_c) + kr(kv * ar_v) + kr(piaci * ar_p) + kr(elsz * rhd)
                    tetelek += [("Energiadíj – csúcs, kedvezményes", kedv - kv, ar_c), ("Energiadíj – völgy, kedvezményes", kv, ar_v)]
                    volgy_ft = fillerre((kv * ar_v + (piaci * ar_p + elsz * rhd) * volgy_arany) * szorzo)
                else:
                    netto = kr(kedv * ar_k) + kr(piaci * ar_p) + kr(elsz * rhd)
                    tetelek.append((f"Energiadíj{cimke}" + (" – kedvezményes" if keret is not None else ""), kedv, ar_k))
                if keret is not None:
                    tetelek.append((f"Energiadíj{cimke} – keret feletti (piaci)", piaci, ar_p))
                if rhd:
                    tetelek.append(("Rendszerhasználati díj", elsz, rhd))
                csat_netto = kr(q_szamla * csat_ar) if csat_ar else Decimal(0)
                if csat_ar:
                    tetelek.append(("Csatornadíj", q_szamla, csat_ar))
                energia_ft = fillerre((netto + csat_netto) * szorzo)
                csatorna_ft = fillerre(csat_netto * szorzo)
                # A havi alapdíj a számlán egy tétel: egyszer kerekítjük, és csak utána osztjuk szét.
                # (H-tarifánál nyáron az A1 alapdíja: a számla is azt a tételt kerekíti, nem a H sajátját.)
                havi_n = havi_ervenyes or alapdij_ho(sajat, fiok)
                arany = alapdij / havi_n if havi_n else Decimal(0)
                alapdij_ft = fillerre(kr(havi_n) * arany * szorzo)
                br_k, br_p = (ar_k + rhd) * szorzo, (ar_p + rhd) * szorzo
                egys = tar[sajat.azonosito].egyseg
                tetel_lista = [
                    {"nev": n, "mennyiseg": m, "egyseg": egys, "ar": ar, "netto": kr(m * ar), "afa": Decimal(afa)}
                    for n, m, ar in tetelek if m
                ]
                if arany:
                    tetel_lista.append({"nev": "Alapdíj", "mennyiseg": arany, "egyseg": "hó", "ar": kr(havi_n),
                                        "netto": kr(havi_n) * arany, "afa": Decimal(afa)})
                # Kiegészítő havi tételek saját ÁFA-kulccsal és hónapokkal (távhő: fűtési alapdíj, hődíj-átalány).
                for k_dij, k_db, k_afa, k_nev in kiegeszito_tetelek(sajat, fiok, fix_elsok, kr):
                    alapdij_ft += fillerre(k_dij * k_db * (1 + k_afa / 100))
                    tetel_lista.append({"nev": k_nev, "mennyiseg": Decimal(k_db), "egyseg": "hó", "ar": k_dij,
                                        "netto": k_dij * k_db, "afa": k_afa})
            else:
                csat = q_szamla * csat_ar if csat_ar else Decimal(0)
                energia_ft = fillerre(kedv * ar_k + piaci * ar_p + csat)
                csatorna_ft = fillerre(csat)
                alapdij_ft = fillerre(alapdij)
                br_k, br_p = ar_k, ar_p
                egys = tar[sajat.azonosito].egyseg
                tetel_lista = [{"nev": "Díj – kedvezményes" if keret is not None else "Díj", "mennyiseg": kedv, "egyseg": egys,
                                "ar": ar_k, "netto": kedv * ar_k, "afa": None}]
                if piaci:
                    tetel_lista.append({"nev": "Díj – keret feletti", "mennyiseg": piaci, "egyseg": egys, "ar": ar_p, "netto": piaci * ar_p, "afa": None})
                if csat:
                    tetel_lista.append({"nev": "Csatornadíj", "mennyiseg": q_szamla, "egyseg": egys, "ar": csat_ar, "netto": csat, "afa": None})
                if alapdij:
                    tetel_lista.append({"nev": "Alapdíj", "mennyiseg": Decimal(1), "egyseg": "", "ar": alapdij, "netto": alapdij, "afa": None})
                tetel_lista = [t for t in tetel_lista if t["mennyiseg"]]

            szeletek.append(
                SzeletEredmeny(
                    tol=a,
                    ig=b,
                    napok=napszam,
                    dijszabas_verzio=sajat.cimke,
                    idenyszak=idx,
                    mennyiseg=q,
                    kedvezmenyes=kedv,
                    piaci=piaci,
                    keret=keret,
                    energia_ft=energia_ft,
                    alapdij_ft=alapdij_ft,
                    egysegar_kedvezmenyes=br_k,
                    egysegar_piaci=br_p,
                    becsult=becsult,
                    csatorna=csatorna.szerep,
                    # Almérőnél az elszámolt (levont) mennyiség: egész m³-nél a kerekített, különben a nullázott elsz.
                    elszamolt=q_szamla if (csatorna.levonas_fobol and egesz) else elsz,
                    egyseg=tar[sajat.azonosito].egyseg,
                    keret_eves=tipus == "eves",
                    keret_evi=Decimal(keret_szabaly["ev_mennyiseg"]) if tipus == "eves" else None,
                    csatorna_ft=csatorna_ft,
                    savkorrekcio=savk,
                    volgy=(elsz * volgy_arany) if volgy_arany is not None else None,
                    volgy_ft=volgy_ft,
                    tetelek=tetel_lista,
                )
            )
    return IdoszakEredmeny(tol=tol, ig=ig, szeletek=szeletek, becsult=becsult_ossz)


def _szabaly(
    sajat: Ervenyes, nap: date, tar: DijszabasTar, fiok: Fiok, szerep: str = "vetelezes"
) -> tuple[dict[str, Decimal], dict[str, Any] | None, str, str | None]:
    """(árak, keret-szabály, ár-kulcs keret nélkül, idényszak neve) egy napra.

    Ha a csatorna egy idényszak saját regisztere (pl. H-tarifa: „h_teli” = 1.81, „h_nyari” = 1.82), az idényszakot
    a regiszter adja, nem a dátum – a mérő is így számol.
    """
    if szerep.startswith(ZONA):  # A2: a zóna saját kedvezményes ára, a díjszabás kerete (közös)
        zona = next((z for z in sajat.szabalyok.get("zonak") or [] if f"{ZONA}{z['nev']}" == szerep), None)
        if zona:
            return sajat.dijak, _modhoz(fiok, sajat.szabalyok.get("keret")), zona["ar"], zona["nev"]
    idenyek = sajat.szabalyok.get("idenyszak") or []
    regiszter = next((x for x in idenyek if szerep == f"h_{x.get('nev')}"), None)
    sz = regiszter or idenyszak(nap, idenyek)
    if sz is None:
        return sajat.dijak, _modhoz(fiok, sajat.szabalyok.get("keret")), sajat.szabalyok.get("ar", "energia_kedvezmenyes"), None
    if sz.get("dijszabas"):
        masik = tar.felold(sz["dijszabas"], nap, fiok.szolgaltato, fiok.feluliras)
        keret = _modhoz(fiok, masik.szabalyok.get("keret")) if sz.get("sajat_keret", True) else {"tipus": "nincs"}
        return masik.dijak, keret, masik.szabalyok.get("ar", "energia_kedvezmenyes"), sz["nev"]
    return sajat.dijak, _modhoz(fiok, sz.get("keret")), sz.get("ar", "energia_kedvezmenyes"), sz["nev"]
