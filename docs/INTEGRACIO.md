# Rezsikövető integráció (2.1.0)

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

## Számlák felvitele

A számlákból jönnek a befizetések (ezekből az egyenleg és a várható elszámolás), a valódi mérőállások és gáznál a havi fűtőérték. Négy út van, a legkényelmesebbtől:

1. **Automatikusan a Díjnetről (ajánlott).** A Díjnet-integráció (HACS) letölti a számlákat egy mappába; a fiók **Számlamappa** mezőjében ezt a mappát add meg (a felület felajánlja a számlát tartalmazó mappákat, pl. `Dijnet /<szolgáltató>`). Az új fájlokat a Rezsikövető 10 percenként feldolgozza.
2. **Feltöltés a panelről.** Rezsikövető panel → a fiók kártyáján **Új számla** → **PDF vagy XML számla feltöltése**. A fájl a fiók számlamappájába kerül, és azonnal feldolgozódik; az ablak kiírja az eredményt (beolvasva / már szerepelt / más mérőé / nem ismertem fel). Telefonról is működik. (Szolgáltatásként: `hu_rezsi.szamla_feltoltes`.)
3. **Fájl bemásolása** a számlamappába (Samba, File editor, Studio Code Server) – ugyanúgy feldolgozódik, mint a letöltött.
4. **Kézi rögzítés:** **Új számla** → kelte, fizetendő összeg (visszatérítésnél mínusz), típus; ha a számlán szerepel: sorszám, elszámolt időszak, záró mérőállás (és hogy a szolgáltató olvasta-e le), gáznál fűtőérték. Bármelyik szolgáltatónál és szkennelt számlánál is működik. (Szolgáltatásként: `hu_rezsi.szamla_rogzites`.)

### Támogatott számlák

| Szolgáltató | XML | PDF | Mit vesz át |
|---|---|---|---|
| MVM Next – áram | ✅ (Díjnet `*_szamla.xml`) | ✅ (XML nélkül is; H-mérőnél a két regiszter összege) | fizetendő, diktált/leolvasott mérőállás |
| MVM Next – gáz | ✅ | – | fizetendő, mérőállás, havi fűtőérték |
| DAKÖV – víz | – | ✅ | fizetendő, fő- és almérő állása |
| MOHU – hulladék | ✅ | – | fizetendő |

- Ha egy számlához XML és PDF is van, az XML-t olvassa (pontosabb).
- A **fizetendő összeg** kerül befizetésként a számításba – elszámoló számlánál a részszámlák, az MVM közös ügyfélszámláján a korábbi túlfizetés levonása után; ez lehet negatív (visszajár).
- Becsült állás nem kerül be; a számla időszakán belüli, a szolgáltató által számított bontás (pl. az éves gázszámla jan. 1-je) sem. Elszámoló leolvasás csak egy elszámoló számla időszakának végén. A számlahatáron az előző záró és a következő induló állás (ugyanaz az érték egy nappal később) csak egyszer kerül be.
- A kézzel rögzített adat mindig erősebb: azonos napra nem ír felül leolvasást, és a kézzel megadott fűtőértéket sem. Ha egy záró állás ellentmond a meglévőknek (a mérő nem mehet visszafelé), a számla bekerül, az állás kimarad.
- Közös mappánál (pl. A1 és H egy szerződésen) a „Számla-mérők” mezőben a mérő gyári számával választható szét.
- Az új számlákról értesítés jön; az „Utolsó számla” entitás mutatja a legutóbbit.

### Ha egy fájlt nem ismer fel

Más szolgáltató számlája, szkennelt (képként mentett) PDF vagy nem számla: a Rezsikövető **értesítést küld** a fájl nevével, és a panel figyelmeztetései között is jelzi. Ilyenkor:

- rögzítsd a számlát kézzel (**Új számla**), és/vagy
- kérj beolvasót: GitHubon **Issues → New issue → „Új szolgáltató / számlaformátum”**, és csatolj egy **kitakart** mintaszámlát. Kitakarandó: név, cím, ügyfél- és szerződésszám, mérési pont azonosító, bankszámla. Az összegek, dátumok, mérőállások és a számla szerkezete maradjon – ezekből készül a beolvasó. XML-nél ugyanezeket a mezőket írd át (pl. „Minta Elek”).

