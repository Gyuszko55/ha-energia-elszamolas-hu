"""Napelemes (HMKE) fiók: vételezés és betáplálás elszámolása.

- Bruttó (2024-től): a vételezés a rendes díjszabás szerint (keret, alapdíj), a betáplálás külön, átvételi áron jóváírva.
- Szaldó (az üzembe helyezéstől 10 évig): évente a vételezés és a betáplálás különbsége számít. Vételezési
  többletnél a nettó mennyiség a rendes díjszabás szerint (éves kerettel), betáplálási többletnél a többlet
  alacsony átvételi áron jóváírva. Az alapdíj mindkét esetben jár.
Források és ellenőrizendő pontok: dijszabasok/villany/hmke.yaml.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from .dijszabas import DijszabasTar
from .egyenleg import _profil_resz, alapdij_osszeg
from .elszamolas import fillerre, honap_kezdetek, kerekit, szamol
from .szamlalo import Pont, Szamlalo, nap_kezdete
from .tipusok import Fiok, IdoszakEredmeny

HMKE = "villany/hmke"


@dataclass
class NapelemEredmeny:
    mod: str
    tol: date
    ig: date
    vetelezes: Decimal
    betaplalas: Decimal
    elszamolt_vetelezes: Decimal  # bruttónál a teljes vételezés, szaldónál a nettó (ha pozitív)
    tobblet: Decimal  # szaldónál a betáplálási többlet
    energia_ft: Decimal  # a vételezés energia- és rendszerhasználati díja
    alapdij_ft: Decimal
    jovairas_ft: Decimal  # a betáplálásért járó összeg (pozitív)
    becsult: bool

    @property
    def egyenleg_ft(self) -> Decimal:
        """Fizetendő (pozitív) vagy jóváírandó (negatív) összeg."""
        return kerekit(self.energia_ft + self.alapdij_ft - self.jovairas_ft)


def _ar(tar: DijszabasTar, fiok: Fiok, nap: date, kulcs: str) -> Decimal:
    return tar.felold(HMKE, nap, fiok.szolgaltato, fiok.feluliras).dijak[kulcs]


def _vetelezo_fiok(fiok: Fiok) -> Fiok:
    return dataclasses.replace(fiok, csatornak=fiok.csatornak[:1])


def brutto(
    fiok: Fiok, tar: DijszabasTar, tol: date, ig: date, vetel: Szamlalo, betap: Szamlalo, meres_vege: datetime | None = None
) -> NapelemEredmeny:
    """Bruttó elszámolás egy (havi) időszakra."""
    r: IdoszakEredmeny = szamol(_vetelezo_fiok(fiok), tar, tol, ig, [vetel], meres_vege=meres_vege)
    vege = min(meres_vege, nap_kezdete(ig)) if meres_vege else nap_kezdete(ig)
    q_be, becsult = betap.fogyasztas(nap_kezdete(tol), vege) if nap_kezdete(tol) < vege else (Decimal(0), False)
    q_be = max(q_be, Decimal(0))
    return NapelemEredmeny(
        mod="brutto", tol=tol, ig=ig, vetelezes=r.mennyiseg, betaplalas=q_be, elszamolt_vetelezes=r.mennyiseg,
        tobblet=Decimal(0), energia_ft=r.energia_ft, alapdij_ft=r.alapdij_ft,
        jovairas_ft=fillerre(q_be * _ar(tar, fiok, tol, "betaplalas_brutto")), becsult=r.becsult or becsult,
    )


def szaldo(
    fiok: Fiok, tar: DijszabasTar, ev_tol: date, ev_ig: date, vetel: Szamlalo, betap: Szamlalo, meres_vege: datetime | None = None
) -> NapelemEredmeny:
    """Szaldó elszámolás egy elszámolási évre (vagy annak eddigi részére: „ha ma lenne az elszámolás”)."""
    vege = min(meres_vege, nap_kezdete(ev_ig)) if meres_vege else nap_kezdete(ev_ig)
    q_ve, b1 = vetel.fogyasztas(nap_kezdete(ev_tol), vege)
    q_be, b2 = betap.fogyasztas(nap_kezdete(ev_tol), vege)
    q_ve, q_be = max(q_ve, Decimal(0)), max(q_be, Decimal(0))
    netto = q_ve - q_be
    # Annyi havi alapdíj, ahány hónap 1-je az [ev_tol, vege) időbe esik (mint „alapdij.mod: idoszakonkent”-nél) –
    # egy nem 1-jén kezdődő évre is 12, nem 13; év közben a mai 1-je már jár; hónaponként a saját díjjal (H-tarifa:
    # nyáron az A1-é).
    elsok = {x for x in honap_kezdetek(ev_tol, vege.date() + timedelta(days=1)) | ({ev_tol} if ev_tol.day == 1 else set())
             if nap_kezdete(x) < vege}
    alapdij = fillerre(alapdij_osszeg(fiok, tar, {x for x in elsok if not fiok.szunetel_nap(x)}))
    if netto > 0:
        # A nettó vételezés az év során egyenletesen: a napi arányos keret így az egész évre (2 523 kWh) jön ki.
        nettoszamlalo = Szamlalo([Pont(nap_kezdete(ev_tol), Decimal(0), True), Pont(vege, netto, True)])
        # Év közben („ha ma lenne az elszámolás”) a keret az eltelt napokkal arányos.
        ig = max(vege.date(), date.fromordinal(ev_tol.toordinal() + 1))
        r = szamol(_vetelezo_fiok(fiok), tar, ev_tol, ig, [nettoszamlalo], meres_vege=vege)
        energia, jovairas, tobblet = r.energia_ft, Decimal(0), Decimal(0)
    else:
        tobblet = -netto
        energia, jovairas = Decimal(0), fillerre(tobblet * _ar(tar, fiok, ev_tol, "szaldo_tobblet"))
    return NapelemEredmeny(
        mod="szaldo", tol=ev_tol, ig=ev_ig, vetelezes=q_ve, betaplalas=q_be, elszamolt_vetelezes=max(netto, Decimal(0)),
        tobblet=tobblet, energia_ft=energia, alapdij_ft=alapdij, jovairas_ft=jovairas, becsult=b1 or b2,
    )


def idoszak_betaplalas(betap: Szamlalo, tol: date, ig: date, most: datetime) -> dict[str, float]:
    """Szaldós fiók folyó időszaka: az eddigi és a várható betáplálás. A még hátralévő rész a tavalyi ugyanazon
    napoké, ha van rá adat; különben az eddigi a napelemes havi profillal az egész időszakra vetítve."""
    t0, t1 = datetime.combine(tol, datetime.min.time()), datetime.combine(ig, datetime.min.time())
    vege = min(max(most, t0), t1)
    eddig = max(betap.fogyasztas(t0, vege)[0], Decimal(0)) if vege > t0 else Decimal(0)
    ev = timedelta(days=365)
    if betap.pontok and betap.pontok[0].ido <= vege - ev and vege < t1:
        varhato = eddig + max(betap.fogyasztas(vege - ev, t1 - ev)[0], Decimal(0))
    else:
        resz_eddig = _profil_resz(tol, vege.date(), "napelem")
        varhato = eddig * _profil_resz(tol, ig, "napelem") / resz_eddig if resz_eddig > 0 and (vege - t0).days >= 3 else eddig
    return {"eddig": round(float(eddig), 1), "varhato": round(float(varhato), 1)}
