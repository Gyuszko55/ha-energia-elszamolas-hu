"""Az elszámoló motor adattípusai. Tiszta Python, Home Assistant nélkül."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum


class Kozmu(StrEnum):
    VILLANY = "villany"
    GAZ = "gaz"
    VIZ = "viz"
    HULLADEK = "hulladek"  # fix díjas, mérő nélkül
    TAVKOZLES = "tavkozles"  # internet, TV, telefon: fix havi előfizetés, havi számlával
    KOZOS = "kozos"  # társasházi közös költség: fix havi díj (közgyűlési határozat), számla helyett havi előírás
    TAVHO = "tavho"  # távhő: mért melegvíz (m³) + fűtési alapdíj és hődíj-átalány havi tételként


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
    ido: time | None = None  # a leolvasás időpontja (ha ismert); nélküle a nap eleje

    @property
    def idopont(self) -> datetime:
        """A számlálóban a leolvasás helye: a megadott időpont, különben a nap eleje (00:00)."""
        return datetime.combine(self.datum, self.ido or time.min)


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
    # Átalányos (egyenletes részszámlás) fizetés: a díjszabás keretének „reszszamla” változata érvényes (gáz: éves keret
    # a havi súlyozott helyett).
    reszszamlas: bool = False
    # A kedvezményes keret szorzója (gáz, fogyasztói közösség: társasház (lakásszám + 1), családi közösség lakásszám).
    keret_szorzo: Decimal = Decimal(1)
    # Díjszabásban „alapdij.szorzo”-ként hivatkozott fiókadatok (pl. gáz B1: gazmero_teljesitmeny m³/h).
    szorzok: dict[str, Decimal] = field(default_factory=dict)
    # A2 regiszter-szenzorok nélkül: a fogyasztás-szenzor órás adataiból naponként (völgy, összes) kWh – ebből bontja
    # a motor csúcsra és völgyre; ahol nincs adat, az órák arányából becsül.
    zona_napok: dict[date, tuple[Decimal, Decimal]] = field(default_factory=dict)
    # D árszabás (és a „mi lenne D-n” összevetés): naponként (fogyasztás, fogyasztás × rugalmas ár, becsült) órás
    # adatból; naponkénti átlagár a fogyasztás nélküli napokra; a legutóbbi közzétett hónap súlyozott ára tartaléknak.
    d_napok: dict[date, tuple[Decimal, Decimal, bool]] = field(default_factory=dict)
    d_ar_napok: dict[date, Decimal] = field(default_factory=dict)
    d_tartalek: Decimal | None = None
    futoertekek: dict[str, Decimal] = field(default_factory=dict)  # gáz: {"ÉÉÉÉ-HH": MJ/m³}
    # Gáz: az elszámoló számlák korrekciós tényezője hónaponként; a többi hónapra a legutóbbi elszámolóé (a következő
    # elszámoló várhatóan ezzel számol), ennek híján a díjszabás alapértéke.
    korrekciok: dict[str, Decimal] = field(default_factory=dict)
    # Az összesített keret kerekítési pontjai (MVM: a keret számlánként, ill. tételenként kerekítve jár): a számlázási
    # időszakok határai (diktálásnál a diktálások), naptári havi számlázásnál „szamlazas_havi”. Üresen: az évkezdettől
    # halmozott keret kerekítve (a régi viselkedés).
    szamlazasi_hatarok: tuple[date, ...] = ()
    szamlazas_havi: bool = False
    # Az elszámoló (éves) leolvasások napjai: az összesített kedvezményes keret (sávkorrekció) évhatárai.
    elszamolasi_napok: tuple[date, ...] = ()
    # A számlázási ütem hónapokban (1 havi, 2 kéthavi, 4 négyhavi …; 0: ismeretlen). A díjszabás „mennyiseg_minimum”
    # szabálya (pl. víz, távhős melegvíz: legalább 1 m³ számlánként) csak egy teljes számlázási időszakra jár.
    szamla_honap: int = 0
    # Sajátos számlázás (pl. üdülő): a számlánkénti minimális mennyiség nem jár.
    minimum_mentes: bool = False
    # Szüneteltetett számlázás (pl. lakatlan ingatlan: haláleset, katasztrófa): [tol, ig) időszakok – ig None: tart.
    # Ezekre a napokra semmi nem jár (fogyasztás, alapdíj, minimum), és számla sem várható.
    szunetel: tuple[tuple[date, date | None], ...] = ()

    def szunetel_nap(self, nap: date) -> bool:
        return any(a <= nap and (b is None or nap < b) for a, b in self.szunetel)


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
    keret_eves: bool = False  # éves keret: a „keret” a szelet elején még hátralévő éves mennyiség (nem összeadható)
    # Összesített keretnél: a kedvezményes mennyiség eltérése a csak erre a szeletre járó kerettől (az MVM számláján
    # „sávkorrekció”) – pozitív: a korábban ki nem használt keret most piaci helyett kedvezményes áron jár.
    savkorrekcio: Decimal = Decimal(0)
    keret_evi: Decimal | None = None
    volgy: Decimal | None = None  # A2 egy csatornán: a völgyidőszaki rész (a többi csúcs)
    volgy_ft: Decimal = Decimal(0)  # ennek energiadíja (az energia_ft része)
    # Számlaszerű tételsorok (tájékoztató bontás): [{nev, mennyiseg, egyseg, ar (nettó egységár), netto, afa}];
    # bruttó díjszabásnál (ÁFA nélkül megadott árak) afa=None és az ár bruttó.
    tetelek: list = field(default_factory=list)  # éves keretnél a teljes éves mennyiség (a panel éves csíkjához)

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
