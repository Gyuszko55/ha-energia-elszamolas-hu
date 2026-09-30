# Használati útmutató

> [!IMPORTANT]
> **Tájékoztató jellegű számítás, nem helyettesíti a szolgáltatói számlát.**
> A csomag a saját mérőid adataiból és a beírt árakból becsül. A fizetendő összeg mindig a szolgáltató számláján szerepel.
> **Eltérések lehetnek.** A csomag naptári hónapokkal (1-jétől a hónap végéig) számol. Ha a szolgáltató leolvasási, elszámolási időszaka nem a hónap első napjával kezdődik, a sávok, a havi összegek és az éves összesítő is eltérhetnek a számlától. Eltérést okozhat még a saját mérő pontatlansága, a kerekítés, az árváltozás időpontja, és a számlán szereplő egyéb tételek (pl. díjak, kedvezmények, ÁFA-bontás).


Az **Energia-elszámolás** nézet három oszlopból áll:

- **Havi villany-elszámolás:** a folyó hónap, a szolgáltató és a tarifák, és a lezárt hónapok.
- **Mérőóra leolvasás:** az óraállások, a leolvasás és csere rögzítése, és a napló.
- **Beállítás:** a források és az első beállítás.

> **A legfontosabb szabály:** a kedvezményes (rezsi) keret **mérőóránként** jár. A főmérőre (A1) és a H-tarifás mérő nyári részére külön-külön napi 6,91 kWh, vagyis havonta 6,91 × a hónap napjai. Ami efölött van, azt piaci áron számolják.

## 1. A havi villany-elszámolás

![Havi villany-elszámolás](kepek/folyo.png)

- **Fejléc:** a folyó hónap, és hogy hányadik napjánál tart.
- **Sáv-csíkok:** mérőnként mennyi fogyott a havi keretből. Zöld: még belefér. Narancs: túllépve, a többlet piaci áron megy.
- **Tételek:**
  - sávon belüli és feletti kWh a főmérőn és a H nyári részén;
  - télen a H kedvezményes (1.81) sor;
  - a fix havi alapdíj.
- **Eddig:** a mai napig fizetendő összeg.
- **Várható:** a hónap végére becsült összeg. Az eddigihez hozzáadja az utolsó 7 nap napi átlagát, szorozva a hátralévő napokkal. A 7 napos átlag a telepítés után egy hétig még pontatlan.
- **Megosztott hónap:** ha a hónapban éves leolvasás volt, a hónap a leolvasás napjával két részre oszlik. Az első rész a lezárt évhez tartozik, a második már az újhoz. A keret és az alapdíj napokra arányosan oszlik meg.

## 2. Szolgáltató és tarifák

![Szolgáltató és tarifák](kepek/tarifak.jpg)

- **Szolgáltató:** válaszd ki a sajátodat. A díjtáblázat kiemeli a sorát, a „Számolt árak” mezőkbe pedig betöltődnek az árai.
- **Számolt árak:** ezekből számol az elszámolás. Ha a számládon más ár szerepel, írd át. Tizedesvesszővel vagy ponttal is beírhatod, Enterrel vagy a mezőből kilépve ment.
- **Rezsisáv:** a napi keret mérőóránként, alapból 6,91 kWh.

Az új ár a folyó hónap egészére érvényes, a lezárt hónapok a saját áraikkal maradnak. Szolgáltató-váltáskor a kézzel beírt árak helyére a táblázat árai kerülnek.

## 3. Lezárt hónapok és az éves elszámolás

![Lezárt hónapok](kepek/lezart.png)

- **Dőlt sor:** a még le nem zárt, folyó hónap.
- **Egy hónap sora:** A1, H nyári és H téli fogyasztás, a sáv feletti rész mérőnként (narancs, ha volt), és a havi összeg. A kWh-k egy tizedesre kerekítve látszanak, így kézzel összeszorozva is kijön az összeg, legfeljebb 1–2 Ft eltéréssel.
- **Kék „Éves elszámolás” sor:**
  - felül egy sorban az időszak és a megjegyzések;
  - alatta az „Összesen”: a két éves leolvasás közötti időszak fogyasztása mérőnként, a sáv feletti kWh és a teljes összeg, vagyis a szolgáltató által elszámolt éves áramdíj.
- **Csillag (\*):** becsült vagy részleges hónap.

A hónapot a Home Assistant minden hónap 1-jén éjfél után magától lezárja, és ide írja.

## 4. Mérőóra leolvasás

A kártya tetején látszik a HA szerinti mostani óraállás és az éves fogyasztás mindhárom mérőre. Alatta:

