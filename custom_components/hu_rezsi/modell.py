"""A beállításokból és a tárolt adatokból motor-objektumok (Fiok, Szamlalo) építése."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from .const import (
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


def d(x: Any) -> date | None:
    if x is None or x == "":
        return None
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def dec(x: Any) -> Decimal | None:
    return None if x is None or x == "" else Decimal(str(x))


def kezdo_mero(beallitas: dict[str, Any]) -> dict[str, Any]:
    """Az első mérő a fiók beállításából (új fióknál)."""
    return {
        "gyari_szam": beallitas.get(CONF_GYARI_SZAM) or "",
        "beepitve": str(beallitas[CONF_BEEPITVE]),
        "kezdo_allas": str(beallitas.get(CONF_KEZDO_ALLAS) or 0),
        "kiszerelve": None,
        "zaro_allas": None,
        "leolvasasok": [],
    }


def kezdo_almero(beallitas: dict[str, Any]) -> dict[str, Any]:
    """Víz: a locsolási almérő első mérője a fiók beállításából."""
    return {
        "gyari_szam": "",
        "beepitve": str(beallitas.get(CONF_ALMERO_BEEPITVE) or beallitas[CONF_BEEPITVE]),
        "kezdo_allas": str(beallitas.get(CONF_ALMERO_KEZDO) or 0),
        "kiszerelve": None,
        "zaro_allas": None,
        "leolvasasok": [],
    }


def mero_motorba(m: dict[str, Any], csatorna: str = "vetelezes") -> Mero:
    """Egy mérő egy regisztere (csatornája): vételezés (1.8.0) vagy betáplálás (2.8.0)."""
    be = csatorna == "betaplalas"
    return Mero(
        gyari_szam=m.get("gyari_szam", ""),
        beepitve=d(m["beepitve"]),
        kezdo_allas=dec(m.get("kezdo_betaplalas" if be else "kezdo_allas")) or Decimal(0),
        kiszerelve=d(m.get("kiszerelve")),
        zaro_allas=dec(m.get("zaro_betaplalas" if be else "zaro_allas")),
        leolvasasok=[
            Leolvasas(
                datum=d(lo["datum"]),
                allas=dec(lo["allas"]),
                tipus=LeolvasasTipus(lo.get("tipus", "kezi")),
                elszamolasi=bool(lo.get("elszamolasi")),
                megjegyzes=lo.get("megjegyzes", ""),
            )
            for lo in m.get("leolvasasok", [])
            if lo.get("csatorna", "vetelezes") == csatorna
        ],
    )


def eves_bazis(tarolt: dict[str, Any]) -> date | None:
    """Az utolsó elszámoló (éves) leolvasás napja; ha nincs, az első mérő beépítése."""
    napok = [d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("elszamolasi")]
    if napok:
        return max(napok)
    return d(tarolt["merok"][0]["beepitve"]) if tarolt["merok"] else None


def elszamolasi_napok(tarolt: dict[str, Any]) -> set[date]:
    return {d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("elszamolasi")}


def fiok_motorba(beallitas: dict[str, Any], tarolt: dict[str, Any]) -> Fiok:
    return Fiok(
        kozmu=Kozmu(beallitas[CONF_KOZMU]),
        szolgaltato=beallitas[CONF_SZOLGALTATO],
        dijszabasok=[DijszabasHozzarendeles(beallitas[CONF_DIJSZABAS], d(beallitas[CONF_DIJSZABAS_TOL]))],
        csatornak=[
            Csatorna(
                merok=[mero_motorba(m) for m in tarolt["merok"]],
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
        futoertekek={k: Decimal(str(v)) for k, v in (tarolt.get("futoertekek") or {}).items()},
    )


def betaplalas_csatorna(tarolt: dict[str, Any]) -> Csatorna:
    """Napelemes fiók: az ad-vesz mérő betáplálási regisztere (2.8.0), keret nélkül."""
    return Csatorna(szerep="betaplalas", merok=[mero_motorba(m, "betaplalas") for m in tarolt["merok"]], keret_aktiv=False)


def elozo_bazis(tarolt: dict[str, Any]) -> date | None:
    """Az utolsó előtti elszámoló leolvasás napja (az előző elszámolási év kezdete)."""
    napok = sorted({d(lo["datum"]) for m in tarolt["merok"] for lo in m.get("leolvasasok", []) if lo.get("elszamolasi")})
    return napok[-2] if len(napok) >= 2 else None


def eredmeny_tarolhato(e) -> dict[str, Any]:
    """IdoszakEredmeny → JSON-barát dict (a lezárt időszakokhoz)."""
    return {
        "tol": e.tol.isoformat(),
        "ig": e.ig.isoformat(),
        "mennyiseg": str(e.mennyiseg),
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
        "keret": None if s.keret is None else round(float(s.keret), 3),
        "energia_ft": float(s.energia_ft),
        "alapdij_ft": float(s.alapdij_ft),
        "ar_kedvezmenyes": float(s.egysegar_kedvezmenyes),
        "ar_piaci": float(s.egysegar_piaci),
        "becsult": s.becsult,
    }
