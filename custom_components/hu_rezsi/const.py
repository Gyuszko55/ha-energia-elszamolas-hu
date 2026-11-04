"""Rezsikövető – állandók."""

DOMAIN = "hu_rezsi"
PLATFORMS = ["sensor"]
FIOK = "fiok"  # alárendelt bejegyzés (config subentry) típusa
SZIGET = "sziget"  # szigetüzemi energiarendszer (kísérleti) – külön alárendelt típus, nem fiók
POSTAFIOK = "postafiok"  # e-mail fiók (IMAP) a számlák beolvasásához – külön alárendelt típus, nem fiók

# E-mail fiók (postafiók subentry) mezői. A jelszó a bejegyzés adataiban van (mint más integrációknál), de a
# diagnosztikából és a Rezsikövető-mentésből kimarad – visszaállítás után újra meg kell adni.
CONF_EMAIL_CIM = "email_cim"  # e-mail cím / felhasználónév
CONF_JELSZO = "jelszo"  # alkalmazásjelszó (Gmail)
CONF_IMAP_SZERVER = "imap_szerver"
CONF_IMAP_PORT = "imap_port"
CONF_IMAP_SSL = "imap_ssl"
CONF_EMAIL_NAPOK = "email_napok"  # visszatekintés (nap)
CONF_EMAIL_KUKA = "email_kuka"  # a Kukát is átnézi (a leveleket olvasás után gyakran törlik)
# Fiók: e-mailes számlák
CONF_EMAIL_POSTAFIOKOK = "email_postafiokok"  # a háztartás mely e-mail fiókjaiban keressen (postafiók-azonosítók)
CONF_EMAIL_FELADOK = "email_feladok"  # feladó címek / domainek (vesszővel)
CONF_EMAIL_TARGY = "email_targy"  # opcionális: a tárgyban szereplő szó
CONF_EMAIL_MERO = "email_mero"  # opcionális: a mérő gyári száma (ha egy szolgáltató levelei több fiókot fednek le)
CONF_EMAIL_IRSZ = "email_irsz"  # opcionális: a felhasználási hely irányítószáma (ugyanerre)
CONF_EMAIL_AUTO = "email_auto"  # tartalom szerinti besorolás: a melléklet beolvasása dönt (mérő, szolgáltató), nem a feladó
EMAIL_ATNEZES_ORA = 1  # óránként
EMAIL_INDULAS_MP = 120  # a HA elindulása után ennyivel (a háttérben)

# A panel integráció szintű (otthontól független) beállításai – hu_rezsi/panel_beallitas.
PANEL_AUTO_BEZARAS = "auto_bezaras_mp"  # a csak megjelenítő ablakok bezárása ennyi mp tétlenség után (0: soha)
PANEL_AUTO_BEZARAS_ALAP = 10