A fel nem ismert fájlt a mappából törölve a figyelmeztetés is eltűnik.

### Számla törlése, újraolvasás

- Panel → **Részletek** → Számlák: jelöld be a törlendőket → **Kijelöltek törlése** → a megerősítő ablakban **Végleges törlés** (a befizetéssel és a mérőállással együtt). Szolgáltatásként: `hu_rezsi.szamla_torles`.
- A mappából beolvasott számla törlés után csak a **Számlák újraolvasása** (`hu_rezsi.szamlak_ujraolvasasa`) szolgáltatással jön vissza; ez a kézzel rögzített számlákat nem törli.

## Villany: az elszámolás módja

Villanyfióknál az **Elszámolás módja** mező dönti el az időszakot és a fizetés módját:

- **Diktálás** – időszak: az előző diktálás másnapjától a diktálás napjáig (`idoszak_mod: diktalas`); határ a számlákból jött leolvasás és elszámolt időszak, valamint a `diktalt: true` jelölésű leolvasás (`hu_rezsi.leolvasas_rogzites`). Keret: napi rész × az időszak napjai. Elmaradt diktálásnál a várható határ havonta tolódik.
- **Átalány** – részszámlás; a havi mennyiség a fiókban beírt *Átalány mennyisége havonta*, különben a legutóbbi MVM-számla „A következő részszámla becsült mennyisége” sora (PDF-ből; XML+PDF párnál a 13 hónapon belüli számlák PDF-jéből).
- **Távleolvasás** – naptári hónap, keret: napi rész × a hónap napjai.

Mód nélküli (régebbi) villanyfióknál az *Elszámolási időszak* és a *Fizetés módja* mező érvényes.

## D (dinamikus) árszabás és „mi lenne D-n”

`d_arak.py`: az MVM D-oldaláról a „negyedórás rugalmas egységárak” PDF (Ft/kWh nettó, kereskedői díjjal) letöltése naponta legfeljebb egyszer, órás átlagárrá alakítva, tárolva (`.storage/hu_rezsi_d_arak`, a régebbi hónapok megmaradnak). A koordinátor a fiók forrás-szenzorának órás statisztikájából naponként (q, q×ár, becsült) összegeket képez (`Fiok.d_napok`); a motor (`motor/rugalmas.py`) a szelet napjaira súlyoz. A `villany/d` díjszabás `rugalmas: true`: a keret feletti rész ára ez; közzétett ár híján a legutóbbi közzétett hónap súlyozott ára (`d_tartalek`, becsült). A1 fióknál `FiokAllapot.d_osszevetes`: időszakonként keret feletti kWh × (D-ár − A1 piaci ár) × ÁFA, az elmúlt 12 hónapra.

Negyedórás árak: a PDF negyedórás sorai is (`negyedek`, ~15 hónap). A közzétett lista utáni napokra `DArak.hupx_frissit` (3 óránként): energy-charts.info `price?bzn=HU` (EUR/MWh, negyedórás) × MNB SOAP `GetExchangeRates` EUR (munkaszüneti napon az előző jegyzés) / 1000 + 13,70 → `szamitott` és `szamitott_orak`; a `DArak.ar()` ezt is használja, így a folyó hónap nem becsült. Az MVM-lista megjelenésekor a számolt napok törlődnek.

**Számlák kimutatása** (`hu_rezsi/szamla_kimutatas`, `entry_id`): az otthon fiókjai (`sid`, `nev`, `kozmu`, `szolgaltato` – a díjszabás-tár neve) és fiókonként a tárolt számlák (`sorszam`, `kelte`, `osszeg`, `szamlaertek`, `tipus`, `idoszak`, `kezi`) kelte szerint rendezve; fiókrend: villany, gáz, víz, hulladék. A havi bontást, az összegzést (stornó = 0) és a Fizetendő/Számlaérték váltást a panel végzi. A nyomtatás a megjelenített táblázat klónjából önálló HTML-lapot ír egy rejtett iframe-be és annak `print()`-jét hívja (a panel árnyék-DOM-ja és sötét témája nélkül); a CSV ugyanebből az adatból Blob-letöltés (`;`, `\ufeff`, CRLF). Mobilon (`_mobil()`: mobil/„Home Assistant/” user-agent vagy durva mutató) a nyomtatás helyett `_kimutatasPdf()`: a táblázat 150 dpi-s fekvő A4-es vásznakra rajzolva (oldaltörés, a betűméret a szélességhez igazodik), oldalanként JPEG, ebből saját, minimális PDF 1.4 (DCTDecode képobjektum, xref) – beágyazott betűkészlet és külső könyvtár nélkül, az ékezeteket a vászon a rendszer betűjével rajzolja.

