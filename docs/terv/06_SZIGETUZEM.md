# 06 – Szigetüzem: a háztartás belső energiaáramlásai (kWh)

> **Állapot:** 2026-10-06. A specifikáció **Krissz55555** javaslata (lent, a 3. fejezetben változtatás nélkül);
> az 1–2. fejezet a megbeszélt döntéseket, a nyitott kérdéseket és a megvalósítás állását rögzíti.
> A motor (`motor/sziget.py`) kész, tesztekkel; a fióktípus, a szenzorok és a panel kísérleti előnézetként fut.
> **Krissz55555 2026-10-06:** az SZ1–SZ8 pontosításokat elfogadta, a 2. lépés mehet. Szigorú szabály: *a felület se sugalljon olyan energiaútvonalat, amit a motor nem tud bizonyítani* – energiafolyam-ábra csak a levezethető útvonalakkal.

## 1. Döntések és pontosítások

| # | Kérdés | Javaslat / döntés |
|---|---|---|
| SZ1 | Hol legyen a rendszerben? | **Új közműtípus egy meglévő otthon alatt** („Szigetüzem”), Ft nélkül. Az otthon összesítőjében megjelenhet, de a rezsiösszegbe nem számít. Teljesen elkülönül a HMKE-től (napelem a villanyfiókban). |
| SZ2 | Export | A spec 10. pontja az energiamérlegben számol exporttal, a csatornalistában nincs. → **opcionális `export` csatorna** (hibrid inverter, ha enged visszatáplálást). Ettől a szigetüzemi nézet még működik; a hálózati elszámolás továbbra is a villanyfiók dolga. |
| SZ3 | Külső energia definíciója | **hálózat + generátor** (rögzítve: `KULSO`). Önellátottság = 1 − külső / fogyasztás, 0 és 100% közé szorítva; ha a külső több a fogyasztásnál (hálózatról töltött akku), 0% és megjegyzés. |
| SZ4 | Rövid időszak | A napi önellátottság **időszakhatár-érzékeny** (Krissz megfogalmazása, 10-06): az akku az egyik időszakban felvett energiát egy másikban adhatja vissza, ezért napi bontásban jelentős a torzítás, havi/éves szinten egyre kevésbé. A panel a ma/tegnap nézetben jelzi. |
| SZ5 | Beállítatlan vs. hiányzó csatorna | Beállítatlan forrás = **0** (nincs ilyen, pl. tiszta szigetüzemben nincs hálózat); beállított, de adat nélküli = **ismeretlen** → minőség PARTIAL, a tőle független mutatók számolódnak. Beállítatlan forrás részaránya nem jelenik meg (nem „0%”). |
| SZ6 | Útvonalak | Csak levezethető: hálózat → akku (ha az inverter külön méri) és hálózat → fogyasztás = hálózat − hálózat → akku; akku nélkül és mért exporttal „PV helyben felhasználva” = PV − export. Akkus rendszerben PV → ház / PV → akku megosztás **nincs** (megjegyzés jelzi). |
| SZ7 | Mérleg-eltérés | BE − KI; neve „mérleg-eltérés”, magyarázata: veszteség, mérési pontok (DC/AC) különbsége, sajátfogyasztás **és az akku tárolt energiájának változása** – nem „akkuveszteség”. Akku-hatásfok az első verzióban nincs, csak töltve / kivéve / nettó. |
| SZ8 | Számlálóhibák | A nyers szenzorsorozatból külön folytonos számláló (`szamlalo_sorozatbol`): ismeretlen kihagyva; ≤ 0,5 kWh és ≤ 0,1% visszaugrás zaj; nagyobb visszaugrás nullázódás (az új érték a reset óta mért energia); ismert maximumnál túlcsordulás; minden esemény naplózva. Mérőcsere/entitáscsere: a meglévő horgonyos logika (kezdőállás) használható. |

## 2. Megvalósítás állása és ütemezés

