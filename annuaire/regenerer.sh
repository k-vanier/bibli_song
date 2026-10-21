#!/bin/bash
# Régénère les annuaires des deux bibliothèques musicales.
P=/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage
D=$(dirname "$(readlink -f "$0")")
export PYTHONPATH=/usr/share/beets
/usr/bin/python3 "$D/annuaire.py" "$P/Musiques Low-Res" ~/.config/beets/library.db "Musiques Low-Res"
/usr/bin/python3 "$D/annuaire.py" "$P/Musiques Hi-Res" ~/.config/beets/hires/library.db "Musiques Hi-Res"
