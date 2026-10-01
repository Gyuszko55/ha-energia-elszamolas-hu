# 04 – Ütemterv

Minden lépcső végén **kiadható, használható változat** van. A következő lépcső csak akkor indul, ha az
előző stabil. Méret: **K** = kicsi (néhány este), **K+** = közepes, **N** = nagy.

## Áttekintés

| Lépcső | Tartalom | Kiadás | Méret |
|---|---|---|---|
| 0 | Tervezés, döntések, közös tároló | – | K |
| 1 | Integráció a v1 tudásával (villany A1+H, gáz m³, leolvasás, mérőcsere) | `0.1` | N |
| 2 | Gáz MJ-alapon, víz és csatorna, elszámolási időszakok | `0.2` | K+ |
| 3 | Napelem: vételezés + betáplálás, szaldó / bruttó | `0.3` | K+ |
| 4 | Előrejelzés, figyelmeztetések, rezsi-kártya | `0.4` | K+ |
| 5 | További tarifák (A2, B, dinamikus) | `0.5+` | igény szerint |
| – | Stabil kiadás, HACS alapértelmezett listára jelentkezés | `1.0` | K |

## 0. lépcső – Tervezés

- [~] **T1** A nyitott kérdések (00, K1–K7) eldöntése a javaslattevővel
- [ ] **T2** Tároló előkészítése (eldöntve: ez a tároló), közreműködői jog a javaslattevőnek, licenc (MIT), jegysablonok
- [~] **T3** Ezek a tervdokumentumok átnézve, a megjegyzések beépítve
- [ ] **T4** Legalább 3 anonimizált valódi számla összegyűjtése tesztadatnak (villany A1, H, gáz)
- [x] **T5** Díjfájl-séma (`schema.json`) és az első díjfájlok: `villany/a1`, `villany/h`, `gaz/lakossagi` a mostani díjtáblázatból

**Kész, ha:** a T1 döntései le vannak írva a `00_ATTEKINTES.md`-ben, és a tároló készen áll az első kódra.

## 1. lépcső – Integráció a v1 tudásával

**Kódszerkezet:**

```
custom_components/hu_rezsi/
├── __init__.py, manifest.json, config_flow.py
├── motor/                 # tiszta Python, HA nélkül
│   ├── idoszak.py, szeletelo.py, keret.py, elorejelzes.py
│   └── modulok/villany.py, gaz.py
├── dijszabasok/           # adatfájlok (02)
├── tarolo.py              # leolvasások, felülírások, lezárt időszakok
├── sensor.py              # költség-, keret-, ár-entitások
├── services.yaml          # leolvasás rögzítése, mérőcsere, időszak lezárása, CSV-export
└── translations/hu.json, en.json
tests/
```

**Jegyek:**

- [x] **I1** Alapváz: manifest, beállítási folyamat (háztartás → fiókok → mérők → csatornák), fordítások
- [x] **I2** Díjfájl-betöltő és séma-ellenőrzés, felülírási rétegek
- [x] **I3** Motor: időszak, szeletelés, napi arányos és éves keret, alapdíj, Decimal-kerekítés
- [x] **I4** Villany modul: A1, H idényes bontással, csatornánkénti keret
- [x] **I5** Gáz modul m³-ben (az MJ a 2. lépcsőben jön)
- [x] **I6** Tároló: leolvasás, korrekció, mérőcsere (mérő lezárása + új nyitása), HA-statisztikából vett állás
- [x] **I7** Szolgáltatások: leolvasás rögzítése, mérőcsere, időszak lezárása, CSV-export
- [x] **I8** Entitások: havi eddigi és várható költség, hátralévő keret, aktuális ár (a HA Energia irányítópulthoz is)
- [x] **I9** Automatikus havi lezárás (1-jén 00:00:30, mint a v1-ben)
- [x] **I10** v1-importáló: a leolvasási napló, a havi napló és a beállított díjak átvétele
- [~] **I11** Tesztek: egység + v1-paritás (18 hónap) kész; számlatesztek a T4 számláira várnak
- [x] **I12** Dokumentáció: telepítés, átállás v1-ről, „tájékoztató jellegű” figyelmeztetés

**Állapot (2026-10-01):** az élő HA-n fut a v1 mellett; az október 31-i hónapzárás a párhuzamos futás első próbája.

**Kész, ha:** egy tiszta HA-ra telepítve beállítható felületről, és a mi éles adatainkon ugyanazt adja, mint a v1.
**Átállás az éles rendszeren:** csak ezután, mentéssel, a két változat egy hónapig párhuzamosan fut.

## 2. lépcső – Gáz MJ, víz, időszakok

- [ ] **G1** `atvaltas: gaz_mj`: havi fűtőérték kézzel vagy entitásból, korrekciós tényező, „becsült” jelzés
- [ ] **G2** Gázkeret MJ-ban, éves bázisdátumtól
- [ ] **V1** Víz modul: vízdíj, csatornadíj (csatornánként kikapcsolható), alapdíj; `viz/egyedi` sablon
- [ ] **V2** Locsolási almérő: a fővízmérőből levonva, csatornadíj nélkül
- [ ] **P1** `egyedi_nap` és `leolvasas_alapu` időszakmód

## 3. lépcső – Napelem

- [ ] **N0** Szabály-összefoglaló forrásokkal: szaldó, bruttó, egyedi; mióta, kire vonatkozik (00, K7)
- [ ] **N1** `betaplalas` csatorna-szerep, kétirányú mérő kezelése
- [ ] **N2** Elszámolási módok a motorban, a keret előtt alkalmazva
- [ ] **N3** Entitások: nettó egyenleg, betáplálás értéke

## 4. lépcső – Előrejelzés és felület

- [ ] **E1** Előrejelzés: tavalyi azonos időszak, fűtési napfok; módszer fiókonként
- [ ] **E2** Várható keretátlépés napja, figyelmeztetés-entitások és értesítés-blueprint
- [ ] **E3** Rezsi-kártya (külön tároló): főoldal = havi költség, várható hó vége, villany/gáz/víz bontás, keret, figyelmeztetések; részletek lenyitva
- [ ] **E4** Leolvasó felület a kártyában (a v1 Energia oldali leolvasójának utódja)

## 5. lépcső – További tarifák

- [ ] **A2** Kétzónás (`zonak`)
- [ ] **B** Vezérelt (`vezerelt` csatorna)
- [ ] **D** Dinamikus (`dinamikus`, árforrás-entitás, aktuális és előrejelzett költség)

Csak akkor, ha van felhasználó, aki tesztelni tudja a saját mérőjével és számlájával.

## A v1 sorsa

| Mikor | Mi történik |
|---|---|
| Most | A v1 csak hibajavítást kap. A README-ben megjelenik egy hivatkozás az új projektre. |
| `0.1` kiadása | Átállási útmutató és importáló. A v1 még támogatott. |
| `1.0` kiadása | A v1 archiválva (csak olvasható), a README az új projektre mutat. |
