# Rezsikövető integráció (0.1 – fejlesztői változat)

> **Tájékoztató jellegű számítás, a hivatalos számlát nem helyettesíti.**
> A 0.1 a v1 YAML-csomag tudását hozza integrációként. A víz, a gáz MJ-alapú elszámolása és a napelem a következő lépcsőkben jön (lásd `docs/terv/04_UTEMTERV.md`).

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
| Szenzor-szorzó | Ha a szenzor rendszeresen eltér az órától |
| Kedvezményes keret | Kikapcsolva minden mennyiség a keret feletti áron számol |
| Mérő beépítése, kezdőállás | Innen indul a számítás |

## Entitások (fiókonként)

| Entitás | Tartalom |
|---|---|
| Költség eddig | A nyitott időszak eddigi költsége; a keret és az alapdíj a teljes időszakra jár, ahogy a számlán. Attribútumban a szeletek (díjváltozás, idényváltás, elszámoló leolvasás szerint). |
| Várható költség | Időszak végére, az utolsó 7 nap napi átlagával |
| Fogyasztás az időszakban | |
| Hátralévő kedvezményes keret | Attribútum: várható keretátlépés napja |
| Aktuális egységár | A következő egység ára – a HA Energia irányítópulthoz ár-entitásként is megadható |
| Éves fogyasztás | Az utolsó elszámoló (éves) leolvasás óta |
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
