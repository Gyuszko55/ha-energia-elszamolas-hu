# 04 – Ütemterv

Minden lépcső végén **kiadható, használható változat** van. A következő lépcső csak akkor indul, ha az
előző stabil. Méret: **K** = kicsi (néhány este), **K+** = közepes, **N** = nagy.

## Áttekintés

| Lépcső | Tartalom | Kiadás | Méret |
|---|---|---|---|
| 0 | Tervezés, döntések, közös tároló | – | K |
| 1 | Integráció a v1 tudásával (villany A1+H, gáz m³, leolvasás, mérőcsere) | `0.1` | N |
| 2 | Gáz MJ-alapon, részszámlás (átalány) elszámolás éves egyenleggel, víz és csatorna, elszámolási időszakok | `0.2` | K+ |
| 3 | Napelem: vételezés + betáplálás, szaldó / bruttó | `0.3` | K+ |
| 4 | Előrejelzés, figyelmeztetések, rezsi-kártya | `0.4` | K+ |
| 5 | További tarifák (A2, B, dinamikus) | `0.5+` | igény szerint |
| – | Stabil kiadás, HACS alapértelmezett listára jelentkezés | `1.0` | K |

## 0. lépcső – Tervezés

- [x] **T1** A nyitott kérdések eldöntve: K1 tároló (később: privát fejlesztői tároló `rezsikoveto`), K2 név/azonosító, K3 díjfájlok a tárolóban, K5 v1-importáló; **K6 módosult:** külön Lovelace-kártya helyett beépített oldalsáv-panel; K4 (min. HA-verzió) és K7 (napelem) részben
- [x] **T2** Tároló: Krissz55555 közreműködő és társszerző, MIT licenc mindkettejük nevén, jegysablon „Új szolgáltató / számlaformátum”
- [x] **T3** Tervdokumentumok; ez az ütemterv 2026-10-02-án frissítve
- [x] **T4** Valódi számlák tesztadatnak: villany A1, H (két regiszter), gáz, DAKÖV, MOHU, MVM végszámla, B tarifa
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
- [x] **I11** Tesztek: egység + v1-paritás (18 hónap) + 2 számlateszt (villany forintra pontos, gáz ±3 Ft az m³-alapú számítás miatt)
- [x] **I12** Dokumentáció: telepítés, átállás v1-ről, „tájékoztató jellegű” figyelmeztetés

**Állapot (2026-10-01):** az élő HA-n fut a v1 mellett; az október 31-i hónapzárás a párhuzamos futás első próbája.

**Kész, ha:** egy tiszta HA-ra telepítve beállítható felületről, és a mi éles adatainkon ugyanazt adja, mint a v1.
**Átállás az éles rendszeren:** csak ezután, mentéssel, a két változat egy hónapig párhuzamosan fut.

## 2. lépcső – Gáz MJ, víz, időszakok

- [x] **G1** `atvaltas: gaz_mj`: havi fűtőérték kézzel vagy entitásból, korrekciós tényező, „becsült” jelzés
- [x] **G2** Gázkeret MJ-ban, éves bázisdátumtól
- [x] **V1** Víz modul: vízdíj, csatornadíj (csatornánként kikapcsolható), alapdíj; `viz/egyedi` sablon
- [x] **V2** Locsolási almérő a főmérő mögött: a mennyisége a csatornadíjból levonódik (DAKÖV elszámoló számla, 2026-08) – két számlateszttel, HA-ban is
- [x] **P1** `egyedi_nap` (gáz: 14-től 13-ig); villanynál **elszámolási mód**: diktálás / átalány / távleolvasás – diktálási időszakok a számlák és a „diktáltam” leolvasások szerint, diktálási ablak a számláról. Gáznál, víznél leolvasás-alapú időszak nincs (nem volt rá igény)
- [x] **R1** Részszámlás (átalány) fiók: részszámlák rögzítése (kézzel, éves tervből, vagy entitásból – pl. Díjnet), befizetve / tényleges / várható éves költség, **várható éves egyenleg** (ráfizetés vagy visszatérítés), figyelmeztetés küszöb felett. A szezonális gáz-előrejelzés (E1) ehhez szükséges, ezért a kettő együtt készül.