**D tarifa elemzés** (`hu_rezsi/d_elemzes`, `sid`, opcionális `honap`): a koordinátor `negyedek_frissit` óránként a forrás 5 perces statisztikájából negyedórás fogyasztást ment (`Store hu_rezsi_negyedek.<entry_id>`); hiányzó órára az órás statisztika negyede. A hónap kerete `_keret_nyers(keret, hónap eleje, következő hónap) × keret_szorzo` (kerekítve; a fő csatorna `keret_aktiv`-ja szerint), és időrendben fogy: negyedóránként a keret feletti rész `min(q, max(0, halmozott + q − keret))`; ebből `atlepes` (az első keret feletti negyedóra), `osszeg.keret_felett`, valamint `d_szamla` / `d_atlag` (az MVM számlázása: keret feletti mennyiség × a hónap teljes fogyasztásával súlyozott ár). A negyedórás mennyiség a motor havi `szamol` kWh-jához arányosítva (0,5–2 közötti szorzónál). Egy hónap: `_d_honap`; havi kimutatás: `d_havi_kimutatas` (folyó + 12 hónap; lezárt hónap gyorsítótárban `(fajl, szamitott_ig ha a hónap az MVM-lista után van)` kulccsal), ebből `_d_12ho` → a `d_kulonbseg` szenzor (`kulonbseg_12ho` = Σ(d_mvm − a1), `kulonbseg_12ho_sajat`); a koordinátor 6 óránként háttérfeladatban számolja. Forrás-szenzor nélkül `_d_honap` a motor havi mennyiségét (mérőállásokból) a hónap eltelt negyedóráira egyenletesen osztja (`egyenletes`), és `adat_ig` jelzi, ha az utolsó leolvasás a hónap vége előtt van (ilyen hónap nem kerül a 12 havi összegbe). A panel „MVM szerint” módja negyedóránként a hónap keret feletti arányát (felett/összes) alkalmazza egyformán – összege megegyezik a `d_szamla`-val. Visszaadja az idősort (`idok`, `fogyasztas`, `d_ar`), az árakat, az arányt és az összesítést; a költséget a panel számolja negyedóránként.

## Gáz mérő nélkül (átalánydíj)

`gaz/mero_nelkuli`: fix díjas fiók (`beallitas.fix_dijas` – a díjszabás is lehet fix díjas, nem csak a közmű), havi díj = `alapdij_ho` (2,465 Ft/MJ nettó) × `szorzok["atalany_mj"]`, ahol az MJ/hó a fiók `szobaszam` és `tuzhely` mezőjéből jön (`gaz_atalany.py`, MVM-táblázat). A varázsló ennél a díjszabásnál a mérő és a számla lépést kihagyja.

## A2 kétzónás tarifa: csúcs és völgy regiszter

Az A2 fióknál megadható a **csúcs (1.8.1)** és a **völgy (1.8.2)** regiszter szenzora (`a2_csucs_forras`, `a2_volgy_forras`). Ekkor a két regiszter külön csatorna (`zona_csucs` / `zona_volgy`, leolvasásnál is), saját kedvezményes áron; a 2 523 kWh/év keret a mérési pontra közös, a zónák között fogyasztásarányosan oszlik meg (egész kWh-ra, kumulatív kerekítéssel), és az elszámolási évben halmozódik. Regiszter-szenzorok nélkül a fiók fogyasztás-szenzorának **órás statisztikájából** bont (`motor/zona.py`): völgy munkanapon 22–06 (nyári időszámításban 23–07), nem munkanapon (hétvége, ünnep, áthelyezett pihenőnap – a `holidays` csomag szerint; a ledolgozós szombat munkanap) egész nap. Órás adat híján az órák arányából becsül.

