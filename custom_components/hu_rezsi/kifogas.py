"""Számlakifogás-tervezet az éves kimutatásból és a folyószámla-kivonatból, szabály alapon (nincs benne mesterséges
intelligencia): minden szám a kimutatásból jön, a szöveg a megállapítások típusából épül.

Mielőtt tervezet készül, ellenőriz: van-e minden időszakhoz mérőállás és számla, a nyomtatott folyószámla-egyenlegek
egyeznek-e a kivonattal, és a teljes eltérés levezethető-e a mennyiségekből és az egységárakból. Ha valami nem jön ki,
az állapot „nem_keszitheto”, és a figyelmeztetésekben van az oka – hibás levél helyett."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# Ennyi forintig (és a díj ennyi hányadáig) az eltérés kerekítés, nem kifogás tárgya.
TURES_FT = 100
# A teljes eltérés és a mennyiségekből levezetett eltérés közti legnagyobb megengedett különbség.
MAGYARAZAT_TURES_FT = 500
# Ennyi kWh alatt a kedvezményes keret eltérése számlánkénti kerekítés.
KERET_HIANY_KWH = 2
# Ezeknél a soronkénti forint félrevezető: a kimaradt és a pótolt fogyasztás egymást ellentételezi.
TORTENET_TIPUSOK = ("nem_kiszamlazott", "potolt_fogyasztas", "savkorrekcio")
KIHAGYOTT_TIPUSOK = ("sav_hiany", "nem_levont")

# Jogi hivatkozások – kézzel karbantartva. Ha ez a dátum egy évnél régebbi, a tervezet figyelmeztet, hogy ellenőrizd.
JOG_ELLENORIZVE = "2026-11-06"
JOG_ELAVUL_NAP = 365
# A 4/2011. NFM rendelet 6. §-a ettől a naptól szól a kedvezményes sávhatárról; előtte a 259/2022. Korm. rendelet.
UJ_RENDELET_TOL = "2025-08-01"
NFM = "4/2011. (I. 31.) NFM rendelet"
REGI_RENDELET = {
    "cim": "259/2022. (VII. 21.) Korm. rendelet 2. § (1) bekezdés és 9. § (1) bekezdés (2025. augusztus 1-jéig hatályos)",
    "szoveg": "a 2025. augusztus 1. előtti időszakra: 2523 kWh/év/mérési pont a kedvezményes mennyiség, amely időarányosan, a számlázási időszak napjai szerint vehető igénybe.",
}
MVM_USZ = {
    "cim": "MVM Next egyetemes villamosenergia-szolgáltatói üzletszabályzat, M.1. melléklet, 2.2.5. pont (hatályos 2026. március 1.)",
    "szoveg": "„A kedvezményes mennyiség időarányosan vehető igénybe. Ennek érdekében az MVM Next naparányos elszámolást alkalmaz, amelynek alapján a felhasználó "
              "számára kiállított számlában a kedvezményes mennyiség 1/365, szökőévben 1/366 részének és a számlázási időszak napjainak szorzatát érvényesíti”.",
}
MVM_TAJEKOZTATO = {
    "cim": "Az MVM Next tájékoztatója az áramszámláról (2022)",
    "szoveg": "„az időarányos számítás miatt esetlegesen ki nem használt kedvezményes mennyiség nem vész el, azt a következő elszámolás során vesszük figyelembe.”",
}
MVM_VISSZATERITES = "A számláikon közölt garantált szolgáltatás szerint a túlfizetés a kifogás jogosságának megállapításától számított 8 napon belül visszajár."
MVM_VALASZ = "Válaszukat a számláikon közölt 15 napos határidőn belül, írásban kérem."


def _ft(x: float | int) -> str:
    return f"{abs(int(round(x))):,}".replace(",", " ") + " Ft"


def _kwh(x: float | int) -> str:
    return f"{abs(int(round(x))):,}".replace(",", " ") + " kWh"


def _nap(iso: str) -> str:
    return f"{iso[:4]}. {iso[5:7]}. {iso[8:10]}."


def _d(iso: str) -> date:
    return date.fromisoformat(iso[:10])


def magyarazott_elteres(k: dict[str, Any]) -> float:
    """A számlák és a számítás különbsége (MVM – saját, bruttó Ft) a mennyiségekből és az egységárakból levezetve."""
    o, a1, h = k["osszesen"], k["dijak"]["a1"], k["dijak"].get("h") or {}
    afa = 1 + a1.get("afa", 27) / 100
    d_kedv, d_piaci = o["mvm_kedvezmenyes"] - o["kedvezmenyes"], o["mvm_piaci"] - o["piaci"]
    netto = (d_kedv * a1["energia_kedvezmenyes"] + d_piaci * a1["energia_piaci"] + (d_kedv + d_piaci) * a1["rendszerhasznalati"])
    if h and (d_teli := o["mvm_teli"] - o["teli"]):
        netto += d_teli * (h["energia_teli"] + h["rendszerhasznalati"])
    return netto * afa + (o["mvm_alapdij_ho"] - o["alapdij_ho"]) * a1["alapdij_ho"] * afa


def _ablak_szamlak(k: dict[str, Any], fsz: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Az elszámolási évhez tartozó összes számla (sztornóval, részszámlával, a közös folyószámla többi fiókjáéval)."""
    tol, ig = _d(k["ev_tol"]), _d(k["ev_ig"])
    out = []
    for x in ((fsz or {}).get("teljesites") or {}).get("sorok") or []:
        i = x.get("idoszak")
        if not i or _d(i[1]) <= tol or _d(i[0]) > ig:
            continue
        out.append({
            "kelte": x.get("kelte"), "sorszam": x.get("sorszam"), "tipus": x.get("tipus"), "fiok": x.get("fiok"), "idoszak": i,
            "szamlaertek": x.get("szamlaertek"), "fizetendo": x.get("fizetendo"), "allapot": x.get("allapot_nev"),
            "fizetve": (x.get("fizetve") or {}).get("datum"),
        })
    return sorted(out, key=lambda y: (y["kelte"] or "", y["sorszam"] or ""))