**Állapot (2026-10-01):** élesben; mindkét valódi számla forintra pontos (nettó tételsoros számlázás ÁFÁ-val). Részszámla-egyenleg a Díjnet-fájlból; két év visszamérése: −2,3% és +5,6% (a havi fűtőértékek és a régi árak hiánya miatt). Új: a szenzor érvényességi dátuma és ellentmondásszűrés (hibás régi szenzoradat ellen).

## 3. lépcső – Napelem

Részletes terv, források és nyitott kérdések: **`05_NAPELEM.md`**. A fejlesztőknek nincs napeleme, ezért a
szabályok nyilvános forrásokból jönnek, és valódi számlákkal kell majd ellenőrizni.

- [x] **N0** Szabály-összefoglaló forrásokkal, esetek (szaldó/bruttó/váltás, akkumulátor, tarifa, fázis), adatforrások, nyitott kérdések
- [x] **N1** Motor: bruttó és szaldó elszámolás, szintetikus tesztek
- [x] **N2** HA-réteg (kísérleti jelzéssel), élő próba szimulált fiókokkal
- [~] **N3** Első valódi napelemes számla (ELMŰ, szaldó, 2025-01-16 – 2026-01-16: vételezés 2 518, betáplálás 5 633 kWh, csak alapdíj) – számlateszt és a „kísérleti” jelzés levétele még hátra; bruttó elszámolású számla még nincs
- [ ] **N4** Akkumulátor és önfogyasztás megtakarítás-elemzése (a 4. lépcsővel)

## 4. lépcső – Előrejelzés és felület

- [~] **E1** Előrejelzés: hónapon belül az utolsó 7 nap átlaga, éves egyenleghez tavalyi éves fogyasztás × havi profil; **tavalyi azonos időszak és fűtési napfok még nincs**
- [~] **E2** Várható keretátlépés napja, figyelmeztetések a panelen és entitásként, értesítés új/fel nem ismert számláról; **értesítés-blueprint még nincs**
- [x] **E3** Rezsikövető **oldalsáv-panel** (a külön kártya helyett): esedékes számlák, havi átlag, fiókkártyák, keret, ⓘ magyarázatok, több otthon fülekkel; irányítópult-kártya nincs
- [x] **E4** Mérőállás-rögzítés, számla feltöltése/kézi rögzítése, jelölős számlatörlés a panelen

## 5. lépcső – További tarifák

- [x] **A2** Kétzónás (`zonak`): regiszter-szenzorokkal vagy órás statisztikából időszabály szerint (völgy munkanapon 22–06 / nyári időszámításban 23–07, nem munkanapon egész nap); közös keret fogyasztásarányosan – **valódi A2-számlával még ellenőrizendő**
- [x] **B** Vezérelt (B Alap), **B Komfort**, **B GEO** – az MVM árlapja szerint, mind a négy elosztói területre
- [x] **D** Dinamikus: MVM negyedórás rugalmas árlista automatikus letöltése, órás fogyasztással súlyozva; „mi lenne D-n” összevetés minden A1 fióknál. **Élő árforrás (folyó hónap) nincs** – ott becslés; valódi D-számla 2027 előtt nem lesz
- [x] **Gáz:** B1 (20 m³/h felett), fogyasztói közösség (A3), gázmérő nélküli átalány; havonta súlyozott keret diktálásnál

## Túl az eredeti terven (2026-10-01/02)

