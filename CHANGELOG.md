# Változások

## [Fejlesztés] Rezsikövető 0.3.0-dev (2026-10-01)

- Napelem (kísérleti): bruttó és szaldó elszámolás, betáplálás-szenzor (Energia-beállításból ajánlva), 2.8.0-s leolvasás; `villany/hmke` forrásokkal; `docs/terv/05_NAPELEM.md`.
- Víz: `viz/dakov` (DAKÖV-számlán forintra pontos), végösszeg-kerekítési mód.
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