## Gáz: kedvezményes keret a fizetés módja szerint

Fogyasztás szerinti (diktálásos) gázfióknál a 63 645 MJ/év keret **havonta súlyozott** (MVM, 2024. augusztus 1-jétől: január 12 365 … július 512 MJ/hó; a díjszabás `keret.havi` listája), a számla napjai szerint, és a **kedvezményes évben** (`keret.ev_kezdet: "08-01"`, aug. 1. – júl. 31.) halmozódik (sávkorrekció). Részszámlás (átalányos) fióknál a díjszabás `keret.reszszamla` változata érvényes: éves keret. Díjszabások: `gaz/lakossagi` (A1, 20 m³/h alatti mérő), `gaz/lakossagi_b1` (B1, alapdíj × a fiók `gazmero_teljesitmeny` m³/h-ja), `gaz/fogyasztoi_kozosseg` (A3, keret × (lakásszám + 1) vagy lakásszám).

## H-tarifa: téli és nyári regiszter

A H-tarifás fióknál megadható a **téli (1.81)** és a **nyári (1.82)** regiszter szenzora. Ekkor a két regiszter külön mérődik (külön leolvasás: `csatorna: h_teli` / `h_nyari`) és külön számolódik: a téli a H-áron, a nyári az A1 áron, saját 2 523 kWh/év kedvezményes kerettel (felette piaci ár), amely csak a nyári időszakban (ápr. 15. – okt. 15.) gyűlik, és az elszámolási évben (éves leolvasástól éves leolvasásig) halmozódik (sávkorrekció). A téli fogyasztásra nincs keret, és a keretbe sem számít bele. Októberben és áprilisban mindkét tarifa külön sorban jelenik meg.

## Átalány

Bármely fiók lehet **részszámlás (átalány)**. Ilyenkor a panelen „átalány” jelzés látszik, és a **Havi fizetendő (átalány)** = az átalány napra leosztva × a hónap napjai. A napi összeg az utolsó részszámla összege osztva az időszakának napjaival, vagy a beállított havi átalány × 12 / 365. Ha a szolgáltató **mennyiséget** számláz átalányként (pl. MVM: 293 kWh/hó), az „Átalány mennyisége havonta” mezőben adható meg: napra leosztva × a hónap napjai, a fiók díjszabásával beárazva. A háztartás havi összesítőjében az átalányos szolgáltatás a fizetendővel szerepel; a panel tételes forintszámítás helyett a fogyasztást mutatja, összevetve az átalány mennyiségével. A várható elszámolás és az éves egyenleg a tényleges fogyasztásból számol.

## Számlázási ütem, elszámolási ciklus, esedékes számlák

Fiókonként megadható a **számlázási ütem** (havonta, kéthavonta, negyedévente) és az **elszámolási ciklus** (félévente, évente). A kártya mutatja a szolgáltatót, az ütemet és a következő elszámolás várható idejét; az egyenleg az elszámolási ciklusra számol (pl. DAKÖV: félévente, közben 2 kéthavi részszámla). A háztartás összesítőjének fő száma az **ebben a hónapban esedékes számlák** összege: a már kiállítottak és az ütem szerint még várhatók (a következő számla = az utolsó + az ütem; összege átalánynál az ütem hónapjainak átalánya, fix díjnál a díj). A késő számla „késik” jelzést kap.

## Fix díjas fiók (hulladékszállítás)

Közmű: „Hulladékszállítás (fix díj)”. Nincs mérő: a költség a díjszabás havi díjrésze, az időszak a naptári negyedév (a számlázás ütemezése szerint), a havi rész a `havi_resz` attribútumban; a háztartás havi összesítőjébe a havi rész kerül. A számlák a számlamappából (pl. `Dijnet /mohu_zrt`) jönnek; a „Következő számla várható” figyelmeztet, ha a díj változik vagy egy számla elmarad.

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
| `hu_rezsi.szamla_rogzites` | Kézi számla (kelte, összeg, típus, sorszám, időszak, záró mérőállás, fűtőérték) – mint egy beolvasott; időszak nélkül a kelte előtt zárult, még nem számlázott időszakhoz rendeli |
| `hu_rezsi.szamla_feltoltes` | PDF/XML számla feltöltése a fiók számlamappájába és azonnali feldolgozás (válaszként az eredmény) |
| `hu_rezsi.szamla_torles` | Egy számla törlése sorszám szerint, a befizetéssel és a mérőállással együtt |
| `hu_rezsi.szamlak_ujraolvasasa` | A mappából jött számlák törlése és teljes újraolvasás (a kézi számlák maradnak; opcionálisan minden mérőállás törlése) |