| Lépés | Tartalom | Állapot |
|---|---|---|
| 1 | **Motor** `motor/sziget.py`: szerepkörök (fogyasztás kötelező; PV, akku töltés/kisütés, hálózat, hálózat → akku, export, generátor, egyéb termelés – mind lehet több forrás), `szamlalo_sorozatbol`, `merleg` (mutatók, mérleg, útvonalak, minőség COMPLETE / ESTIMATED / PARTIAL / INSUFFICIENT_DATA), `idoszakok` (ma, tegnap, hónap, előző hónap, év, előző év, összesen), `honapok` | **kész** – `tests/motor/test_sziget.py`, 32 teszt (Krissz 25. pontos mátrixa, valós nap szintetikus mintájával) |
| 2 | Rendszertípus a varázslóban (`sziget` alárendelt típus): szerepkörönként szenzorválasztó (többes), Wh/MWh az egységből; kézi leolvasás `hu_rezsi.sziget_leolvasas` | **kísérleti előnézet** (2026-10-06) – kézi kezdőállás szenzoros forrásnál még nincs |
| 3 | Szenzorok: folyó havi fogyasztás, PV, akku töltés/kisütés, hálózat, generátor, önellátottság, hálózati részarány, adatminőség | **kísérleti előnézet** |
| 4 | Panel: szigetüzemi kártya (21. pont), időszakválasztó, havi bontás | **kísérleti előnézet** – éves összevetés-grafikon még nincs |
| 5 | Minta otthonba generált szigetüzemi fiók; valós regressziós teszt Krissz rendszeréből | hátra – **kell:** az inverter energia-entitásainak listája és 1–2 hónap statisztika-export |

## 3. Eredeti specifikáció (Krissz55555)

**1. Alapelv** – A Szigetüzem ne a meglévő HMKE/PV funkció bővítése legyen, hanem külön energiarendszer-típus. A kettő célja eltér: HMKE/PV: hálózati elszámolás, vételezés, betáplálás, szaldó/bruttó elszámolás; Szigetüzem: a háztartás belső energiaáramlásainak és energiafüggetlenségének követése. A szigetüzem első verziója legyen szigorúan energia-alapú, kWh-ban. Ne kerüljön bele feltételezett Ft-érték, akkumulátor-amortizáció vagy becsült megtakarítás.

**2. Lefedendő rendszerek** – Ne csak a klasszikus, hálózat nélküli szigetüzemet kezelje. Tiszta szigetüzem: PV → Fogyasztás, PV → Akku ↔ Fogyasztás. Hálózati tartalékkal: PV → Fogyasztás, PV → Akku ↔ Fogyasztás, Hálózat → Fogyasztás, Hálózat → Akku (ha engedélyezett). Generátoros rendszer: PV / Akku / Generátor / opcionális hálózat → Fogyasztás. A modell kezelje ezek kombinációit is. Így Axpert/Voltronic, Victron, Deye/Sunsynk és más rendszerek is leképezhetők gyártófüggetlenül.

**3. Az elszámolás alapja kizárólag energia** – Kumulatív energia-számlálók: house/load energy total, PV energy total, battery charge energy total, battery discharge energy total, grid import energy total, generator energy total. Elsődlegesen: `device_class: energy`, `state_class: total_increasing`, unit: kWh. Wh/MWh forrás elfogadható, ha a Rezsikövető kWh-ra normalizálja. Ne legyen elszámolási alap: W, A, V, SOC %, pillanatnyi PV teljesítmény, pillanatnyi inverterteljesítmény. W-ból kWh integrálás első körben ne a Rezsikövető feladata legyen.

**4. Kötelező és opcionális csatornák** – Kötelező: `load_energy` [kWh] – a rendszer által ellátott fogyasztók összes energiája. Opcionális: `pv_energy`, `battery_charge_energy`, `battery_discharge_energy`, `grid_import_energy`, `generator_energy`, `other_generation_energy`. Az `other_generation_energy` lehet például szél- vagy vízenergia.

**5. Akkumulátor** – Minimum: `battery_charge_energy` [kWh], `battery_discharge_energy` [kWh]. Opcionális: névleges kapacitás [kWh], használható kapacitás [kWh], SOC [%], tárolt energia [kWh]. A SOC nem elszámolási adat. Például 63% SOC egy 70 kWh-s rendszernél nem jelenti automatikusan, hogy pontosan 44,1 kWh van az akkumulátorban. BMS-kalibráció, tartalékok és eltérő pakkméretek miatt ezt nem szabad elszámolási alapként használni.

