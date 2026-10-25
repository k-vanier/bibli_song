#!/bin/bash
# Régénère l'annuaire commun des deux bibliothèques musicales (musics/Annuaire.html).
# dossier musics : RANGER_ROOT, sinon /etc/bibli_song.conf (écrit par installer.sh ; /etc/list_songs.conf avant
# le changement de nom du projet), sinon celui du serveur
MUSICS=; for c in /etc/bibli_song.conf /etc/list_songs.conf; do [ -r "$c" ] && { . "$c"; break; }; done
P=${RANGER_ROOT:-${MUSICS:-/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics}}
P=${P%/}
D=$(dirname "$(readlink -f "$0")")
export PYTHONPATH=/usr/share/beets BEETSDIR="$P/.beets/lowres"
/usr/bin/python3 "$D/annuaire.py" "$P" "Musiques Low-Res:$P/.beets/lowres/library.db" "Musiques Hi-Res:$P/.beets/hires/library.db"
