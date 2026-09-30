#!/bin/sh
# Havi villany-elszámolás CSV-másolata (packages/energia_elszamolas/hu_energia_elszamolas.yaml, shell_command.villany_havi_csv).
# A rezsisáv mérőóránként külön: A1 (a_*) és H nyári (h_nyari_*).
F=/config/energia_elszamolas/havi.csv
[ -f "$F" ] || echo "rogzitve;honap;napok;a_kwh;h_teli_kwh;h_nyari_kwh;a_sav_kwh;a_rezsi_kwh;a_piaci_kwh;a_ft;h_sav_kwh;h_nyari_rezsi_kwh;h_nyari_piaci_kwh;h_nyari_ft;h_teli_ft;alapdij_ft;osszesen_ft" > "$F"
echo "$(date '+%Y-%m-%d %H:%M');$1;$2;$3;$4;$5;$6;$7;$8;$9;${10};${11};${12};${13};${14};${15};${16}" >> "$F"