# Fiók (subentry) mezői
CONF_KOZMU = "kozmu"
CONF_SZOLGALTATO = "szolgaltato"
CONF_DIJSZABAS = "dijszabas"
CONF_DIJSZABAS_TOL = "dijszabas_tol"
CONF_IDOSZAK_MOD = "idoszak_mod"
CONF_IDOSZAK_NAP = "idoszak_nap"
CONF_FORRAS = "forras_entitas"
CONF_SZORZO = "forras_szorzo"
CONF_FORRAS_TIPUS = "forras_tipus"  # meroallas | szamlalo
CONF_FORRAS_TOL = "forras_tol"  # a szenzor adatai ettől érvényesek
CONF_LEGTERFOGAT = "legterfogat"  # távhő: a lakás légtérfogata (lm³) – a fűtési és a melegvíz-alapdíj szorzója
CONF_FUTES_GJ_HO = "futes_gj_ho"  # távhő: a havi hődíj-átalány (GJ/hó, a fűtési idényben) – a számláról
CONF_GAZMERO_TELJESITMENY = "gazmero_teljesitmeny"  # gáz B1: a mérő névleges teljesítménye (m³/h) – az alapdíj szorzója
CONF_LAKASSZAM = "lakasszam"  # gáz fogyasztói közösség (A3): lakások száma
CONF_KOZOSSEG_TIPUS = "kozosseg_tipus"  # tarsashaz: (lakásszám + 1) × keret | csaladi: lakásszám × keret
CONF_PROFIL_FORRAS = "profil_forras"  # ritka leolvasásnál a havi elosztás alakja (pl. kazán becsült gáza)
CONF_FORRAS_KORREKCIO = "forras_korrekcio"  # automatikus mérő-korrekció a leolvasásokból (alapból be)
CONF_KERET_AKTIV = "keret_aktiv"
CONF_GYARI_SZAM = "gyari_szam"
CONF_BEEPITVE = "beepitve"
CONF_KEZDO_ALLAS = "kezdo_allas"
CONF_FIZETESI_MOD = "fizetesi_mod"  # fogyasztas_szerint | reszszamla
CONF_RESZSZAMLA_DB = "reszszamla_db_ev"
CONF_DIJNET = "dijnet_szolgaltato"  # a Díjnet-integráció számláinak „provider” mezője
CONF_CSATORNADIJ = "csatornadij_aktiv"
CONF_NAPELEM = "napelem_mod"  # nincs | brutto | szaldo
CONF_BETAPLALAS = "betaplalas_entitas"
CONF_ALMERO = "almero"  # víz: locsolási almérő a főmérő mögött
CONF_ALMERO_KEZDO = "almero_kezdo_allas"
CONF_ALMERO_BEEPITVE = "almero_beepitve"
CONF_ALMERO_FORRAS = "almero_forras"
CONF_RESZSZAMLA_OSSZEG = "reszszamla_osszeg"
CONF_ELOZO_EV = "elozo_ev_mennyiseg"
CONF_HASZNALAT = "hasznalat"  # „allando” (alapértelmezés) | „nyaralo”: idényes használat – az előrejelzés havi profilja
CONF_ATALANY_MENNYISEG = "atalany_mennyiseg"
CONF_SZAMLAZAS_HONAP = "szamlazas_honap"  # számlázási ütem: 1 havi, 2 kéthavi, 3 negyedéves, 4 négyhavi (pl. ALFÖLDVÍZ)
CONF_DIKT_ABLAK = "diktalasi_ablak"  # a diktálási ablak napjai (pl. "8-14"), amíg nincs számla, amely közli
CONF_KOV_EVES = "kovetkezo_eves_leolvasas"  # a szolgáltató következő éves leolvasása (tört év: beköltözés, új szolgáltatás)
CONF_UTALAS_NAP = "utalas_nap"  # állandó (ütemezett) átutalás a hónap e napján; munkaszüneti napon az utána következő első munkanapon
CONF_SZUNETEL_TOL = "szunetel_tol"  # szüneteltetett számlázás kezdete (pl. lakatlan ingatlan) – erre az időre semmi nem jár
CONF_SZUNETEL_IG = "szunetel_ig"  # a szüneteltetés utolsó napja (üresen: tart)
CONF_ELSZAMOLAS_HONAP = "elszamolas_honap"  # elszámolási ciklus: 6 félév, 12 év  # havi átalány mennyiségben (pl. 293 kWh/hó)
CONF_SZAMLA_MAPPA = "szamla_mappa"  # a config mappához képest, pl. "Dijnet /mvm_next_foldgaz"
CONF_H_TELI = "h_teli_forras"  # H-tarifa téli regiszter (1.81) szenzora
CONF_H_NYARI = "h_nyari_forras"  # H-tarifa nyári regiszter (1.82) szenzora
CONF_A2_CSUCS = "a2_csucs_forras"  # A2 csúcsidőszaki regiszter (1.8.1) szenzora
CONF_A2_VOLGY = "a2_volgy_forras"  # A2 völgyidőszaki regiszter (1.8.2) szenzora
CONF_ELSZAMOLAS_MOD = "elszamolas_mod"  # villany: diktalas | atalany | tavleolvasas
CONF_SZAMLA_MEROK = "szamla_merok"  # vesszővel elválasztott gyári számok; üres: a mappa minden számlája

EGYSEG = {"villany": "kWh", "gaz": "m³", "viz": "m³", "hulladek": "db", "tavho": "m³", "kozos": "db", "tavkozles": "db"}  # a mért (óra) egység
FIX_DIJAS = {"hulladek", "kozos", "tavkozles"}  # mérő nélküli közművek: csak alapdíj és számlák
FIX_DIJSZABASOK = {"gaz/mero_nelkuli"}  # mérő nélküli díjszabás mérős közműnél (gáz átalány: csak gáztűzhely)
CONF_SZOBASZAM = "szobaszam"  # gáz mérő nélkül: szobaszám (1–4, félszobával)
CONF_TUZHELY = "tuzhely"  # gáz mérő nélkül: a gáztűzhely fajtája
DIJNET_MINTA = ".dijnet_paid_invoices_*.yaml"
PENZNEM = "HUF"
FRISSITES_PERC = 10
# A lezárás a következő időszak első napján csak ennyi óra után fut, hogy az előző nap
# utolsó órájának statisztikája már elkészüljön.
LEZARAS_KESLELTETES_ORA = 1

# Otthon-beállítás (a háztartás bejegyzésének beállításai – options): fűtés és hőmérséklet az indítókártyához.
CONF_FUTES = "futes"
CONF_BELSO_HOMERSEKLET = "belso_homerseklet"
CONF_KULSO_HOMERSEKLET = "kulso_homerseklet"
OTTHON_BEALLITASOK = (CONF_FUTES, CONF_BELSO_HOMERSEKLET, CONF_KULSO_HOMERSEKLET)