## Átállás a v1 YAML-csomagról

1. Telepítsd az integrációt, és vedd fel a fiókokat. Forrásnak a v1 óraállás-szenzorait add meg „Mérőóra-állás” módban: `sensor.meroora_allas`, `sensor.meroora_allas_h`, `sensor.gaz_meroora_allas`.
2. Futtasd a `hu_rezsi.v1_import` szolgáltatást **próbafuttatással**, és nézd át a jelentést.
3. Ha rendben van, futtasd `probafuttatas: false`-szal. Átkerül a leolvasási napló (elszámoló leolvasásként, a mérők kezdetével és a H-óra felszerelésével) és a lezárt havi elszámolások (A1/H szétbontva).
4. **Egy hónapig fusson párhuzamosan a két rendszer.** A v1 csomagot csak azután töröld, ha a hónapzárások egyeznek.

A korrekció-típusú v1 bejegyzéseket az importáló kihagyja; ezeket kézi leolvasásként rögzítsd.

## Hibakeresés

**Beállítások → Eszközök és szolgáltatások → Rezsikövető → ⋮ → Diagnosztika letöltése.** Benne vannak a fiókok beállításai, a tárolt adatok és a számláló utolsó pontjai.

## Kezdő óraállás mint elszámolási origó

`modell.kezdo_origo_szinkron`: ha a fiók beállításában van kézzel megadott `kezdo_allas` (a `beepitve` kezdőnappal), a tár `kezdo_origo` mezőjébe kerül ({datum, allas}); minden frissítéskor szinkronizálódik (kiürítve törlődik). A `_eves_napok` az elszámolási leolvasások mellé ezt a napot is felveszi, így `eves_bazis`, `elszamolasi_napok`, `elozo_bazis` is számol vele (a ≥300 napos szűrés szerint egy későbbi éves leolvasás átveszi a helyét). A panel a mérőállások közé `tipus: "kezdo"` sorként teszi (mindig látszik). A számláló a kezdőállást továbbra is a mérő `kezdo_allas`-ából veszi (egymérős fióknál `mero_szinkron`).

## Elszámolási módok: távleolvasás, diktálás, átalány

- Távleolvasásnál (`elszamolas_mod == "tavleolvasas"`) az ütem `kovetkezo_diktalas` és `diktalasi_ablak` mezője üres – a panel nem mutat diktálást.
- Átalánynál `koordinator._diktalt_szamla`: a legutóbbi számla elszámolt időszakának (`_szamlazott_idoszak`) vége utáni legutolsó `diktalt` saját állásig `szamol` (alapdíjjal) → `FiokAllapot.diktalt_szamla`; ez a `varhato_szamla` (esedékesség) és a nem kiállított kéthavi ablak fizetendője. Egyszeri: a következő beolvasott számla időszaka átlépi a diktálás napját, és a felülírás megszűnik.
- `koordinator._szamla_alapu_allasok`: részszámlánként (`_atalany_mennyiseg_szamlan`: `elszamolt_kwh`, `elszamolt_gaz.m3`, átalányos `elszamolt_viz.ivoviz`) az időszak elején aktív mérő utolsó valódi állása (vagy kezdőállása), ill. ha azóta nem volt valódi állás, az előző becsült állás + a számlázott mennyiség, az időszak utolsó napjára. A panel `tipus: "szamla_atalany"` sorként mutatja; a számlálóba nem kerül.

## Diktálás: időszak két leolvasás között

