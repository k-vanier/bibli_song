#!/bin/bash
# Installe list_songs de zéro sur Debian / Ubuntu : paquets, dépôt, dossiers, configurations beets,
# commandes list_songs et annuaire-regenerer, jeton Discogs, partage Samba et HTTPS (facultatifs).
#
# Usage : sudo ./installer.sh [options]
#   --musics CHEMIN        dossier musics (défaut : celui du serveur actuel, voir MUSICS_DEFAUT)
#   --utilisateur NOM      compte qui lance list_songs (défaut : celui qui a fait sudo)
#   --domaine DOMAINE      publie l'annuaire en HTTPS sur ce domaine (annuaire/publier-https.sh)
#   --port-externe PORT    port de la box redirigé vers 8443 (avec --domaine, défaut 8443)
#   --discogs              demande le jeton Discogs (pochettes) et l'enregistre dans ~/discog
#   --samba                partage le dossier musics sur le réseau (pas sur openmediavault : passer par son interface)
#
# Exemple : sudo ./installer.sh --domaine mon-nom.freeboxos.fr --port-externe 8081 --discogs
# Sans le dépôt à côté (script copié seul), il est cloné dans ~<utilisateur>/DEV.
# Relançable sans risque : rien d'existant n'est écrasé (configs, musique, mot de passe, certificat).
# Pour repartir d'une sauvegarde : remettre le dossier musics (il contient .beets/, les bases), puis lancer ce script.
set -euo pipefail

MUSICS_DEFAUT=/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics
DEPOT_URL=https://github.com/k-vanier/DEV.git
MUSICS=$MUSICS_DEFAUT
UTIL=${SUDO_USER:-}
DOMAINE=
PORT_EXT=8443
DISCOGS=0
SAMBA=0

aide() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case $1 in
    --musics) MUSICS=${2%/}; shift ;;
    --utilisateur) UTIL=$2; shift ;;
    --domaine) DOMAINE=$2; shift ;;
    --port-externe) PORT_EXT=$2; shift ;;
    --discogs) DISCOGS=1 ;;
    --samba) SAMBA=1 ;;
    -h|--help) aide ;;
    *) echo "Option inconnue : $1"; aide 1 ;;
  esac
  shift
done

