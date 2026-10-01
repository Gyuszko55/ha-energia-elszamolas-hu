# 05 – Napelem (HMKE): mit kell figyelembe venni, honnan jön az adat

> **Állapot:** 2026-10-01. A fejlesztők egyikének sincs napeleme, ezért ez a fejezet **nyilvános forrásokra
> és szintetikus tesztekre** épül. Minden bizonytalan pont jelölve van; élesben csak „kísérleti” jelzéssel
> kerülhet ki, amíg napelemes felhasználók valódi számláival nem ellenőriztük.

## 1. Mi számít az elszámolásban?

**Csak az, ami a hálózati csatlakozási ponton (az ad-vesz mérőn) átmegy:**

| Mérőregiszter | Jelentés | Rezsikövető-csatorna |
|---|---|---|
| 1.8.0 (tarifánként 1.8.1, 1.8.2…) | a hálózatból vételezett energia | `vetelezes` |
| 2.8.0 | a hálózatba betáplált energia | `betaplalas` |

A **termelés**, a **saját fogyasztás** és az **akkumulátor** az elszámolásban közvetlenül nem jelenik meg,
csak annyiban, amennyiben megváltoztatja a vételezést és a betáplálást. Ezeket az elemzéshez (megtakarítás,
megtérülés – 4. lépcső) használjuk, nem a számla kiszámításához.

## 2. Esetek, amelyekkel számolni kell

| Szempont | Változatok | Mit jelent a motorban |
|---|---|---|
| Elszámolási mód | **szaldó** (az üzembe helyezéstől 10 évig, ha az igény 2023-09 előtt ment be) · **bruttó** (2024-től az új rendszerek, illetve kérésre) · **szaldóból bruttóra váltás** a 10 év lejártakor | díjszabás-hozzárendelés dátummal: a váltás napján új időszak |
| Elszámolás gyakorisága | szaldó: **éves** nettózás, közben részszámlák (átalány) · bruttó: **havi** | szaldó → éves egyenleg (a részszámlás logika újrahasznosítva) |
| Akkumulátor | nincs · van (csak napelemről tölt) · van (hálózatról is tölt, pl. dinamikus tarifával) | az elszámolásra nincs közvetlen hatása; megtakarítás-elemzés a 4. lépcsőben |
| Tarifa | A1 · A1 + H (külön mérő) · B (vezérelt) · A2 (kétzónás) · később dinamikus | a vételezés a meglévő díjszabások szerint; a betáplálás mindig a `villany/hmke` szerint |
| Fázisszám | 1 fázis · 3 fázis | 3 fázisnál a mérő összegez – **ellenőrizendő**, hogy fázisonként vagy összesítve |
| Teljesítmény | HMKE: legfeljebb 50 kVA | e fölött nem lakossági (nem célunk) |

## 3. A két elszámolás szabályai (források: `dijszabasok/villany/hmke.yaml`)

### Bruttó (2024-01-01-től)
- Havonta külön számolják a vételezést és a betáplálást.
- **Vételezés:** rendes díjszabás (energiadíj, rendszerhasználati díj, alapdíj, rezsicsökkentett keret).
- **Betáplálás:** átvételi áron jóváírva, elosztónként: MVM Démász 5,25 · MVM Émász 4,94 · E.ON és OPUS TITÁSZ 4,39 · ELMŰ 5,11 Ft/kWh.
  (Megfigyelés: ezek pontosan a kedvezményes villanyár nettó energiadíj-részei.)
- A jóváírás külön számla vagy fizetési kérelem alapján megy.

### Szaldó (10 évig)
- **Éves** nettózás: vételezés − betáplálás az elszámolási évre (két éves leolvasás között). Év közben részszámlák.
- Vételezési többlet: a nettó mennyiség a rendes díjszabás szerint.
- Kiegyenlített év: csak a forgalomtól független díjak (alapdíj).
- Betáplálási többlet: alacsony átvételi áron jóváírva (4/2011 NFM rendelet; MVM Next szerződésben 1 Ft/kWh).

## 4. Nyitott kérdések (ellenőrizendő, mielőtt élesnek mondjuk)