def _folyoszamla(fsz: dict[str, Any] | None, jegyzek: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A kivonat az év első számlájától: tételek futó egyenleggel, a nyomtatott egyenleggel és az összesítéssel."""
    if not fsz or not jegyzek:
        return None
    kezdet = jegyzek[0]["kelte"]
    tetelek = fsz.get("tetelek") or []
    elotte = [t for t in tetelek if t["datum"] < kezdet]
    nyito = elotte[-1]["egyenleg"] if elotte else (fsz.get("nyito") or {}).get("osszeg", 0)
    sorok = [{a: t.get(a) for a in ("datum", "fajta", "sorszam", "fiok", "megnevezes", "kovetel", "tartozik", "egyenleg", "szolgaltato_egyenleg", "elteres")}
             for t in tetelek if t["datum"] >= kezdet]
    befizetes = sum(t["tartozik"] for t in sorok if t["fajta"] == "befizetes")
    kovetel = sum(t["kovetel"] for t in sorok)
    tartozik = sum(t["tartozik"] for t in sorok if t["fajta"] != "befizetes")
    return {"kozos": bool(fsz.get("kozos")), "nev": fsz.get("nev"), "nyito": nyito, "sorok": sorok, "zaro": fsz.get("zaro"),
            "terheles": kovetel, "jovairas": tartozik, "befizetes": befizetes}


def _ellenorzes(k: dict[str, Any], folyo: dict[str, Any] | None) -> list[dict[str, Any]]:
    ki: list[dict[str, Any]] = []

    def jelez(szoveg: str, blokkolo: bool = False) -> None:
        ki.append({"szoveg": szoveg, "blokkolo": blokkolo})

    sorok = [s for s in k["sorok"] if s.get("mvm")]
    if not sorok:
        jelez("Az évben nincs olyan elszámoló számla, amelyen tételes adat van, így nincs mit összevetni.", True)
        return ki
    if k.get("hianyos"):
        jelez("Néhány időszakhoz nincs mérőállás, ezek kimaradtak az összevetésből.", True)
    for a, b in zip(sorok, sorok[1:]):
        if _d(b["tol"]) != _d(a["ig"]) + timedelta(days=1):
            jelez(f"Hiányzó időszak a számlák között: {_nap(a['ig'])} és {_nap(b['tol'])} között. Valószínűleg hiányzik egy számla.", True)
    for s in sorok:
        if s["mert"] < 0:
            jelez(f"A {s['sorszam']} sz. számla időszakában a mérőállások szerinti fogyasztás negatív. Ellenőrizd a mérőállásokat és a mérőcserét.", True)
        if s.get("csonka"):
            jelez(f"A {s['sorszam']} sz. számla {_nap(s['szamla_tol'])} napjától szól, de a mérőállások csak {_nap(s['tol'])} napjától vannak meg, így a számla nem vethető össze. "
                  "Rögzítsd a számla induló állását.", True)
    if k.get("merocsere"):
        jelez("Mérőcsere volt: a táblázatokban az új mérő állásai a régi záróállásától folytatva szerepelnek. A levélben ezeket a valódi állásokra érdemes javítani.")
    for s in sorok:
        if not s.get("valodi"):
            jelez(f"A {s['sorszam']} sz. számla időszakának valamelyik végére nincs valódi mérőállás, arányos becslésből számolok.")
    o = k["osszesen"]
    teljes = o["mvm"] - o["helyes"]
    magyarazott = magyarazott_elteres(k)
    if abs(teljes - magyarazott) > max(MAGYARAZAT_TURES_FT, abs(o["helyes"]) * 0.01):
        jelez(f"A teljes eltérés ({_ft(teljes)}) nem vezethető le a mennyiségekből és az egységárakból ({_ft(magyarazott)}). "
              "Lehet, hogy év közben változott az ár, vagy egy számla tételei nem olvashatók. Nézd át a számlákat.", True)
    if folyo:
        for t in folyo["sorok"]:
            if t.get("elteres"):
                jelez(f"A {t['sorszam']} sz. számlára nyomtatott folyószámla-egyenleg {_ft(t['szolgaltato_egyenleg'])}, a kivonat szerinti ettől "
                      f"{_ft(t['elteres'])}-tal tér el. Valószínűleg hiányzik egy számla vagy befizetés.", True)
    else:
        jelez("A folyószámla-kivonat nem készíthető el, a tervezetből a folyószámla-egyeztetés kimarad.")
    if any(e.get("mvm_kedvezmenyes") is None for e in k.get("kedv_evek") or []):
        jelez("Néhány számlán nincs tételes kedvezményes adat, ezért a kedvezményes évek szerinti bontás hiányos.")
    if not (k.get("ugyfel") or {}).get("azonosito"):
        jelez("A felhasználó azonosítója nincs a számlákon, a levélben kézzel kell kitölteni.")
    return ki


def _jogi_sor(k: dict[str, Any]) -> dict[str, Any] | None:
    """A választott jogszabály szerinti időszak sora a kimutatásból (ha van)."""
    return next((j for j in k.get("jogi_idoszakok") or [] if j["tol"] == k.get("valasztott")), None)


def _keret_hiany(j: dict[str, Any] | None) -> bool:
    """Kedvezményes évre kimutatható keret-hiány: ekkor a levél és a követelés a jogszabály szerinti évhez igazodik."""
    return bool(j) and j["fajta"] == "ev" and j.get("hiany") is not None and j["hiany"] >= KERET_HIANY_KWH


def _masik_ev_hianya(k: dict[str, Any], j: dict[str, Any] | None) -> str | None:
    """A választott kedvezményes évben nincs hiány, de az összevetett számlák egy másik évben igen: annak a neve."""
    if not j or j["fajta"] != "ev" or j.get("hiany") is None or j["hiany"] >= KERET_HIANY_KWH:
        return None
    return next((e["ev"] for e in k.get("kedv_evek") or [] if e["ev"] != j["nev"] and ((e.get("teljes") or e).get("hiany") or 0) >= KERET_HIANY_KWH), None)


def _hiany_mondat(j: dict[str, Any]) -> str:
    return (f"A {j['nev']}. kedvezményes évben ({_nap(j['tol'])} – {_nap(j['ig'])}) {_kwh(j['keret_szamlazva'])} keret járt, a számlákon "
            f"{_kwh(j['szamla_kedvezmenyes'])} szerepel kedvezményes áron: {_kwh(j['hiany'])} hiányzik, kb. {_ft(j['hiany_ft'])} többlet.")


def _okok(k: dict[str, Any], jogi: dict[str, Any] | None = None) -> list[str]:
    meg = k["megallapitasok"]
    van_potlas = any(m["tipus"] == "potolt_fogyasztas" for m in meg)
    out = []
    for m in meg:
        if m["tipus"] in KIHAGYOTT_TIPUSOK:
            continue
        mondat = f"A {m['sorszam']} sz. számla ({_nap(m['tol'])} – {_nap(m['ig'])}): {m['szoveg']}"
        if m.get("hatas_ft") is not None and not (van_potlas and m["tipus"] in TORTENET_TIPUSOK):
            mondat += f" (hatása {_ft(m['hatas_ft'])})"
        out.append(mondat + ".")
    if jogi:
        out.append(_hiany_mondat(jogi))
    else:
        out += [m["szoveg"][0].upper() + m["szoveg"][1:] + "." for m in meg if m["tipus"] == "sav_hiany"]
    return out


def _jogalap(k: dict[str, Any], tol: str, sav_hiany: bool, mvm: bool) -> list[dict[str, str]]:
    """A levél jogi hivatkozásai: csak ami az adott tarifára és megállapításra vonatkozik."""
    h = k.get("dijszabas") == "villany/h"
    ki = [{"cim": f"{NFM} 6. § (1) bekezdés",
           "szoveg": "a kedvezményes lakossági sávhatár az „A1”, „A2”, „B Alap” és „H” árszabás esetén árszabásonként 2523 kWh"
                     + ("; „H” árszabásnál a fűtési idényen kívüli időszakban érvényesíthető." if h else ", ezért a H-tarifa fogyasztása az A1 keretét nem érinti.")}]
    if not h:
        ki.append({"cim": "6. § (3) bekezdés", "szoveg": "a kedvezményes mennyiség augusztus 1. és július 31. közötti időszakra vonatkozik."})
    ki.append({"cim": "6. § (4) bekezdés", "szoveg": "a mennyiség időarányosan vehető igénybe, naparányos elszámolással: 1/365 (szökőévben 1/366) rész szorozva a számlázási időszak napjaival, az e feletti rész számlázható lakossági piaci áron."})
    if tol < UJ_RENDELET_TOL:
        ki.append(REGI_RENDELET)
    if mvm:
        ki.append(MVM_USZ)
        if sav_hiany:
            ki.append(MVM_TAJEKOZTATO)
    return ki


def _erveles(k: dict[str, Any], sorok: list[dict[str, Any]]) -> list[str]:
    """Az utólag pótolt fogyasztás érvelése: csak ha egy korábbi számlán kimaradt fogyasztást egy későbbi pótol, és a
    kedvezményes keretből hiány is van – különben nincs mire alapozni."""
    meg = k["megallapitasok"]
    if not any(m["tipus"] == "sav_hiany" for m in meg):
        return []
    potlo = next((s for s in sorok if s["mvm"]["kiszamlazott"] is not None and s["mvm"]["kiszamlazott"] - s["mert"] >= 1), None)
    ered = next((s for s in sorok if s["mvm"]["kiszamlazott"] is not None and s["mert"] - s["mvm"]["kiszamlazott"] >= 1), None)
    if not potlo or not ered or potlo["tol"] <= ered["tol"]:
        return []
    kimaradt = ered["mert"] - ered["mvm"]["kiszamlazott"]
    # A mérősor szerinti időszak: ha a számla valamelyik tétele épp a kimaradt mennyiség, annak az időszaka, különben az egész számláé.
    resz = next((r for r in ered.get("reszek") or [] if abs(r["mert"] - kimaradt) < 1), None) or {"tol": ered["tol"], "ig": ered["ig"], "keret": ered["keret"]}
    nap = (_d(resz["ig"]) - _d(resz["tol"])).days + 1
    pnap = (_d(potlo["ig"]) - _d(potlo["tol"])).days + 1

    def ev(iso: str) -> str | None:
        return next((e["ev"] for e in k.get("kedv_evek") or [] if e["tol"] <= iso <= e["ig"]), None)

    ki = [f"A pótolt {_kwh(kimaradt)} saját számlájuk ({ered['sorszam']}) mérősora szerint a {_nap(resz['tol'])} – {_nap(resz['ig'])} közötti, {nap} napos időszakban fogyott. "
          f"Erre az időszakra önmagában {_kwh(resz['keret'])} keret jár ({k.get('keret_ev', 2523):.0f} ÷ 365 × {nap}).",
          f"A {potlo['sorszam']} sz. számla ezt a fogyasztást a {_nap(potlo['tol'])} – {_nap(potlo['ig'])} közötti, {pnap} napos időszakkal számlázta, ezért csak ennek {_kwh(potlo['mvm']['kedvezmenyes'])}-s kerete jutott rá."]
    e1, e2 = ev(resz["ig"]), ev(potlo["ig"])
    if e1 and e2 and e1 != e2:
        ki.append(f"Ezzel a fogyasztás a {e1}. kedvezményes évből a {e2}. évbe került, holott a 6. § (3) bekezdése szerint a keret kedvezményes évhez kötött.")
    ki.append("Álláspontom szerint a 6. § (4) bekezdése szerinti naparányos keret a fogyasztás valós időszakához tartozik: nem veszhet el azzal, hogy a számla a fogyasztást utólag, egy másik időszak tételeként számlázza.")
    return ki


def _lenyeg_jogi(j: dict[str, Any]) -> str:
    """A kifogás lényege a jogszabály szerinti kedvezményes évre (a számlák egészben a mellékletben)."""
    # A keret és a fogyasztás ugyanarra a napra szóljon: folyamatban lévő évben is csak a számlázott napig.
    m_sz = j["mert"] if j.get("mert_szamlazva") is None else j["mert_szamlazva"]
    r = [f"A {j['nev']}. kedvezményes évben ({_nap(j['tol'])} – {_nap(j['ig'])}, {j['nap']} nap) a fogyasztás a mérőállások szerint {_kwh(m_sz)}, a járó keret {_kwh(j['keret_szamlazva'])}."
         f" Kedvezményes áron a számlákon a tételek dátuma szerint {_kwh(j['szamla_kedvezmenyes'])} szerepel, {_kwh(j['hiany'])} hiányzik."]
    r.append(f"Ennek bruttó értéke az egységárakból {_ft(j['hiany_ft'])} a javamra.")
    return " ".join(r)


def _lenyeg(k: dict[str, Any], tol: str, ig: str, teljes: int, kovetel: int) -> str:
    o = k["osszesen"]
    r = [f"A {_nap(tol)} – {_nap(ig)} közötti számlázott időszakban a fogyasztás a mérőállások szerint {_kwh(o['mert'])}"]
    if abs(o["mert"] - o["kiszamlazott"]) < 1:
        r[0] += ", és a számlák is ennyit számláztak ki."
    else:
        r[0] += f", a számlák {_kwh(o['kiszamlazott'])}-t számláztak ki."
    if abs(o["kedvezmenyes"] - o["mvm_kedvezmenyes"]) >= 1:
        r.append(f"Kedvezményes áron a számlákon {_kwh(o['mvm_kedvezmenyes'])} szerepel, a mérés és a díjszabás szerint {_kwh(o['kedvezmenyes'])} járna.")
    r.append(f"A számlák díja összesen {_ft(o['mvm'])}, a számításom szerint {_ft(o['helyes'])}"
             + (f" (a számlánkénti kerekítésekkel a különbség {_ft(teljes)})" if abs(teljes - kovetel) >= 1 else "")
             + f": a mennyiségekből és az egységárakból számolt különbözet {_ft(kovetel)} " + ("a javamra." if kovetel > 0 else "a szolgáltató javára."))
    return " ".join(r)


def tervezet(k: dict[str, Any], fsz: dict[str, Any] | None, ma: date | None = None) -> dict[str, Any]:
    """A tervezet adatai a panelnek: k – kimutatas (eves_kimutatas eredménye), fsz – a folyószámla-kivonat (egyutt=True)."""
    ma = ma or date.today()
    o = k["osszesen"]
    jogi = _jogi_sor(k)
    hiany = _keret_hiany(jogi)
    jegyzek = _ablak_szamlak(k, fsz)
    folyo = _folyoszamla(fsz, jegyzek)
    figy = _ellenorzes(k, folyo)
    sorok = [s for s in k["sorok"] if s.get("mvm")]
    teljes = int(round(o["mvm"] - o["helyes"])) if sorok else 0
    # A követelés a mennyiségekből és az egységárakból számolt különbözet (ezt lehet helyesbíteni); a számlasorok összege
    # ettől csak kerekítésben térhet el, különben az ellenőrzés már leállította a tervezetet.
    kovetel = int(round(magyarazott_elteres(k))) if sorok else 0
    if hiany:  # a jogszabály szerinti év hiánya a követelés; a számlák egészben a mellékletben, a kerekítések nem tárgyai
        kovetel = int(jogi["hiany_ft"])
    ki: dict[str, Any] = {
        "allapot": "nem_keszitheto" if any(f["blokkolo"] for f in figy) else "kesz",
        "figyelmeztetesek": figy, "fiok": k.get("fiok"), "ugyfel": k.get("ugyfel") or {}, "mero": k.get("mero"), "szolgaltato": k.get("szolgaltato"),
        "dijszabas": k.get("dijszabas"), "ev_tol": k["ev_tol"], "ev_ig": k["ev_ig"], "dijak": k.get("dijak"), "keret_ev": k.get("keret_ev"),
        "osszeg": {"ft": abs(kovetel), "irany": "javamra" if kovetel > 0 else "szolgaltato", "szamlasorok_ft": abs(teljes)},
        "sorok": sorok, "osszesen": o, "kedv_evek": k.get("kedv_evek") or [], "allasok": k.get("allasok") or {}, "allasok_becsult": k.get("allasok_becsult") or [], "fuggo": k.get("fuggo"),
        "szamlajegyzek": jegyzek, "folyoszamla": folyo, "idoszak": jogi, "keret_hiany": hiany,
    }
    if ki["allapot"] != "kesz":
        return ki
    meg = k["megallapitasok"]
    mvm = "MVM" in (k.get("szolgaltato") or "").upper()
    celok = [m for m in meg if m["tipus"] not in KIHAGYOTT_TIPUSOK]
    if abs(teljes) < TURES_FT and not celok:
        ki["allapot"] = "nincs_elteres"
        return ki
    if masik := _masik_ev_hianya(k, jogi):  # a hiány nem ebben az évben van: a levél ott készül, különben rossz évről szólna
        ki["allapot"] = "nincs_elteres"
        ki["masik_ev"] = masik
        return ki
    # Ha a számla kimaradt fogyasztást pótol, a kifogás a pótló számlára szól (a korábbi számla önmagában már rendeződött).
    potlo = [m["sorszam"] for m in meg if m["tipus"] == "potolt_fogyasztas"]
    szamok = potlo or [m["sorszam"] for m in celok]
    nem_levont = [m for m in meg if m["tipus"] == "nem_levont"]
    kerelmek = [f"Vizsgálják felül és helyesbítsék a {', '.join(szamok)} sz. számlá{'kat' if len(szamok) > 1 else 't'} a mérőállások és a díjszabás szerint "
                "(ha az Önök számítása eltér, annak levezetésével)."]
    if kovetel > 0:
        kerelmek.append(f"Az általam {_ft(kovetel)}-ra számolt különbözetet írják jóvá a folyószámlán, számolják el az esetleges tartozással szemben, és a fennmaradó részt térítsék vissza."
                        + (f" {MVM_VISSZATERITES}" if mvm else ""))
    else:
        kerelmek.append(f"Tájékoztassanak a helyesbítés nyomán keletkező különbözet (általam számolva {_ft(kovetel)}) rendezésének módjáról.")
    kerelmek += [f"Vonják le a {m['sorszam']} sz. részszámlát a következő elszámolóban." for m in nem_levont]
    if folyo and folyo["kozos"]:
        kerelmek.append("Küldjenek tételes kivonatot a közös folyószámláról " + ("a kedvezményes évre és az azt követő számlákra." if hiany else "az elszámolási évre."))
    kerelmek.append("Ha a számításomat nem fogadják el, kérem tételes, írásbeli indoklásukat időszakonként.")
    nem_vitatott = []
    if abs(o["mert"] - o["kiszamlazott"]) < 1:
        nem_vitatott.append("a fogyasztás mennyiségét")
    if o["alapdij_ho"] == o["mvm_alapdij_ho"]:
        nem_vitatott.append("az alapdíjat")
    if any(0 < abs(s["elteres"]) < max(TURES_FT, s["helyes"] * 0.005) for s in sorok):
        nem_vitatott.append("a számlánkénti kisebb kerekítési eltéréseket")
    tol, ig = (jogi["tol"], jogi["ig"]) if hiany else (sorok[0]["tol"], sorok[-1]["ig"])
    if (ma - _d(JOG_ELLENORIZVE)).days > JOG_ELAVUL_NAP:
        figy.append({"szoveg": f"A jogszabályi hivatkozásokat legutóbb {_nap(JOG_ELLENORIZVE)} ellenőriztük, azóta változhattak. Küldés előtt nézd meg a hatályos szöveget.", "blokkolo": False})
    if tol < UJ_RENDELET_TOL:
        figy.append({"szoveg": f"Az időszak egy része 2025. augusztus 1. elé esik, amikor még a 259/2022. Korm. rendelet volt hatályos. A levél mindkettőre hivatkozik, de ezt a részt nézd át külön.", "blokkolo": False})
    ki.update({
        "jogalap": _jogalap(k, tol, any(m["tipus"] == "sav_hiany" for m in meg), mvm), "jog_ellenorizve": JOG_ELLENORIZVE, "erveles": _erveles(k, sorok),
        "valasz": MVM_VALASZ if mvm else "Válaszukat írásban kérem.",
        "targy_szamlak": szamok, "tol": tol, "ig": ig, "lenyeg": _lenyeg_jogi(jogi) if hiany else _lenyeg(k, tol, ig, teljes, kovetel), "okok": _okok(k, jogi if hiany else None), "kerelmek": kerelmek, "nem_vitatott": nem_vitatott,
        "fuggo_szoveg": f"A {_nap(k['fuggo']['tol'])} – {_nap(k['fuggo']['ig'])} közötti időszakról még nincs számlám, ez a kifogásnak nem része." if k.get("fuggo") else None,
    })
    return ki
