#!/bin/sh
# Mérőleolvasási napló CSV-másolata (packages/energia_elszamolas/hu_energia_leolvasas.yaml, shell_command.meroora_naplo_csv).
# Argumentumok: datum mero tipus allas uj_kezdo korrekcio ha_elotte lezart_fogyasztas
F=/config/energia_elszamolas/naplo.csv
[ -f "$F" ] || echo "rogzitve;datum;mero;tipus;allas;uj_kezdo;korrekcio;ha_elotte;lezart_fogyasztas" > "$F"
echo "$(date '+%Y-%m-%d %H:%M');$1;$2;$3;$4;$5;$6;$7;$8" >> "$F"
