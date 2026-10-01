# Rezsikövető integráció (0.1 – fejlesztői változat)

> **Tájékoztató jellegű számítás, a hivatalos számlát nem helyettesíti.**
> A 0.1 a v1 YAML-csomag tudását hozza integrációként. A víz, a gáz MJ-alapú elszámolása és a napelem a következő lépcsőkben jön (lásd `docs/terv/04_UTEMTERV.md`).

## Mennyire pontos?

Két valódi MVM Next számlán ellenőrizve (`tests/motor/test_szamlak.py`):

| Számla | Számla végösszege | Rezsikövető |
|---|---|---|
| Villany A1, 2026.05.14–06.08 (293 kWh) | 14 624 Ft | **14 624 Ft** |
| Gáz, 2026.07.15–08.13 (103 m³ = 3 564 MJ) | 11 185 Ft | **11 185 Ft** |

A számlákból átvett szabályok: a díjak nettók, a számla tételsoronként forintra kerekít, és az ÁFA a nettóra jön; a kedvezményes keret egész kWh-ra kerekítve jár (26 nap → 180 kWh); az alapdíj számlánként egy teljes hónap; a gáz MJ-ban számol (m³ × korrekció × havi fűtőérték, egész MJ, hónaponként).

**Fontos:** a szolgáltató részszámlái gyakran becsült mennyiségről szólnak (a fenti gázszámla 103 m³-t számlázott, a gázóra valójában ~20 m³-t mért). A Rezsikövető a mért fogyasztásból számol, ezért egy-egy részszámlától eltérhet; az éves elszámolással kell egyeznie.

## Telepítés

1. Másold a `custom_components/hu_rezsi` mappát a HA `config/custom_components/` mappájába (később: HACS egyéni tároló).
2. Indítsd újra a Home Assistantot.
3. **Beállítások → Eszközök és szolgáltatások → Integráció hozzáadása → Rezsikövető**, add meg a háztartás nevét.
4. A háztartás bejegyzésén: **Fiók hozzáadása**. Egy fiók = egy szerződés egy mérővel (pl. „Villany A1”, „Villany H”, „Gáz”).

### A fiók beállításai

| Mező | Mire jó |
|---|---|
| Szolgáltató, díjszabás | A hivatalos díjak ezekből töltődnek be (`dijszabasok/`), később felülírhatók |
| Elszámolási időszak | Naptári hónap, vagy egyedi kezdőnap (pl. minden hónap 12-e) |
| Automatikus mérőállás-szenzor | Opcionális. Statisztikával rendelkező szenzor (`state_class: total_increasing`) |
| A szenzor értéke | **Mérőóra-állás:** a szenzor értéke maga az óraállás (pl. a v1 `sensor.meroora_allas`). **Számláló:** csak a változását vesszük át, a kézi leolvasásokhoz igazítva (pl. Shelly összes energia). |
| A szenzor érvényes ettől | A szenzor ez előtti adatait figyelmen kívül hagyja (pl. hibás régi képlet). A leolvasásoknak ellentmondó (visszafelé futó) értékeket a motor magától is eldobja. |
| Szenzor-szorzó | Ha a szenzor rendszeresen eltér az órától |
| Kedvezményes keret | Kikapcsolva minden mennyiség a keret feletti áron számol |
| Mérő beépítése, kezdőállás | Innen indul a számítás |

## Részszámlás (átalány) fiók

Ha a fiók fizetési módja „Részszámlás”, három entitás jön létre: **Befizetve (részszámlák)**, **Várható éves költség** és **Várható éves egyenleg** (pozitív: visszatérítés, negatív: ráfizetés). Az elszámolási év az utolsó elszámoló leolvasástól tart egy évig.

- A befizetések a Díjnet-integráció kifizetett számláiból (a fiókban kiválasztott szolgáltató) és kézzel rögzített részszámlákból jönnek (`hu_rezsi.reszszamla_rogzites`). Az év kezdete utáni 20 napon belül kelt számla az előző év elszámolója.
- A hátralévő részszámlák: (évi darabszám − eddigi) × az utolsó összeg.
- Az előrejelzés a tavalyi éves fogyasztás és egy havi profil (gáznál fűtési profil) alapján készül; az attribútumokban a tavalyi év **visszamérése** is látszik (befizetve vs. számított).

Gáznál a havi fűtőérték a számláról rögzíthető: `hu_rezsi.futoertek_rogzites` (hónap `ÉÉÉÉ-HH`, MJ/m³).

## Napelemes fiók (kísérleti)

Villanyfióknál a „Napelem” mező: **bruttó** (havi; a vételezés a rendes díjszabás szerint, a betáplálás az elosztó átvételi árán jóváírva) vagy **szaldó** (éves nettózás az elszámolási évre; vételezési többletnél a nettó a rendes díjszabás szerint, betáplálási többletnél alacsony átvételi ár). A betáplálást (2.8.0) egy szenzor adja – ha a HA Energia irányítópulton be van állítva a hálózati betáplálás, azt ajánlja fel –, vagy kézi leolvasás `csatorna: betaplalas` értékkel. Entitások: **Betáplálás**, **Betáplálás jóváírása**, **Napelemes egyenleg**.

