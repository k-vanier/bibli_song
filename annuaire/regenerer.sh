#!/bin/bash
# Régénère l'annuaire commun des deux bibliothèques musicales (musics/Annuaire.html).
# dossier musics : RANGER_ROOT, sinon /etc/list_songs.conf (écrit par installer.sh), sinon celui du serveur
MUSICS=; [ -r /etc/list_songs.conf ] && . /etc/list_songs.conf
P=${RANGER_ROOT:-${MUSICS:-/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics}}
P=${P%/}
D=$(dirname "$(readlink -f "$0")")
export PYTHONPATH=/usr/share/beets BEETSDIR="$P/.beets/lowres"
/usr/bin/python3 "$D/annuaire.py" "$P" "Musiques Low-Res:$P/.beets/lowres/library.db" "Musiques Hi-Res:$P/.beets/hires/library.db"
