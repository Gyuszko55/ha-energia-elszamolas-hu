"""Az elszámoló motor adattípusai. Tiszta Python, Home Assistant nélkül."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Kozmu(StrEnum):
    VILLANY = "villany"
    GAZ = "gaz"
    VIZ = "viz"


class LeolvasasTipus(StrEnum):
    SZOLGALTATOI = "szolgaltatoi"
    KEZI = "kezi"
    AUTOMATIKUS = "automatikus"


# Ugyanarra a napra több leolvasásnál ez dönt (nagyobb = erősebb).
LEOLVASAS_ELSOBBSEG = {
    LeolvasasTipus.SZOLGALTATOI: 3,
    LeolvasasTipus.KEZI: 2,
    LeolvasasTipus.AUTOMATIKUS: 1,
}


@dataclass(frozen=True)
class Leolvasas:
    datum: date
    allas: Decimal
    tipus: LeolvasasTipus = LeolvasasTipus.KEZI
    elszamolasi: bool = False
    megjegyzes: str = ""


@dataclass
class Mero:
    """Fizikai mérőóra. Mérőcserekor a régi lezárul (kiszerelve), és új mérő nyílik."""

    gyari_szam: str
    beepitve: date
    kezdo_allas: Decimal = Decimal(0)
    kiszerelve: date | None = None
    zaro_allas: Decimal | None = None
    leolvasasok: list[Leolvasas] = field(default_factory=list)


@dataclass
class Csatorna:
    szerep: str = "vetelezes"
    merok: list[Mero] = field(default_factory=list)
    keret_aktiv: bool = True
    csatornadij_aktiv: bool = True  # víz: locsolási almérőnél kikapcsolva
    levonas_fobol: bool = False  # víz: almérő a főmérő mögött – a mennyisége a csatornadíjból levonódik


@dataclass(frozen=True)
class DijszabasHozzarendeles:
    dijszabas: str
    ervenyes_tol: date
    ervenyes_ig: date | None = None


@dataclass(frozen=True)
class Feluliras:
    """Egy díj vagy szabály-paraméter felülírása dátumtól, pl. kulcs='dijak.energia_kedvezmenyes'."""

    kulcs: str
    ertek: Decimal
    ervenyes_tol: date


@dataclass
class Fiok:
    kozmu: Kozmu
    szolgaltato: str
    dijszabasok: list[DijszabasHozzarendeles]
    csatornak: list[Csatorna]
    feluliras: list[Feluliras] = field(default_factory=list)
    eves_bazis: date | None = None  # az utolsó éves elszámoló leolvasás napja (éves kerethez)
    futoertekek: dict[str, Decimal] = field(default_factory=dict)  # gáz: {"ÉÉÉÉ-HH": MJ/m³}


@dataclass
class SzeletEredmeny:
    tol: date
    ig: date  # kizárólagos
    napok: Decimal
    dijszabas_verzio: str
    idenyszak: str | None
    mennyiseg: Decimal
    kedvezmenyes: Decimal
    piaci: Decimal
    keret: Decimal | None
    energia_ft: Decimal
    alapdij_ft: Decimal
    egysegar_kedvezmenyes: Decimal
    egysegar_piaci: Decimal
    becsult: bool
    csatorna: str = "vetelezes"
    elszamolt: Decimal | None = None  # elszámolási egységben (gáznál MJ); None = mennyiseg
    egyseg: str = ""
    csatorna_ft: Decimal = Decimal(0)  # víz: ebből a csatornadíj (az energia_ft része)

    @property
    def osszesen_ft(self) -> Decimal:
        return self.energia_ft + self.alapdij_ft


def _ft(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)


@dataclass
class IdoszakEredmeny:
    tol: date
    ig: date  # kizárólagos
    szeletek: list[SzeletEredmeny]
    becsult: bool

    @property
    def mennyiseg(self) -> Decimal:
        return sum((s.mennyiseg for s in self.szeletek), Decimal(0))

    # A szeletek fillérre pontosak; az időszak összegei forintra kerekítve.
    @property
    def energia_ft(self) -> Decimal:
        return _ft(sum((s.energia_ft for s in self.szeletek), Decimal(0)))

    @property
    def alapdij_ft(self) -> Decimal:
        return _ft(sum((s.alapdij_ft for s in self.szeletek), Decimal(0)))

    def energia_ft_ahol(self, **feltetel) -> Decimal:
        """Részösszeg forintra kerekítve, pl. energia_ft_ahol(idenyszak="teli")."""
        return _ft(
            sum(
                (s.energia_ft for s in self.szeletek if all(getattr(s, k) == v for k, v in feltetel.items())),
                Decimal(0),
            )
        )

    @property
    def osszesen_ft(self) -> Decimal:
        return _ft(sum((s.energia_ft + s.alapdij_ft for s in self.szeletek), Decimal(0)))
