# Rezsikövető – 0. lépcső: áttekintés

> **Állapot:** tervezet, megvitatásra. Kód még nincs, ez a dokumentumcsomag a közös alap.
> **Dátum:** 2026-10-01

## Miről szól?

A mostani `ha-energia-elszamolas-hu` (v1, YAML-csomag) villany- és gázköltséget számol.
A cél egy **komplett, magyar lakossági rezsikövető**: villany, gáz, víz és csatorna egy helyen,
saját Home Assistant-integrációként (HACS), két párhuzamos magyar projekt helyett egyetlen közösben.

A felhasználó négy kérdésre kapjon választ, ebben a sorrendben:

1. **Mennyibe került?** Lezárt időszakok költsége.
2. **Mennyi lesz?** Várható költség az időszak végére.
3. **Hol tartok a keretben?** Hátralévő kedvezményes keret, várható keretátlépés.
4. **Kell-e valamin változtatnom?** Figyelmeztetések, javaslatok.

## Alapelvek

| # | Elv | Mit jelent a gyakorlatban |
|---|---|---|
| 1 | **Rétegzés** | A mérés, a díjszabás és az elszámolás külön réteg. Egy díjváltozás csak adatfájl-frissítés, nem kódátírás. |
| 2 | **Modulok közös maggal** | Villany, gáz és víz külön modul. A közös mag kezeli az időszakokat, a leolvasásokat, a kereteket és az előrejelzést. A gáz MJ-logikájának módosítása nem nyúl a villanyhoz. |
| 3 | **Verziózott díjszabás** | Minden díj és szabály hatálybalépési dátummal él. Egy 2027-es változás nem írja át a korábbi elszámolásokat. |
| 4 | **Minden felülírható** | A hivatalos díjak alapértékként töltődnek be, de mérőnként bármelyik felülírható (pl. egyedi szerződés, eltérő vízdíj). |
| 5 | **A mérőóra az igazság** | Az automatikus HA-szenzor csak segédeszköz. A kézi leolvasás, a mérőcsere és a korrekció mindig felülbírálja. |
| 6 | **Számolómotor HA nélkül** | Az elszámoló motor tiszta Python, HA-függőség nélkül, így valódi számlákból készült tesztesetekkel ellenőrizhető. |
| 7 | **Tájékoztató jelleg** | A számítás tájékoztató, a hivatalos számlát nem helyettesíti. Ezt a felületen is jelezni kell. |

## Amit szándékosan NEM csinálunk

- **Nem másoljuk a HA Energia irányítópultot.** Ár-entitásokat adunk neki, de a saját felületünk pénzügyi szemléletű.
- **Nem töltünk le adatot szolgáltatói portálokról** (pl. ügyfélkapuk), legalábbis az első kiadásokban nem.
- **Nem kezelünk üzleti (nem lakossági) tarifákat.**
- **Nem építünk új funkciót a v1 YAML-csomagba.** Az csak hibajavítást kap, amíg az integráció el nem éri a tudását.

## A dokumentumcsomag

| Fájl | Tartalom |
|---|---|
| `00_ATTEKINTES.md` | Ez a fájl: célok, elvek, szójegyzék, nyitott kérdések |
| `01_ADATMODELL.md` | Háztartás → Szolgáltatói fiók → Mérő → Csatorna, leolvasások, időszakok |
| `02_DIJSZABAS_FORMATUM.md` | A verziózott díjszabás-fájlok formátuma, példákkal |
| `03_ELSZAMOLO_MOTOR.md` | Hogyan lesz a mérőállásokból forint: időszak-bontás, keret, előrejelzés |
| `04_UTEMTERV.md` | Lépcsők, mérföldkövek, GitHub-jegyek |

## Szójegyzék

| Fogalom | Jelentés |
|---|---|
| **Háztartás** | Egy ingatlan, a rendszer legfelső szintje. |
| **Szolgáltatói fiók** | Egy szerződés egy szolgáltatóval (pl. MVM villany, Főgáz, helyi vízmű). Egy háztartásban több is lehet. |
| **Mérő** | Fizikai mérőóra, saját gyári számmal. Cserekor új mérő jön létre, a régi lezárul. |
| **Csatorna** | Egy mérőn belüli külön számláló: pl. vételezés és betáplálás, vagy a H-mérő téli és nyári regisztere. |
| **Díjszabás** | Egy tarifa szabályai (sávok, keret, idényszak) és díjai (Ft/egység, alapdíj), hatálybalépési dátummal. |
| **Keret** | A kedvezményes (rezsicsökkentett) áron elszámolható mennyiség. |
| **Elszámolási időszak** | Két leolvasás vagy két számlázási dátum közti idő. Nem feltétlenül naptári hónap. |
| **Leolvasás** | Dátumozott mérőállás, forrása lehet kézi, szolgáltatói vagy automatikus. |

## Nyitott kérdések (döntés kell a közös munka előtt)

| # | Kérdés | Javaslat |
|---|---|---|
| K1 | Melyik tárolóban és kinek a vezetésével menjen a projekt? | Új, közös tároló (pl. `ha-rezsi-hu`), mindkét fél karbantartó joggal. |
| K2 | Mi legyen a neve és az integráció azonosítója? | Név: „Rezsikövető”; azonosító: `hu_rezsi`. |
| K3 | Ki és hogyan frissíti a hivatalos díjakat? | Díjfájlok a tárolóban, változáskor új kiadás. Bárki küldhet javítást, forrásmegjelöléssel. |
| K4 | Mi a legrégebbi támogatott HA-verzió? | Az aktuális és az előző fő kiadás (pl. 2026.9+). |
| K5 | Mi legyen a v1 felhasználóival? | Átvezető útmutató és importáló a leolvasási naplóhoz. A v1 csak hibajavítást kap. |
| K6 | Lovelace-kártya ugyanabban a tárolóban vagy külön? | Külön tároló, mert a HACS külön kezeli az integrációt és a kártyát. |
| K7 | Szaldós és bruttó napelemes elszámolás: melyik szabályok érvényesek és mióta? | A 3. lépcső előtt külön, forrásokkal alátámasztott összefoglaló kell. |
