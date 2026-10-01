# Változások

## [Fejlesztés] Rezsikövető 2.0.0b2 (2026-10-01)

- **H-tarifa két regiszterrel:** a téli (1.81) és a nyári (1.82) regiszter külön szenzorból és külön leolvasással mérődik, és külön számolódik (téli: H-ár, nyári: A1 ár saját kerettel, amely csak nyáron gyűlik). Az októberi és áprilisi váltás hónapjában mindkét tarifa külön sorban látszik (panel, `idenyszakok` attribútum). Az előrejelzés a két regiszter együttes napi átlagát naptár szerint osztja szét (okt. 15-től a téli, ápr. 15-től a nyári).
- **Átalány bármely szolgáltatásnál:** „átalány” jelzés; **Havi fizetendő (átalány)** entitás = az átalány napra leosztva × a hónap napjai (az utolsó részszámla összege / időszakának napjai, vagy a beállított havi átalány × 12 / 365); a háztartás havi összesítőjében átalánynál a fizetendő szerepel.
- DAKÖV-számlák elszámolt időszaka (import-verzió 4); üres háztartás a panelen.

## Rezsikövető 2.0.0b1 – 2026-10-01 (első béta)

- **„Rezsi” oldalsáv-panel** (HTML/JS webkomponens + websocket-végpont): háztartás-összesítő, figyelmeztetések, fiókonkénti kártyák (eddig/várható, keret, várható elszámolás, éves egyenleg, számlák, napelem), részletek, mérőállás rögzítése; mobilon is.
- Az integráció verziószáma a v1 csomag utódjaként 2.x (a korábbi 0.1–0.4 fejlesztői változatok tartalma alább).

## [Fejlesztés] Rezsikövető 0.4.0-dev (2026-10-01)

- **Automatikus számlafeldolgozás** fiókonként egy mappából (pl. a Díjnet letöltési mappája): MVM áram/gáz és MOHU XML, DAKÖV PDF (pypdf). Rögzíti a befizetést, a valódi (diktált/leolvasott) mérőállást, gáznál a havi fűtőértéket; a becsült és a számla időszakán belüli számított állás kimarad; mérők gyári szám szerint (közös mappa szétválasztható); értesítés az új számlákról; „Utolsó számla” entitás.
- Befizetések számlaszám szerint egyesítve (számlamappa + Díjnet; sorszám híján nap + összeg egységes formában).
- **Fix díjas fiók** (hulladékszállítás, MOHU): mérő nélkül, naptári negyedéves időszak (a havi rész attribútumban, a háztartás havi összesítőjében a havi rész), `hulladek/mohu` díjszabás.
- Új entitások számlamappás fiókoknál: **Számlák az utolsó 12 hónapban**, **Következő számla várható** (szokásos időköz alapján; figyelmeztet elmaradt számlára, fix díjnál díjváltozásra).
- Új időszakmód: naptári negyedév.
- **Várható elszámolás** entitás minden fióknál: az utolsó valódi elszámolás óta mért fogyasztás költsége mínusz az azóta kiállított számlák.

## [Fejlesztés] Rezsikövető 0.3.0-dev (2026-10-01)

- Napelem (kísérleti): bruttó és szaldó elszámolás, betáplálás-szenzor (Energia-beállításból ajánlva), 2.8.0-s leolvasás; `villany/hmke` forrásokkal; `docs/terv/05_NAPELEM.md`.
- Víz: `viz/dakov` (két DAKÖV-számlán forintra pontos: 8 013 és 11 202 Ft), végösszeg-kerekítési mód, locsolási **almérő** a főmérő mögött (levonás a csatornadíjból), naptári havi alapdíj; HA-ban almérő kezdőállással, leolvasással és mérőcserével (`csatorna: almero`).
- Részszámlás fiók: opcionális részszámla-összeg és előző évi fogyasztás; a hátralévő részszámlákhoz nem az elszámoló számla összege számít; megbízhatósági jelzés; az almérő arányos előrejelzése.
- Javítás: új fiók felvételekor az entitásai azonnal elérhetők (újraszámolás, ha a fiók még hiányzik).

## [Fejlesztés] Rezsikövető 0.2.0-dev (2026-10-01)

- Nettó tételsoros számlázás ÁFÁ-val: mindkét valódi számla forintra pontos.
- Gáz MJ-ban (havi fűtőérték, `futoertek_rogzites`), éves keret MJ-ban.
- Víz: vízdíj + csatornadíj (kikapcsolható), `viz/egyedi` sablon.
- Részszámlás (átalány) fiók: befizetve, várható éves költség és egyenleg, Díjnet-forrás, tavalyi visszamérés.
- A forrás-szenzor érvényességi dátuma, ellentmondásszűrés.

## [Fejlesztés] Rezsikövető integráció 0.1.0-dev (2026-10-01)

- Új: `custom_components/hu_rezsi` HA-integráció (1. lépcső): fiókok felületről, verziózott díjfájlok, elszámoló motor (HA nélkül tesztelhető), leolvasás/mérőcsere/felülírás/napló/CSV szolgáltatások, automatikus hónapzárás, v1-importáló, diagnosztika.
- Számlák alapján: a keret egész kWh-ra kerekítve, az alapdíj számlánként egy hónap; gáz díjai (99,163 Ft/m³, alapdíj 972,82 Ft/hó) a 2026-08-as számlából. Számlatesztek.
- A v1 YAML-csomag változatlan.

## 1.0.0 – 2026-09-30

Első kiadás:

- Havi villany-elszámolás mérőóránkénti rezsisávval (A1 és H nyári külön), H-tarifa téli/nyári bontás.
- Szolgáltató-választó díjtáblázattal: MVM Démász, E.ON, OPUS TITÁSZ, ELMŰ, ELMŰ-ÉMÁSZ.
- „Eddig” és „Várható” összeg, megosztott hónap éves leolvasáskor, automatikus hónapzárás naplóval és CSV-vel.
- Lezárt hónapok táblázat éves elszámolás összesítővel.
- Mérőóra-leolvasás, korrekció és mérőcsere (villany A, villany H, gáz), leolvasási napló szűrővel.
- A mérő-források a felületen megadhatók, A1 szorzóval.
- `hu-szam-sor`: input_number beviteli sor tizedesvesszővel.