etape() { echo; echo "=== $*"; }
case $MUSICS in /*) ;; *) echo "--musics : chemin absolu attendu"; exit 1 ;; esac
case $MUSICS in *['&|"']*|*"'"*) echo "--musics : pas de & | \" ou ' dans le chemin"; exit 1 ;; esac
[ "$(id -u)" = 0 ] || { echo "À lancer avec sudo."; exit 1; }
[ -n "$UTIL" ] && [ "$UTIL" != root ] || { echo "Préciser le compte qui lancera list_songs : --utilisateur NOM"; exit 1; }
id "$UTIL" >/dev/null 2>&1 || { echo "Compte inconnu : $UTIL"; exit 1; }
MAISON=$(getent passwd "$UTIL" | cut -d: -f6)
GROUPE=$(id -gn "$UTIL")
. /etc/os-release
case "${ID:-} ${ID_LIKE:-}" in *debian*|*ubuntu*) ;; *) echo "Prévu pour Debian / Ubuntu (ici : ${PRETTY_NAME:-inconnu})"; exit 1 ;; esac
OMV=0; [ -d /etc/openmediavault ] && OMV=1
en_tant_que() { runuser -u "$UTIL" -- env HOME="$MAISON" "$@"; }

etape "Paquets ($PRETTY_NAME)"
export DEBIAN_FRONTEND=noninteractive
# sortie d'apt masquée, ses erreurs restent affichées
paquets() { echo "installation : $*"; apt-get install -y -qq -o Dpkg::Use-Pty=0 "$@" >/dev/null; }
apt-get update -qq
paquets git sudo beets python3-pil python3-mediafile python3-unidecode fonts-dejavu-core unar
# 7z pour les archives .7z (et .rar en secours) : paquet « 7zip » récent, sinon « p7zip-full »
paquets 7zip 2>/dev/null || paquets p7zip-full
PYTHONPATH=/usr/share/beets python3 -c 'import beets, mediafile, PIL, unidecode' \
  || { echo "Modules Python manquants (beets, mediafile, PIL, unidecode)"; exit 1; }

etape "Dépôt"
ICI=$(dirname "$(readlink -f "$0")")
if [ -f "$ICI/list_songs.py" ]; then
  LS=$ICI
else
  if [ ! -d "$MAISON/DEV/.git" ]; then
    en_tant_que git clone -q "$DEPOT_URL" "$MAISON/DEV"
  else
    en_tant_que git -C "$MAISON/DEV" pull -q --ff-only || echo "(mise à jour du dépôt impossible, on garde la version présente)"
  fi
  LS=$MAISON/DEV/list_songs
fi
chmod +x "$LS/list_songs" "$LS/list_songs.py" "$LS/annuaire/regenerer.sh" "$LS/annuaire/publier-https.sh" "$LS/installer.sh"
echo "list_songs : $LS"

etape "Dossiers ($MUSICS)"
# seuls les dossiers créés ici changent de propriétaire : la musique déjà présente garde ses droits
for d in "$MUSICS" "$MUSICS/Candidats" "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res" \
         "$MUSICS/.beets" "$MUSICS/.beets/lowres" "$MUSICS/.beets/hires" "$MUSICS/.beets/journal"; do
  [ -d "$d" ] || { install -d -o "$UTIL" -g "$GROUPE" -m 2775 "$d"; echo "créé : $d"; }
done
en_tant_que test -w "$MUSICS/Candidats" -a -w "$MUSICS/.beets" \
  || { echo "$UTIL ne peut pas écrire dans $MUSICS/Candidats ou $MUSICS/.beets : corriger les droits du partage"; exit 1; }

etape "Configurations beets"
for lib in lowres hires; do
  cfg=$MUSICS/.beets/$lib/config.yaml
  if [ -f "$cfg" ]; then
    echo "gardée : $cfg"
  else
    sed "s|$MUSICS_DEFAUT|$MUSICS|g" "$LS/exemples/beets-$lib.yaml" | tr -d '\r' > "$cfg"
    chown "$UTIL:$GROUPE" "$cfg"
    echo "créée : $cfg"
  fi
done
if [ -f "$MAISON/.config/beets/library.db" ]; then
  echo "Ancien dossier $MAISON/.config/beets trouvé : list_songs le déplacera dans $MUSICS/.beets au premier lancement"
fi

etape "Commandes list_songs et annuaire-regenerer"
cat > /usr/local/bin/list_songs <<EOF
#!/bin/sh
# installé par list_songs/installer.sh
export RANGER_ROOT='$MUSICS/'
exec '$LS/list_songs' "\$@"
EOF
cat > /usr/local/bin/annuaire-regenerer <<EOF
#!/bin/sh
# installé par list_songs/installer.sh
export RANGER_ROOT='$MUSICS/'
exec '$LS/annuaire/regenerer.sh' "\$@"
EOF
chmod 755 /usr/local/bin/list_songs /usr/local/bin/annuaire-regenerer
echo "list_songs et annuaire-regenerer utilisables depuis n'importe quel dossier"

if [ $DISCOGS = 1 ]; then
  etape "Jeton Discogs"
  if [ -s "$MAISON/discog" ]; then
    echo "déjà présent : $MAISON/discog"
  else
    echo "Jeton personnel : https://www.discogs.com/settings/developers (« Generate new token »)"
    read -rsp "Jeton (rien ne s'affiche, Entrée pour passer) : " jeton; echo
    if [ -n "$jeton" ]; then
      (umask 077; printf '%s\n' "$jeton" > "$MAISON/discog")
      chown "$UTIL:$GROUPE" "$MAISON/discog"; chmod 600 "$MAISON/discog"
      echo "enregistré : $MAISON/discog"
    fi
  fi
fi

if [ $SAMBA = 1 ]; then
  etape "Partage Samba"
  if [ $OMV = 1 ]; then
    echo "openmediavault : créer le partage dans son interface (Services → SMB/CIFS), sinon il serait écrasé."
  else
    paquets samba
    if grep -q '^\[musics\]' /etc/samba/smb.conf; then
      echo "partage [musics] déjà présent"
    else
      cp /etc/samba/smb.conf "/etc/samba/smb.conf.avant-$(date +%Y%m%d-%H%M%S)"
      cat >> /etc/samba/smb.conf <<EOF

# ajouté par list_songs/installer.sh
[musics]
   path = $MUSICS
   valid users = $UTIL
   read only = no
   force group = $GROUPE
   create mask = 0664
   directory mask = 2775
   veto files = /.beets/
EOF
      testparm -s >/dev/null && systemctl restart smbd
    fi
    pdbedit -L 2>/dev/null | grep -q "^$UTIL:" || { echo "Mot de passe réseau (Samba) pour $UTIL :"; smbpasswd -a "$UTIL"; }
    echo "partage : \\\\$(hostname)\\musics"
  fi
fi

etape "Annuaire"
en_tant_que env RANGER_ROOT="$MUSICS/" "$LS/annuaire/regenerer.sh"

if [ -n "$DOMAINE" ]; then
  etape "HTTPS ($DOMAINE)"
  MUSICS=$MUSICS "$LS/annuaire/publier-https.sh" "$DOMAINE" "$PORT_EXT"
fi

etape "Terminé"
cat <<EOF
Musique à ranger    : $MUSICS/Candidats/
Ranger              : list_songs --simulation, puis list_songs
Annuaire            : $MUSICS/Annuaire.html (régénérer : annuaire-regenerer)
À sauvegarder       : $MUSICS (musique + .beets/)$([ -s "$MAISON/discog" ] && echo " et $MAISON/discog")
EOF
[ -n "$DOMAINE" ] && echo "Annuaire en ligne   : https://$DOMAINE:$PORT_EXT/"
[ $OMV = 1 ] && [ $SAMBA = 0 ] && echo "Partage réseau      : à créer dans openmediavault (Services → SMB/CIFS) s'il n'existe pas"
exit 0
