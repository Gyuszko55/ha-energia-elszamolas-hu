# Változások

## [Fejlesztés] Rezsikövető integráció 0.1.0-dev (2026-10-01)

- Új: `custom_components/hu_rezsi` HA-integráció (1. lépcső): fiókok felületről, verziózott díjfájlok, elszámoló motor (HA nélkül tesztelhető), leolvasás/mérőcsere/felülírás/napló/CSV szolgáltatások, automatikus hónapzárás, v1-importáló, diagnosztika.
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