| # | Kérdés | Mostani feltételezés a kódban |
|---|---|---|
| NQ1 | Szaldónál a rezsicsökkentett keret (2 523 kWh/év) a **nettó** vételezésre jár? | igen, az eltelt napokkal arányosan |
| NQ2 | Szaldónál a rendszerhasználati díj a nettóra vagy a teljes vételezésre jár? | a nettóra |
| NQ3 | A szaldós többlet átvételi ára ma is 1 Ft/kWh? Változik? | 1 Ft/kWh, felülírható |
| NQ4 | A betáplálás jóváírásán van-e ÁFA (magánszemély nem ÁFA-alany)? | nincs, a megadott összeg jár |
| NQ5 | A bruttó átvételi ár évente változik? Kötődik a kedvezményes energiadíjhoz? | rögzített, verziózható |
| NQ6 | Szaldó → bruttó váltásnál hogyan osztják meg az évet (záró elszámolás a váltás napján?) | a váltás napján lezárt szaldó-év, utána havi bruttó |
| NQ7 | 3 fázisú mérő: fázisonkénti vagy összegzett regiszterek? | összegzett |
| NQ8 | H-tarifás külön mérő napelemes háztartásban: a betáplálás melyik mérőn megy? | az A1 (ad-vesz) mérőn |

## 5. Honnan jön az adat?

| Forrás | Mit ad | Pontosság | Megjegyzés |
|---|---|---|---|
| **A HA Energia irányítópult beállítása** | a már beállított hálózati vételezés- és betáplálás-szenzorok | amennyire a szenzor | **Javasolt alapértelmezés:** a Rezsikövető kiolvashatja a `grid` forrás `flow_from` / `flow_to` statisztikáit, így nem kell újra beállítani |
| Okosmérő HAN/P1 port (pl. DSMR-olvasó) | 1.8.0 / 2.8.0 közvetlenül a mérőből | **a számlával azonos** | a legjobb forrás, ha a mérő engedi |
| Inverter-integráció (Huawei, Fronius, SolarEdge, Growatt, GoodWe, Deye/Solarman, SMA…) | termelés, akkumulátor, és ha van saját fogyasztásmérője: hálózati vételezés és betáplálás | jó (±1–3%) | az inverter mérője nem hitelesített; szorzóval korrigálható |
| Kétirányú Shelly (Pro 3EM, EM) | `total_active_energy` és `total_active_returned_energy` | jó | 3 fázisnál a fázisok összege |
| Kézi leolvasás | 1.8.0 és 2.8.0 a mérő kijelzőjéről | pontos | a `leolvasas_rogzites` csatornával (`vetelezes` / `betaplalas`) |
| Számla, elszámoló számla | elszámolt mennyiségek és díjak | hivatalos | ellenőrzéshez, és a részszámlák forrásaként (Díjnet) |
| Elosztói okosmérő-portál (15 perces adatok) | vételezés és betáplálás idősorként | pontos | később CSV-importtal |

## 6. Hogyan ellenőrizzük napelem nélkül?

1. **Szintetikus tesztek** a dokumentált szabályokra (`tests/motor/test_napelem.py`: bruttó havi, elosztónkénti ár, szaldó vételezési és betáplálási többlet, év közbeni arányos keret).
2. **Valódi számlák napelemes felhasználóktól**, anonimizálva (név, cím, azonosító nélkül): legalább egy bruttó havi számla és egy szaldós éves elszámoló számla, lehetőleg akkumulátoros és 3 fázisú esettel is. Ezekből számlatesztek lesznek, ahogy a villany-, gáz- és vízszámlánál.
3. **Élő próba szimulált fiókkal** a saját HA-nkon (a vételezés és a betáplálás helyére meglévő szenzorok), csak a működés ellenőrzésére.
4. Amíg a 2. pont nincs meg, a napelemes fiók **„kísérleti”** jelzést kap a felületen és az entitások attribútumaiban.

## 7. Ütemterv

- [x] **N0** Ez az összefoglaló, forrásokkal és nyitott kérdésekkel
- [x] **N1** Motor: bruttó és szaldó elszámolás (`motor/napelem.py`), szintetikus tesztek
- [ ] **N2** HA-réteg (kísérleti): napelemes mód a fiókban, betáplálás-forrás (Energia-beállításból, szenzorból vagy kézi leolvasással), entitások: betáplálás, jóváírás, egyenleg / szaldó
- [ ] **N3** Valódi számlák gyűjtése napelemes felhasználóktól (GitHub-felhívás) → számlatesztek → a „kísérleti” jelzés levétele
- [ ] **N4** Akkumulátor és önfogyasztás: megtakarítás-elemzés (4. lépcső)