`beallitas.idoszak_mod`: tiszta diktálásnál (`elszamolas_mod == "diktalas"`) `"leolvasas"`, átalánynál `"diktalas"`. `modell.diktalasi_hatarok(tarolt, minden_leolvasas=True)`: minden vételezési leolvasás, a mérők beépítése és a `kezdo_origo` (számla-időszakok nélkül). `motor/elorejelzes.idoszak(..., "leolvasas")`: mint a diktálási, de az utolsó határ után nem görget havonta (`gorget=False`). `koordinator._leolvasasos_lezartak`: a lezárt lista = egymást követő határpárok a nyitott időszakig; a hiányzót `szamol`-lal pótolja, az átfedő, nem egyező régi bejegyzést törli, `nyitott_tol` = az utolsó határ.

## Munkarend, díjszabás-metaadat, számla-összevetés

- `motor/munkarend.py`: `unnepnapok(ev)` (Mt. 102. §, `husvetvasarnap`), `ATHELYEZESEK` (év → rendelet, ellenőrizve, (munkanap, pihenőnap) párok), `munkanap(nap)`; a `motor/zona.py` ezt használja. Ismeretlen évre a `holidays` csomag „…-től helyettesítve” bejegyzései (ha telepítve), különben áthelyezés nélkül.
- Díjszabás-verzió: `ellenorzes: {allapot, datum, mivel, validalas}` (`ELLENORZES_ALLAPOTOK`), `ervenyes_ig`; a betöltő ellenőrzi, egy teszt minden beépített fájlra megköveteli. Panel: `dijszabas_info` (a Részletek „Díjszabás” ⓘ buborékában a validáló számlák is).
- **Validálás (2026-10-05):** díjszabás csak akkor `szamlaval_egyezik`, ha **valódi számlákkal** is forintra egyezik – a unit tesztek csak regresszióvédelem. Ilyenkor kötelező a `validalas` lista, számlacsoportonként: `szolgaltato` (a `szolgaltatok.yaml` kulcsa – villanynál ez az elosztói terület is, pl. `mvm_demasz`), `elszamolas` (`diktalas` / `atalany` / `leolvasas` / `tavleolvasas` / `fix`), `szamla_tipusok` (`havi`, `resz`, `elszamolo`, `ketthavi`, `negyedeves`, `vegszamla`), `szamlak` és `forintra` (egész), opcionálisan `hely`, `idoszak`, `max_elteres_ft`, `megjegyzes`. **HMKE-nél** kötelező a `hmke: szaldo | brutto` is (`VALIDALAS_*` a `motor/dijszabas.py`-ban). Példa:
  ```yaml
  ellenorzes:
    allapot: szamlaval_egyezik
    datum: 2026-10-04
    mivel: "hu_rezsi.szamla_osszevetes …"
    validalas:
      - {hely: Városi lakás, szolgaltato: mvm_demasz, elszamolas: diktalas, szamla_tipusok: [havi, elszamolo], idoszak: "2024-12 – 2026-09", szamlak: 17, forintra: 14, max_elteres_ft: 2}
  ```
- `Szamla.szamlaertek`, `Szamla.levont_szamlak` ([sorszám, összeg|None]); tárolva `szamlaertek`, `levont_szamlak` (meta-pótlás v4, ~3 év). `koordinator._szamla_teljes_dija`: számlaérték + levont részszámlák (hiányzó összeg a tárolt részszámlából; lista híján az időszakba eső részszámlák). `koordinator.szamla_osszevetes(sid, honap)` → `hu_rezsi.szamla_osszevetes`; az ablak a leolvasási napokhoz igazodik.
- Alapdíj `mod: idoszakonkent`: szeletenként `havi × (hónap 1-jei a [a, b) szeletben)`; idényszakos díjszabásnál a hónap 1-jén érvényes idény díjszabásának `alapdij_ho`-ja.
- Gáz: `Szamla.korrekciok` és a tételidőszak minden hónapjára `futoertekek` (`_honapok`); `rogzit`: elszámolónál felülír, és `tarolt["korrekciok"]`; `Fiok.korrekciok`, `motor/elszamolas.korrekcio()` (hónap → legutóbbi elszámolóé → díjszabás alapértéke). Meta-pótlás v5: a tárolt gázelszámolók újraolvasva (csak ezek az értékek).
- Keret kerekítés: `Fiok.szamlazasi_hatarok` (diktálási/leolvasási határok, `modell._szamlazasi_hatarok`) ill. `Fiok.szamlazas_havi`; `_osszesitett_kedvezmenyes` ezek (és a keret `tetel_hatar`) mentén szakaszonként kerekít (`szamlankent`), a gáz (`visszamenoleges: false`) változatlan. Alapdíj: diktálásnál a hónap-1-jei az (a, b] napok közül, egyébként [a, b).
- `modell._eves_napok`: a `evkezdet` jelölésű leolvasások és a `kezdo_origo` napja mindig évkezdet (`kenyszer`), a többi elszámolási leolvasásra a ≥300 napos szűrő.

