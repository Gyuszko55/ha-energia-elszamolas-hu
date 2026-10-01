# 02 – A díjszabás-fájlok formátuma

## Cél

A hivatalos díjak és szabályok **adatfájlokban** élnek, nem a kódban. Díjváltozáskor csak egy új
verzió-blokk kerül a fájlba, és az integráció új kiadást kap. A kódhoz akkor kell nyúlni, ha egy
**új fajta szabály** jelenik meg, amit a meglévő szabályelemek nem tudnak leírni.

## Mappaszerkezet

```
custom_components/hu_rezsi/dijszabasok/
├── villany/
│   ├── a1.yaml          # általános
│   ├── a2.yaml          # kétzónás (később)
│   ├── b.yaml           # vezérelt (később)
│   ├── h.yaml           # hőszivattyús, idényes
│   └── napelem.yaml     # betáplálás: szaldó / bruttó (3. lépcső)
├── gaz/
│   └── lakossagi.yaml
├── viz/
│   └── egyedi.yaml      # nincs országos díj, sablon a kézi megadáshoz
└── szolgaltatok.yaml    # szolgáltató-kulcsok és megjelenítendő nevek
```

## Egy díjfájl felépítése

```yaml
azonosito: villany/a1
nev: "A1 – általános lakossági"
kozmu: villany
egyseg: kWh
verziok:                         # időrendben; a legújabb a lista végén
  - ervenyes_tol: 2026-01-01
    forras: "MVM hirdetmény, 2026. január (link)"
    szabalyok:
      keret:
        tipus: napi_aranyos      # a keret az időszak napjaival arányos
        ev_mennyiseg: 2523       # kWh/év → 6,912 kWh/nap
        hatar_felett: piaci      # a keret feletti rész ára
    dijak:
      alap:                      # ha a szolgáltatónál nincs külön sor, ez érvényes
        energia_kedvezmenyes: 36.386   # Ft/kWh, bruttó
        energia_piaci: 70.104          # Ft/kWh, bruttó
        alapdij_ho: 153.035            # Ft/hó, bruttó
      eon:
        energia_kedvezmenyes: 35.293
      elmu:
        energia_kedvezmenyes: 36.208
```

### Szabályok

- **Minden díj bruttó Ft.** Az áfabontás csak megjelenítési kérdés, nem a számítás része.
- **`forras` kötelező.** Hivatalos dokumentum, hirdetmény vagy saját számla hivatkozása. E nélkül a fájl nem kerül be.
- **Régi verzió soha nem módosul**, kivéve ha bizonyítottan hibás volt. Ilyenkor a változásnaplóban jelezni kell.
- **A szolgáltatói sor csak az eltérést tartalmazza.** A hiányzó mezők az `alap` sorból öröklődnek.

## Szabályelemek

Egy díjszabás néhány előre definiált építőelemből áll. Új tarifa = meglévő elemek új kombinációja.

| Elem | Változatok | Mire jó | Mikortól |
|---|---|---|---|
| `keret` | `napi_aranyos`, `eves`, `nincs` | Kedvezményes mennyiség és a felette lévő ár | 1. lépcső |
| `idenyszak` | dátumtartományok | H-tarifa: télen saját ár, nyáron egy másik díjszabás (A1) szerint | 1. lépcső |
| `atvaltas` | `gaz_mj` | m³ → MJ fűtőértékkel és korrekciós tényezővel | 2. lépcső |
| `csatornadij` | ár + kapcsoló | Víz: a vízmennyiség után csatornadíj is | 2. lépcső |
| `betaplalas` | `szaldo`, `brutto`, `egyedi` | Napelem: vételezés és betáplálás összevetése | 3. lépcső |
| `zonak` | időablakok | A2: csúcs- és völgyidőszak | 5. lépcső |
| `dinamikus` | árforrás-entitás | D: óránkénti ár egy HA-entitásból | 5. lépcső |

## Példák

### H-tarifa (idényes, nyáron A1 szerint)

```yaml
azonosito: villany/h
nev: "H – hőszivattyús"
kozmu: villany
egyseg: kWh
verziok:
  - ervenyes_tol: 2026-01-01
    forras: "…"
    szabalyok:
      idenyszak:
        - nev: teli
          tol: "10-15"           # hónap-nap, évente ismétlődik
          ig: "04-15"            # kizárólagos
          keret: {tipus: nincs}
        - nev: nyari
          dijszabas: villany/a1  # nyáron az A1 szabályai és díjai
          sajat_keret: true      # a keretet a H-mérőre külön kell számolni
    dijak:
      alap:
        energia_teli: 22.962
        alapdij_ho: 50.165
```

### Gáz (MJ-alapú)

```yaml
azonosito: gaz/lakossagi
nev: "Lakossági földgáz"
kozmu: gaz
egyseg: MJ                       # az elszámolás egysége
mert_egyseg: m3                  # a mérő egysége
verziok:
  - ervenyes_tol: 2026-01-01
    forras: "…"
    szabalyok:
      atvaltas:
        tipus: gaz_mj
        futoertek_alap: 34.0     # MJ/m³; ELLENŐRIZENDŐ, ha nincs havi érték
        korrekcios_tenyezo_alap: 1.0
      keret:
        tipus: eves
        ev_mennyiseg: 63645      # MJ (= 1729 m³); ELLENŐRIZENDŐ
        hatar_felett: piaci
    dijak:
      alap:
        energia_kedvezmenyes: …  # Ft/MJ
        energia_piaci: …         # Ft/MJ
        alapdij_ho: …
```

A **havi elszámolási fűtőérték** változik, és utólag tehető közzé. Ezért nem a díjfájlban él, hanem
fiókonként adható meg havonta: kézzel, vagy egy HA-entitásból. Ha nincs megadva, a `futoertek_alap` érvényes,
és a felület „becsült” jelzést mutat.

### Víz (nincs országos díj)

```yaml
azonosito: viz/egyedi
nev: "Víz- és csatornadíj (egyedi)"
kozmu: viz
egyseg: m3
verziok:
  - ervenyes_tol: 2000-01-01
    forras: "Sablon – a díjakat a helyi vízmű számlájáról kell megadni"
    szabalyok:
      keret: {tipus: nincs}
      csatornadij: {alapertelmezes: be}
    dijak:
      alap:
        viz_m3: null             # kötelező kitölteni
        csatorna_m3: null
        alapdij_ho: null
```

Ha később a legnagyobb vízművek díjai ismertek, saját fájlt kaphatnak (pl. `viz/fovarosi.yaml`).

## Felülírások

A felhasználó a felületen bármely `dijak.*` vagy `szabalyok.*` értéket felülírhatja, dátumtól, fiókra vagy csatornára.
A felülírás nem módosítja a díjfájlt. Ha az integráció új hivatalos díjat hoz, a felület jelzi:
„Hivatalos díj változott, de nálad felülírt érték van érvényben.”

## Ellenőrzés

- JSON-séma minden díjfájlhoz (`dijszabasok/schema.json`).
- Automatikus teszt minden kiadás előtt: a fájlok betölthetők, a verziók időrendben vannak, minden hivatkozott díjszabás létezik, a `forras` ki van töltve.
