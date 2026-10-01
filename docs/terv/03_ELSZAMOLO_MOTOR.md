# 03 – Az elszámoló motor

## Feladata

Bemenet: egy szolgáltatói fiók, egy időszak, a leolvasások és a díjszabások.
Kimenet: mennyiségek és forintok bontásban, plusz előrejelzés.

A motor **tiszta Python, HA-függőség nélkül** (`hu_rezsi/motor/`). A HA-réteg csak adatot ad neki és
megjeleníti az eredményt. Így a motor önállóan, gyorsan tesztelhető.

## Lépések

```
1. Időszak  →  2. Fogyasztás  →  3. Szeletelés  →  4. Keret  →  5. Díjak  →  6. Eredmény
                                                                            ↘  7. Előrejelzés
```

### 1. Időszak meghatározása

| `idoszak_mod` | Időszak |
|---|---|
| `naptari_honap` | Hónap 1-jétől a következő hónap 1-jéig (a v1 működése) |
| `egyedi_nap` | Pl. minden hónap 12-étől 12-éig, a szolgáltató számlázási ciklusához igazítva |
| `leolvasas_alapu` | Két `elszamolasi: igen` leolvasás között; a nyitott időszak az utolsó ilyen leolvasástól tart |

Az éves elszámolás (pl. gázkeret) a fiók **éves bázisdátumától** számít, ami az utolsó éves elszámoló leolvasás napja.

### 2. Fogyasztás csatornánként

- Mérőnként: az időszak végi állás − kezdő állás. A mérők fogyasztása a fiók szintjén összeadódik, így a mérőcsere magától kezelődik.
- **Állás egy adott napon**, csökkenő elsőbbséggel:
  1. leolvasás azon a napon,
  2. a HA hosszú távú statisztikája (óránkénti `sum`) a forrás-entitásból, szorzóval, a legközelebbi leolvasáshoz igazítva,
  3. lineáris becslés két leolvasás között, „becsült” jelöléssel.
- A korrekció-típusú leolvasás az utána következő állásokat tolja el (a v1 „korrekció” mezőjének megfelelője).

### 3. Szeletelés

Az időszakot ott kell szeletekre vágni, ahol a számítás szabálya változik:

- díjszabás-verzió hatálybalépése (pl. január 1-jei díjemelés),
- díjszabás-hozzárendelés változása (tarifaváltás),
- idényhatár (H-tarifa: okt. 15., ápr. 15.),
- éves elszámoló leolvasás az időszak közepén (a v1 „megosztott hónap” esete).

Minden szelet saját napszámot, saját fogyasztást (a 2. lépés szerint) és saját díjakat kap.
**A v1 bevált megoldása általánosítva:** ott a hónap egy leolvasásnál két részre oszlott, itt bármilyen határnál
akárhány szeletre bomolhat.

### 4. Keret

| Kerettípus | Számítás |
|---|---|
| `napi_aranyos` | keret = (éves mennyiség ÷ 365) × a szelet napjai. Szeletenként külön. |
| `eves` | Egy közös éves keret az éves bázisdátumtól. A szelet a még fel nem használt részből gazdálkodik. |
| `nincs` | Minden mennyiség egy áron. |

- A keret **csatornánként** jár, ha a csatornán `keret_aktiv: igen` (a v1-ben: A1 és H nyári külön keret).
- A keret feletti mennyiség a `hatar_felett` ár szerint számolódik.
- **Hátralévő keret** = az időszak (vagy év) kerete − eddigi fogyasztás. Ez a felület „Hol tartok?” kérdésére ad választ.

### 5. Díjak alkalmazása

Szeletenként: a díjszabás aktuális verziója → a szolgáltatói sor → a fiók- és csatorna-felülírások (lásd 02).
Az alapdíj a szelet napjaival arányos (a v1-ben is így van).

Közmű-specifikus lépések a modulokban:

- **gáz:** m³ × korrekciós tényező × fűtőérték = MJ, utána díjazás MJ-ban;
- **víz:** vízdíj + csatornadíj (ha a csatornán be van kapcsolva) + alapdíj;
- **napelem (3. lépcső):** a vételezés és a betáplálás összevetése az elszámolási mód szerint, keret előtt.

### 6. Eredmény