## Fiók lezárása (végelszámolás)

`hu_rezsi.fiok_lezarasa` (`datum`, `zaro_allas`, `visszavonas`): `tarolt["megszunt"] = {datum, allas}`, a záró állás `vegleolvasas: true, diktalt: true` leolvasásként (diktálásnál határ). `_fiok`: ha a lezárás napja elmúlt, `most` = a lezárás napja 0:00, az időszak `idoszak(veg − 1 nap)`–`veg`; leolvasásos módban a `_leolvasasos_lezartak` `veg`-ig zár, egyébként egy „végelszámolás” forrású lezárt bejegyzés; `nyitott_tol` = `veg`. `_varhato_elszamolas` lezárt fióknál számla nélkül is az éves bázistól számol. Panel: `megszunt`; a havi összegekből a korábbi hónapban lezárt fiók kimarad. Visszavonás: a `megszunt`, a végleolvasás és a „végelszámolás” bejegyzés törlése, `nyitott_tol` újraszámolva.

## Mérőcsere

`hu_rezsi.merocsere`: a nap aktív mérője `kiszerelve` + `zaro_allas` (H-nál `zaro_h_teli`/`zaro_h_nyari`), új mérő `beepitve` + `kezdo_allas` (`kezdo_h_teli`/`kezdo_h_nyari`); a záró állás nem lehet kisebb a régi mérő leolvasásainál, és a csere utáni napra nem lehet rajta leolvasás. `visszavonas: true`: az utolsó mérő törlése (ha nincs rajta leolvasás), az előző újra nyitott. Diktálásnál a mérő beépítése időszakhatár (`diktalasi_hatarok(..., minden_leolvasas=True)`). Panel: a Mérőállás ablak „Mérőcsere” módja.

## Tört év, az elszámolási év hossza

`CONF_KOV_EVES` (`kovetkezo_eves_leolvasas`, a varázsló számla-lépésében): `koordinator._ciklus` a számlán közölt következő leolvasás híján ebből adja a következő elszámolást (ha elmúlt, ciklusonként tovább; 12 hónap + 31 napnál távolabbit figyelmen kívül hagy). `_egyenleg`: ha ez >45 nappal eltér a bázis + ciklustól, `eves_egyenleg(ev_ig=…)` és a részszámlák száma a tört év hónapjaiból. `modell._eves_napok`: két (valódi vagy kényszerített) évkezdet között, ill. az utolsó után a mai napig, ha a különbség > 12 hónap + `EVES_TURES_NAP` (31), évfordulónként virtuális évhatár; `eves_bazis` éves leolvasás nélkül is évfordulónként lép.
- Lezárt fióknál az esedékesség a mai nap szerint számol; fix díjnál a `vegszamla` (az első várható számla, amelynek hónapja a lezárás időszaka után van, a töredék díjjal), és `nincs_tobb`, ha egy számla időszaka eléri a lezárás időszakát (mért fióknál mindig – ott a „még nem érkezett számla” jelzi a végszámlát).

## MVM gáz PDF (XML nélkül), többhavi számlázás eltolása

`szamlak.mvm_gaz_szoveg`: a `beolvas_fajl` XML nélküli PDF-ágában a DAKÖV és az MVM-áram után; a számlaérték a „Számla összesen:” sor utolsó (bruttó) száma (a „Bruttó számlaérték összesen** 27 3 475” sorban az ÁFA-kulcs összeolvad). `szamla_import.szamlazasi_eltolas(tarolt)`: a legutóbbi időszakos számla elszámolt időszakának kezdete − a kiállítás hónapja (hónapban); a `szamlazasi_ablak` ezzel számol (alapból −periódus, utólagos). A varázsló fix díjas fióknál (hulladék, `gaz/mero_nelkuli`) a számla-lépést mutatja, a mérő-mezők nélkül.