- **Számlák:** automatikus feldolgozás mappából (MVM áram/gáz XML és PDF, végszámla, DAKÖV, MOHU), feltöltés a panelről, kézi rögzítés, jelölős törlés, újraolvasás, fel nem ismert fájlok jelzése, fizetendő összeg (negatív is), árszabás szerinti válogatás (A1/H/B), átalány-mennyiség és diktálási ablak a számláról.
- **Számlázás:** számlázási ütem és elszámolási ciklus, ebben a hónapban esedékes számlák, utólagos többhavi számlázás (víz, hulladék), fix díjas fiók (hulladék), víz tételes díja, lezárt időszakok újraszámolása.
- **Felület és beállítás:** lépésenkénti fiók-varázsló (csak a releváns mezőkkel, szerkeszthető mérő-kezdőadatokkal), több otthon fülekkel, ikon/logó (HA `brand/`), indulást nem blokkoló számlafeldolgozás.
- **Felület és beállítás (2.1.0):** dinamikus varázsló – külön „Elszámolás” lépés csak a díjszabáshoz tartozó kérdésekkel, területi díjszabás-ellenőrzés, díjszabás-váltáskor a már nem érvényes mezők törlése.
- **Dokumentáció:** telepítési és kezelési kézikönyv (`docs/KEZIKONYV.md`), nyomtatható képes útmutató.

## Kiadás előtt hátra

| # | Teendő |
|---|---|
| K1 | **Párhuzamos futás kiértékelése:** a v1 és a Rezsikövető októberi hónapzárásának összevetése (2026-11-01 után), utána az élő átállás és a v1 kivezetése |
| K2 | ~~Díjak ellenőrzése a hivatalos forrásokkal~~ – kész (2026-10-03): MVM villany-árlap (VE_Lakossági_Árak_2025/1), gáz-árlap (Gáz_2026/2), gázátalány (Átalány_országos_2023/1), D kereskedői díj (HVEKD1) |
| K3 | Napelem: számlateszt a valódi szaldós számlából, bruttó számla beszerzése, „kísérleti” jelzés levétele (N3) |
| K4 | Képernyőképek mintaadatokkal (a kézikönyvben és a képes útmutatóban most valódi adatok vannak), GitHub megosztási kép feltöltése |
| K5 | Minimális HA-verzió rögzítése (a `hacs.json` 2025.6-ot mond; a beépített ikonhoz és az alárendelt bejegyzésekhez újabb kell), elavult HA-hívás cseréje (`device_registry.async_get_device`) |
| K6 | Angol fordítás kiegészítése (a magyar teljes, az angol részleges) |
| K7 | Fejlesztői tároló → nyilvános tároló, béta kiadás HACS-ban, majd `1.0` és jelentkezés a HACS alapértelmezett listájára |

## Tervezett funkciók

| # | Funkció | Leírás |
|---|---|---|
| T1 | **Számlák e-mailből** – ✅ elkészült a 2.2.0-ban (2.2.0b1, 2026-11-01; élesítés előtt valódi postafiókkal kipróbálandó) | Megvalósítva: külön „E-mail fiók” alárendelt bejegyzés (több is lehet; bejelentkezés-ellenőrzés a varázslóban), a fiókoknál „E-mailes számlák” lépés (postafiók, feladó a szolgáltatóból előtöltve, tárgy, mérő gyári száma / irányítószám), óránkénti átnézés, panel-állapotsor „Átnézés most” gombbal, `hu_rezsi.email_atnezes`, javítandó probléma hibánál; a jelszó a mentésből kimarad (`INTEGRACIO.md` – műszaki jegyzet). Eredeti terv: beépített IMAP-olvasó, kódírás nélkül beállítható. A fiók beállításainál: e-mail fiók (IMAP-szerver, felhasználó, alkalmazásjelszó a HA saját tárolójában), feladószűrő (pl. `mvmee.hu`) és visszatekintési idő. Csak olvas: nem töröl, nem jelöl olvasottnak, a Kuka mappát is átnézheti. A PDF-/XML-mellékletet a fiók számlamappájába menti, onnan a meglévő feldolgozás olvassa be. A melléklet nélküli értesítőből (pl. Telekom) a levél szövegéből rögzít számlát. Több fiókos otthonnál a felhasználási hely (irányítószám, mérő gyári száma) alapján választ fiókot. Mintája egy saját telepítésben működő szkript (2026-10). |

## A v1 sorsa

| Mikor | Mi történik |
|---|---|
| Most | A v1 csak hibajavítást kap. A README-ben megjelenik egy hivatkozás az új projektre. |
| `0.1` kiadása | Átállási útmutató és importáló. A v1 még támogatott. |
| `1.0` kiadása | A v1 archiválva (csak olvasható), a README az új projektre mutat. |