**6. Több akkumulátor** – Az adatmodell támogassa: egy akkumulátort, több külön akkumulátort saját charge/discharge kWh-val, vagy egy összesített akkumulátor-rendszert, ha csak az inverter összesített adata érhető el.

**7. Több PV mező / inverter** – Lehessen egyetlen összesített PV-szenzor vagy több PV-forrás/MPPT/inverter. A motor számára: PV_total = az összes PV-forrás összege.

**8. Energiaforrások aránya** – Példa: Teljes fogyasztás: 382,6 kWh; Hálózatról: 21,8 kWh; Generátorról: 4,3 kWh; Saját rendszerből: 356,5 kWh. Önellátottság: 1 − külső energia / fogyasztás. A külső energia definícióját rögzíteni kell; tipikusan hálózat + generátor.

**9. PV önfogyasztás** – Ha a mérésekből egyértelműen meghatározható, megjelenhet: PV termelés, PV közvetlen fogyasztás, PV → akkumulátor, PV export. Nem szabad olyan energiaáramlást tényként megjeleníteni, amely csak becslés vagy feltételezés.

**10. Energiaegyensúly** – Ideális esetben: BE: PV + hálózat + generátor + akkumulátor kisütés; KI: fogyasztás + akkumulátor töltés + export. A különbség mérési eltérés/veszteség lehet. Figyelembe kell venni a mérési pontokat. Ha PV DC-oldali, a Load pedig AC-oldali adat, a különbség tartalmazhat inverter-, DC/DC-, kábel- és sajátfogyasztási veszteséget. Nem szabad automatikusan akkumulátorveszteségnek nevezni.

**11. Akkumulátor-hatásfok** – Egy tetszőleges hónapra a discharge/charge arány nem feltétlenül valódi round-trip hatásfok, mert az időszak eleji és végi tárolt energia eltérhet. Első verzióban inkább: Akkuba töltve [kWh], Akkuból kivéve [kWh]. A hatásfok csak akkor jelenjen meg, ha megbízhatóan meghatározható.

**12. Hálózati backup** – A hálózat jelenléte nem teszi HMKE-vé a rendszert. Példa: PV → inverter, Akku → inverter, Grid → inverter AC-IN, Grid export tiltott. Ez továbbra is szigetüzemi/backup rendszer. Mutatók: hálózati vételezés [kWh], hálózati részarány [%], önellátottság [%].

**13. Hálózati akkumulátortöltés** – Külön kezelendő: Grid → Battery. Ha az inverter külön méri, vegyük figyelembe. Nem szabad például 200 kWh PV és 250 kWh battery charge esetén feltételezni, hogy mind a 250 kWh PV-ből származott. Az energia eredete és útvonala két külön kérdés.

**14. Bypass üzem** – A Grid → Load közvetlen bypass normál hálózati vételezés. Nem szabad feltételezni, hogy minden energia átmegy az akkumulátoron.

**15. Generátor** – Opcionális energiaforrás: `generator_energy`. Lehetséges útvonal: Generator → Load, Generator → Battery. Összesített generátorenergia is elfogadható.

**16. PV-visszaszabályozás / elveszett termelés** – Tele akkumulátornál és alacsony fogyasztásnál az inverter visszaszabályozhatja a PV-t. A kihasználatlan PV energia nem számítható ki pusztán a tényleges PV-termelésből. Csak megbízható adatforrás esetén jelenjen meg. Első verzióból kihagyandó.

**17. Számlálóhibák kezelése** – Minden total_increasing csatornánál kezelendő: mérő reset, invertercsere, entitáscsere, unknown, unavailable, HA restart, számláló nullázódás, számláló túlcsordulás, hibás visszaugrás. Példa: 12543 kWh, 12548 kWh, 0 kWh ← reset, 3 kWh. Ebből nem lehet negatív fogyasztás. A meglévő mérőcsere/baseline logika újrahasznosítható.

**18. Adatminőség** – Belső állapotok: COMPLETE, PARTIAL, ESTIMATED, INSUFFICIENT_DATA. A hiányzó opcionális csatorna ne tegye az egész rendszert unavailable-lé. Például Load + PV + Grid esetén önellátottság számítható, de akkumulátorhasználat nem.

**19. Kezdőpont** – Javasolt sorrend: 1. kézzel megadott kezdőállás, 2. HA long-term statistics / Recorder, 3. aktuális entitásérték mint baseline. Ha nincs múltbeli adat: „Az energiamérleg követése ettől az időponttól indul.” Nem kell történeti adatot kitalálni.

