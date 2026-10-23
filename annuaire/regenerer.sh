#!/bin/bash
# Régénère l'annuaire commun des deux bibliothèques musicales (musics/Annuaire.html).
P=/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics
D=$(dirname "$(readlink -f "$0")")
export PYTHONPATH=/usr/share/beets
/usr/bin/python3 "$D/annuaire.py" "$P" "Musiques Low-Res:$HOME/.config/beets/library.db" "Musiques Hi-Res:$HOME/.config/beets/hires/library.db"