> A szabályok nyilvános forrásokon alapulnak, valódi napelemes számlán még nem ellenőriztük. Esetek, források, nyitott kérdések: `docs/terv/05_NAPELEM.md`. **Ha van napelemed, egy anonimizált számlád sokat segítene.**

## Víz

A `viz/dakov` díjszabás a DAKÖV lakossági díjaival (számlán ellenőrizve: 8 013 Ft forintra pontos); más vízműnél a `viz/egyedi` sablon díjait felülírással kell megadni. A locsolási mérő külön fiók vagy csatorna, csatornadíj nélkül.

## Automatikus számlafeldolgozás

A fiók „Számlamappa” mezőjében megadott mappa (a config mappán belül; a felület felajánlja a számlát tartalmazó mappákat, pl. a Díjnet-integráció `Dijnet /<szolgáltató>` mappáit) új fájljait a Rezsikövető minden frissítéskor feldolgozza:

| Forrás | Fájl | Mit vesz át |
|---|---|---|
| MVM Next áram, gáz | `*_szamla.xml` (Díjnet) | befizetés, diktált/leolvasott mérőállás, gáznál a havi fűtőérték |
| DAKÖV víz | PDF | befizetés, mérőállások (fő- és almérő) |
| MOHU | XML | befizetés |

- Becsült állás nem kerül be; a számla időszakán belüli, a szolgáltató által számított bontás (pl. az éves gázszámla jan. 1-je) sem. Elszámoló leolvasás csak egy elszámoló számla időszakának végén.
- A kézzel rögzített adat mindig erősebb: azonos napra nem ír felül leolvasást, és a kézzel megadott fűtőértéket sem.
- Közös mappánál (pl. A1 és H egy szerződésen) a „Számla-mérők” mezőben a mérő gyári számával választható szét.
- Az új számlákról értesítés jön; az „Utolsó számla” entitás mutatja a legutóbbit.

## Entitások (fiókonként)

| Entitás | Tartalom |
|---|---|
| Költség eddig | A nyitott időszak eddigi költsége; a keret és az alapdíj a teljes időszakra jár, ahogy a számlán. Attribútumban a szeletek (díjváltozás, idényváltás, elszámoló leolvasás szerint). |
| Várható költség | Időszak végére, az utolsó 7 nap napi átlagával |
| Fogyasztás az időszakban | |
| Hátralévő kedvezményes keret | Attribútum: várható keretátlépés napja |
| Aktuális egységár | A következő egység ára – a HA Energia irányítópulthoz ár-entitásként is megadható |
| Éves fogyasztás | Az utolsó elszámoló (éves) leolvasás óta |
| Várható elszámolás | „Ha ma lenne az elszámolás”: az utolsó valódi elszámoló számla időszakának vége óta mért fogyasztás költsége (alapdíjjal) és az azóta kiállított számlák különbsége. Pozitív: visszatérítés, negatív: ráfizetés. Ha nincs elszámoló számla, az első számla időszakától számol. |
| Utolsó számla | A számlamappából feldolgozott legutóbbi számla összege (sorszám, kelte, típus) |
| Utolsó lezárt időszak | Az időszak végén automatikusan lezárul (a következő időszak első napján 01:00 után) |

A háztartáson: **Rezsi eddig összesen** és **Rezsi várható összesen**.

## Szolgáltatások

| Szolgáltatás | Mire jó |
|---|---|
| `hu_rezsi.leolvasas_rogzites` | Kézi vagy szolgáltatói leolvasás. Az „elszámoló” leolvasástól indul az éves keret, és ott kettéválik az időszak. |
| `hu_rezsi.leolvasas_torles` | Egy nap leolvasásainak törlése |
| `hu_rezsi.merocsere` | A régi mérő lezárása és új nyitása – a fogyasztás folytonos marad |
| `hu_rezsi.feluliras` | Díj felülírása dátumtól, pl. `dijak.energia_piaci` |
| `hu_rezsi.naplo` | Lezárt időszakok, mérők, leolvasások (válaszként) |
| `hu_rezsi.csv_export` | CSV a `/config/hu_rezsi/` mappába |
| `hu_rezsi.v1_import` | Átvétel a v1 csomagból (alapból próbafuttatás) |

## Átállás a v1 YAML-csomagról

1. Telepítsd az integrációt, és vedd fel a fiókokat. Forrásnak a v1 óraállás-szenzorait add meg „Mérőóra-állás” módban: `sensor.meroora_allas`, `sensor.meroora_allas_h`, `sensor.gaz_meroora_allas`.
2. Futtasd a `hu_rezsi.v1_import` szolgáltatást **próbafuttatással**, és nézd át a jelentést.
3. Ha rendben van, futtasd `probafuttatas: false`-szal. Átkerül a leolvasási napló (elszámoló leolvasásként, a mérők kezdetével és a H-óra felszerelésével) és a lezárt havi elszámolások (A1/H szétbontva).
4. **Egy hónapig fusson párhuzamosan a két rendszer.** A v1 csomagot csak azután töröld, ha a hónapzárások egyeznek.

A korrekció-típusú v1 bejegyzéseket az importáló kihagyja; ezeket kézi leolvasásként rögzítsd.

## Hibakeresés

**Beállítások → Eszközök és szolgáltatások → Rezsikövető → ⋮ → Diagnosztika letöltése.** Benne vannak a fiókok beállításai, a tárolt adatok és a számláló utolsó pontjai.
