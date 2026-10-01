"""Az elszámoló motor: egy fiók egy időszakának költsége szeletekre bontva.

Lépések (docs/terv/03_ELSZAMOLO_MOTOR.md): szeletelés → fogyasztás → keret → díjak.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .dijszabas import DijszabasHiba, DijszabasTar, Ervenyes
from .szamlalo import Szamlalo, nap_kezdete
from .tipusok import Fiok, IdoszakEredmeny, SzeletEredmeny

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


def atvalt(q: Decimal, nap: date, atv: dict[str, Any] | None, fiok: Fiok) -> tuple[Decimal, bool]:
    """Mért mennyiség → elszámolási mennyiség. Gáz: m³ × korrekció × fűtőérték, egész MJ-ra kerekítve."""
    if not atv:
        return q, False
    if atv.get("tipus") != "gaz_mj":
        raise DijszabasHiba(f"ismeretlen átváltás: {atv.get('tipus')}")
    fe, becsult = futoertek(nap, atv, fiok)
    korr = Decimal(atv.get("korrekcios_tenyezo_alap", 1))
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


def szamol(
    fiok: Fiok,
    tar: DijszabasTar,
    tol: date,
    ig: date,
    szamlalok: list[Szamlalo],
    meres_vege: datetime | None = None,
    extra_hatarok: set[date] | None = None,
) -> IdoszakEredmeny:
    """A [tol, ig) időszak elszámolása.

    szamlalok: csatornánként egy számláló, a fiok.csatornak sorrendjében.
    meres_vege: eddig van mért fogyasztás (nyitott időszaknál „most”). A keret és az alapdíj
    ettől függetlenül a teljes szeletre jár, ahogy a számlán is.
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
    if any(v.szabalyok.get("atvaltas") for h in fiok.dijszabasok for v in tar[h.dijszabas].verziok):
        hatarok |= honap_kezdetek(tol, ig)  # a fűtőérték havonta változik: a számla is hónaponként bont
    napok = sorted(d for d in hatarok if tol <= d <= ig)

    szeletek: list[SzeletEredmeny] = []
    becsult_ossz = False
    for ci, (csatorna, szamlalo) in enumerate(zip(fiok.csatornak, szamlalok, strict=True)):
        for a, b in zip(napok, napok[1:]):
            sajat = tar.felold(_hozzarendeles(fiok, a), a, fiok.szolgaltato, fiok.feluliras)
            arak, keret_szabaly, ar_kulcs, idx = _szabaly(sajat, a, tar, fiok)

            ta, tb = nap_kezdete(a), min(nap_kezdete(b), vege)
            if ta < tb:
                q, becsult = szamlalo.fogyasztas(ta, tb)
            else:
                q, becsult = Decimal(0), False
            q = max(q, Decimal(0))
            atv = sajat.szabalyok.get("atvaltas")
            elsz, becsult_fe = atvalt(q, a, atv, fiok)
            becsult = becsult or becsult_fe
            becsult_ossz |= becsult

            napszam = Decimal((b - a).days)
            keret: Decimal | None
            tipus = (keret_szabaly or {}).get("tipus", "nincs")
            if not csatorna.keret_aktiv and tipus != "nincs":
                keret = Decimal(0)
            elif tipus == "napi_aranyos":
                keret = _napi_keret(keret_szabaly) * napszam
                if keret_szabaly.get("kerekites") is not None:  # pl. MVM: egész kWh-ra
                    keret = keret.quantize(Decimal(1).scaleb(-int(keret_szabaly["kerekites"])), rounding=ROUND_HALF_UP)
            elif tipus == "eves":
                if fiok.eves_bazis is None:
                    raise DijszabasHiba("éves kerethez meg kell adni a fiók éves bázisdátumát")
                felhasznalt = elszamolt_mennyiseg(szamlalo, fiok.eves_bazis, a, atv, fiok)
                keret = max(Decimal(keret_szabaly["ev_mennyiseg"]) - felhasznalt, Decimal(0))
            else:
                keret = None

            if keret is None:
                kedv, piaci = elsz, Decimal(0)
                ar_k, ar_p = arak[ar_kulcs], arak.get("energia_piaci", Decimal(0))
            else:
                kedv, piaci = min(elsz, keret), max(elsz - keret, Decimal(0))
                ar_k, ar_p = arak["energia_kedvezmenyes"], arak["energia_piaci"]

            # Víz: csatornadíj a mért mennyiség után (csatornánként kikapcsolható, pl. locsolási almérő).
            csat_ar = arak.get("csatorna_m3") if sajat.szabalyok.get("csatornadij") and csatorna.csatornadij_aktiv else None
            rhd = arak.get("rendszerhasznalati") or Decimal(0)

            alapdij = Decimal(0)
            if ci == 0:  # az alapdíj a fiókot terheli, nem csatornánként
                havi = sajat.dijak.get("alapdij_ho") or Decimal(0)
                if (sajat.szabalyok.get("alapdij") or {}).get("mod") == "idoszakonkent":
                    # Számlánként (havi időszakonként) egy teljes havi alapdíj, a szeletek között napok szerint.
                    alapdij = havi * napszam / Decimal((ig - tol).days)
                else:
                    alapdij = havi * honap_aranya(a, b)

            afa = arak.get("afa")
            if afa is not None:
                # Nettó díjak: a számla tételsoronként forintra kerekít, az ÁFA a nettóra jön.
                szorzo = 1 + Decimal(afa) / 100
                netto = kerekit(kedv * ar_k) + kerekit(piaci * ar_p) + kerekit(elsz * rhd)
                csat_netto = kerekit(q * csat_ar) if csat_ar else Decimal(0)
                energia_ft = fillerre((netto + csat_netto) * szorzo)
                csatorna_ft = fillerre(csat_netto * szorzo)
                # A havi alapdíj a számlán egy tétel: egyszer kerekítjük, és csak utána osztjuk szét.
                havi_n = sajat.dijak.get("alapdij_ho") or Decimal(0)
                arany = alapdij / havi_n if havi_n else Decimal(0)
                alapdij_ft = fillerre(kerekit(havi_n) * arany * szorzo)
                br_k, br_p = (ar_k + rhd) * szorzo, (ar_p + rhd) * szorzo
            else:
                csat = q * csat_ar if csat_ar else Decimal(0)
                energia_ft = fillerre(kedv * ar_k + piaci * ar_p + csat)
                csatorna_ft = fillerre(csat)
                alapdij_ft = fillerre(alapdij)
                br_k, br_p = ar_k, ar_p

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
                    elszamolt=elsz,
                    egyseg=tar[sajat.azonosito].egyseg,
                    csatorna_ft=csatorna_ft,
                )
            )
    return IdoszakEredmeny(tol=tol, ig=ig, szeletek=szeletek, becsult=becsult_ossz)


def _szabaly(
    sajat: Ervenyes, nap: date, tar: DijszabasTar, fiok: Fiok
) -> tuple[dict[str, Decimal], dict[str, Any] | None, str, str | None]:
    """(árak, keret-szabály, ár-kulcs keret nélkül, idényszak neve) egy napra."""
    sz = idenyszak(nap, sajat.szabalyok.get("idenyszak") or [])
    if sz is None:
        return sajat.dijak, sajat.szabalyok.get("keret"), sajat.szabalyok.get("ar", "energia_kedvezmenyes"), None
    if sz.get("dijszabas"):
        masik = tar.felold(sz["dijszabas"], nap, fiok.szolgaltato, fiok.feluliras)
        keret = masik.szabalyok.get("keret") if sz.get("sajat_keret", True) else {"tipus": "nincs"}
        return masik.dijak, keret, masik.szabalyok.get("ar", "energia_kedvezmenyes"), sz["nev"]
    return sajat.dijak, sz.get("keret"), sz.get("ar", "energia_kedvezmenyes"), sz["nev"]
