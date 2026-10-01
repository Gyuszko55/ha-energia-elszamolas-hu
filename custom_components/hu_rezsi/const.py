"""Rezsikövető – állandók."""

DOMAIN = "hu_rezsi"
PLATFORMS = ["sensor"]
FIOK = "fiok"  # alárendelt bejegyzés (config subentry) típusa

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

EGYSEG = {"villany": "kWh", "gaz": "m³", "viz": "m³"}  # a mért (óra) egység
DIJNET_MINTA = ".dijnet_paid_invoices_*.yaml"
PENZNEM = "HUF"
FRISSITES_PERC = 10
# A lezárás a következő időszak első napján csak ennyi óra után fut, hogy az előző nap
# utolsó órájának statisztikája már elkészüljön.
LEZARAS_KESLELTETES_ORA = 1