**20. Időszakok** – Minimum: Ma, Tegnap, Aktuális hónap, Előző hónap, Aktuális év, Előző év, Összesen, Egyéni időszak. Mindenhol kWh legyen az alap.

**21. Javasolt UI** – Példa: SZIGETÜZEM – 2026. október. Fogyasztás: 382,6 kWh. ENERGIAFORRÁSOK: PV: 417,3 kWh; Hálózati vételezés: 21,8 kWh; Generátor: 0,0 kWh. AKKUMULÁTOR: Töltés: 186,4 kWh; Kisütés: 163,7 kWh. ELLÁTÁS: Önellátottság: 94,3%; Hálózati részarány: 5,7%. ADATMINŐSÉG: teljes energiamérleg. Később energiafolyam-ábra is készülhet, de csak olyan útvonal kapjon konkrét kWh értéket, amely ténylegesen meghatározható.

**22. Home Assistant entitások** – Például: `sensor.sziget_fogyasztas_havi`, `sensor.sziget_pv_havi`, `sensor.sziget_akku_toltes_havi`, `sensor.sziget_akku_kisutes_havi`, `sensor.sziget_halozat_havi`, `sensor.sziget_generator_havi`, `sensor.sziget_onellatottsag`, `sensor.sziget_halozati_reszarany`, `sensor.sziget_adatminoseg`. A nyers forrásszenzorokat nem kell duplikálni.

**23. Amit első verzióban nem raknék bele** – Ft-ban számolt PV-megtakarítás; akkumulátor amortizáció; akkumulátor Ft/kWh; SOC-ból számolt fogyasztás; W → kWh integrálás; becsült elveszett PV-termelés; akkumulátor-élettartam jóslás; CO₂-megtakarítás. Az első verzió feladata: „Minden mérhető energiaáramlást helyesen, reprodukálhatóan és kizárólag kWh-ban elszámolni.”

**24. Beépítési sorrend** – 1. Új szigetüzem rendszer/fióktípus, teljesen elkülönítve a HMKE-től. 2. Általános kWh EnergyChannel modell. 3. load_energy kötelező csatorna. 4. PV/grid/generator opcionális források. 5. Akkumulátor charge/discharge csatornák. 6. Több PV/akku/forrás aggregálása. 7. HA total_increasing szenzorok validálása és kWh-normalizálás. 8. Baseline/history kezelés. 9. Napi/havi/éves delta-számítás. 10. Önellátottság/hálózati részarány. 11. Energiaegyensúly és adatminőség. 12. Reset/mérőcsere/entitáscsere kezelése. 13. Szenzorok létrehozása. 14. Panel/UI. 15. Valós inverteres tesztek. 16. Csak ezután haladó mutatók.

**25. Tesztmátrix** – Legalább: csak PV + fogyasztás; PV + akku + fogyasztás; PV + akku + grid backup; grid → load bypass; grid → battery; generátor; több akkumulátor; több PV inverter; nincs PV szenzor; nincs akku szenzor; nincs grid; akku tele; akku üres; HA restart; inverter reset; számláló visszaugrás; entitás unavailable; mérőcsere; hónapváltás; évváltás; eltérő kezdőállások; Wh → kWh; MWh → kWh; hiányos energiamérleg. Kell valós rendszeres regressziós teszt is: például egy Axpert/Victron/Deye rendszerből egy nap összes kWh számlálóját elmenteni, majd ellenőrizni, hogy a Rezsikövető ugyanazt az energiamérleget reprodukálja.

**26. Legfontosabb tervezési szabály** – A Rezsikövető csak azt állítsa biztos tényként, amit a rendelkezésre álló kWh mérőkből ténylegesen le lehet vezetni. Ha csak: PV = 20 kWh, Load = 15 kWh, Battery charge = 8 kWh, Battery discharge = 4 kWh áll rendelkezésre, abból ne találja ki, pontosan hány kWh ment PV → ház és PV → akku, ha a mérési topológia ezt nem teszi egyértelművé. Ez a kulcs ahhoz, hogy a Szigetüzem modul ugyanolyan szigorú legyen, mint a számlás rész.