```python
@dataclass
class SzeletEredmeny:
    tol: date
    ig: date
    napok: int
    dijszabas_verzio: str         # pl. "villany/a1@2026-01-01"
    mennyiseg: Decimal            # elszámolási egységben
    kedvezmenyes: Decimal
    piaci: Decimal
    keret: Decimal
    energia_ft: Decimal
    alapdij_ft: Decimal
    egyeb_ft: dict[str, Decimal]  # pl. {"csatornadij": …}
    becsult: bool                 # volt-e becsült állás a számításban

@dataclass
class IdoszakEredmeny:
    tol: date
    ig: date
    szeletek: list[SzeletEredmeny]
    eddig_ft: Decimal
    varhato_ft: Decimal
    hatralevo_keret: Decimal
    varhato_keretatlepes: date | None
    figyelmeztetesek: list[str]
```

Pénzhez és mennyiséghez `Decimal` kell, nem `float`, hogy a kerekítés pontosan egyezzen a számlával.
A kerekítési szabály (szeletenként vagy összesítve) díjszabás-paraméter legyen.

### 7. Előrejelzés

- **1. lépcső (a v1 módszere):** az utolsó 7 nap napi átlaga × a hátralévő napok. A H-tarifánál a hátralévő napok idényenként külön számolnak.
- **4. lépcső:** választható módszerek:
  - tavalyi azonos időszak a HA statisztikájából, idei szintre arányosítva,
  - gáznál fűtési napfok alapján (külső hőmérséklet-entitásból),
  - a várható keretátlépés napja: amikor a halmozott előrejelzés eléri a keretet.

A módszer fiókonként választható, és az eredmény mellett megjelenik, melyik készítette.

## Részszámlás fiók: éves egyenleg

Az elszámolási év az éves bázisdátumtól (utolsó elszámoló leolvasás) a következő várható leolvasásig tart.

```
befizetve        = az év eddigi részszámláinak összege
hátralévő        = az év még hátralévő részszámlái (rögzített terv vagy az utolsó összeg × hátralévő hónapok)
tényleges eddig  = a mért fogyasztás költsége az év elejétől (szeletek, éves keret, alapdíjak)
várható éves     = tényleges eddig + előrejelzés a következő éves leolvasásig
várható egyenleg = befizetve + hátralévő − várható éves     (> 0: visszatérítés, < 0: ráfizetés)
```

- A gáz előrejelzésénél a 7 napos átlag félrevezető (nyáron közel nulla, télen sokszoros), ezért ide a
  szezonális módszer kell: a tavalyi azonos időszak, illetve a fűtési napfok (4. lépcső).
- Figyelmeztetés, ha a várható ráfizetés meghalad egy küszöböt: ilyenkor érdemes a szolgáltatónál
  részszámla-módosítást kérni, vagy félretenni.
- A részszámla mennyisége a mért fogyasztástól függetlenül becsült lehet (pl. 103 m³ számlázva, ~20 m³ mérve);
  a Rezsikövető ezért nem a részszámla mennyiségét, hanem az összegét használja.

## Figyelmeztetések (példák)

| Kód | Mikor |
|---|---|
| `keret_atlepes_varhato` | Az előrejelzés szerint az időszakban elfogy a keret |
| `keret_atlepve` | Már a keret feletti áron fogyaszt |
| `becsult_adat` | Hiányzó állás miatt becslés van a számításban |
| `forras_elakadt` | A forrás-entitás 24 órája nem változott, vagy nem elérhető |
| `felulirt_dij_elavult` | Új hivatalos díj jött, de a felhasználó felülírt értéke van érvényben |
| `futoertek_hianyzik` | Gáznál nincs megadva az adott havi fűtőérték |
| `varhato_rafizetes` | Részszámlás fióknál a várható éves ráfizetés meghaladja a beállított küszöböt |

## Tesztelés

1. **Egységtesztek** minden lépésre (szeletelés, keret, átváltás, kerekítés).
2. **Számlatesztek:** valódi, anonimizált számlák adatai (leolvasások, díjak, végösszeg). A motornak forintra pontosan ki kell hoznia a számla összegét, vagy a teszt dokumentálja, miért tér el.
3. **v1-paritás:** a mostani YAML-változat lezárt hónapjai (16 hónapnyi napló) bemenetként; a motornak ugyanazt kell adnia.