1. **Típus:** Éves leolvasás vagy Mérőcsere.
2. **Mérő kapcsolója** (A, H, Gáz): csak azt kapcsold be, amelyikről adatot írsz be.
3. **Adatok:** dátum, a leolvasott óraállás és szükség esetén korrekció. Mérőcserénél az óraállás a **leszerelt** óra végállása, alatta az új óra kezdőállása.
4. **Eltérés a HA-tól:** mennyivel mutat mást a valódi óra, mint a HA. Ezt írhatod be korrekciónak.
5. **Mehet:** rögzíti a bejelölt mérők adatait a naplóba, utána kiüríti a mezőket.

![Leolvasási napló](kepek/naplo.png)

A **Leolvasási napló** mindent visszamenőleg mutat, és a szűrővel mérőre vagy típusra szűkíthető. A Fogyasztás oszlop az előző éves leolvasás óta eltelt fogyasztás.

## 5. Gyakori teendők

### Megjött az éves leolvasás

1. Típus: **Éves leolvasás**. Kapcsold be a leolvasott mérő(ke)t.
2. Írd be a dátumot és a leolvasott óraállást. Ha az „Eltérés a HA-tól” nagy, írd be korrekciónak.
3. **Mehet**, majd erősítsd meg.

Ettől kezdve az éves fogyasztás nulláról számol, a lezárt évet a napló megőrzi, és a havi elszámolásban kék összesítő sor jelenik meg.

### Kicserélték a mérőórát

1. Típus: **Mérőcsere**. Kapcsold be a kicserélt mérőt.
2. Óraállás: a **leszerelt** óra utolsó állása. Új óra: az új óra kezdőállása. Dátum: a csere napja.
3. **Mehet**.

A HA ezután az új órát mutatja, de az éves és havi fogyasztás nem ugrik meg, mert a csere nem számít fogyasztásnak.

### A HA óraállása nem egyezik az órával

1. Kapcsold be a mérőt, és írd be a mostani óraállást és a dátumot.
2. Az „Eltérés a HA-tól” értékét írd be korrekciónak.
3. **Mehet**.

Ha az eltérés tartósan, arányosan nő, állítsd a **Beállítás / A1 szorzó** értékét. Ha például a hivatalos óra 4%-kal többet mutat, írj be 1,04-et.

### Régebbi leolvasást vinnél fel

Ugyanúgy, mint az éves leolvasásnál, csak a régi dátummal. Ha a dátum régebbi a legutóbbi éves leolvasásnál, a bejegyzés csak a naplóba kerül, és a mostani számítást nem változtatja meg.

### Változtak az árak

Írd át a „Számolt árak” mezőt. Ha a szolgáltató tartósan árat változtat, a díjtáblázatot is frissítsd a `hu_energia_elszamolas.yaml` fájlban.

## 6. Ha valami nem stimmel

| Mit látsz | Mi lehet az oka | Mit tegyél |
|---|---|---|
| A havi kártya „Nincs adat” | Nincs megadva az A1 forrás, vagy nem futott le az első beállítás. | Beállítás → Források, majd „Első beállítás”. |
| Az „A1 forrás” nem elérhető | Elírt entitás-azonosító. | Fejlesztői eszközök → Állapotok: másold ki pontosan. |
| A sáv-csík a hónap elején narancs | A keret havi: a hónap elején még kicsi, a hónap végéig nő. | Nincs teendő, a „Várható” mutatja a hónap végi helyzetet. |
| A havi vagy éves összeg eltér a számlától | Tájékoztató számítás. A szolgáltató elszámolási időszaka nem a hónap 1-jétől tart, eltér a saját mérőd, vagy a számlán más tételek is vannak. | A számla a mérvadó. A leolvasás napját rögzítsd éves leolvasásként, a szorzóval és a korrekcióval igazítsd a mérést az órához. |
| A „Várható” furcsán magas vagy alacsony | Az utolsó 7 nap átlaga, telepítés után még kevés adatból. | Egy hét után beáll. |
| A „Mehet” után nem került be semmi | Nem volt bekapcsolva a mérő, vagy üres maradt az óraállás. | Kapcsold be a mérőt, írd be az állást, és nyomd meg újra. |
| Rossz adatot rögzítettem | Elírás. | A bejegyzés törölhető eseménnyel (lásd README → Mentések). A korrekciót egy ellentétes korrekcióval vond vissza. |
| A táblázatok helye üres | Hiányzik a html-template-card (HACS). | Telepítsd, és frissítsd az oldalt. |
| A beviteli mezőknél „Custom element doesn't exist: hu-szam-sor” | Nincs regisztrálva az erőforrás. | README → Telepítés, 4. lépés. |
