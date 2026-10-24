#!/bin/bash
# Installe list_songs de zéro sur Debian / Ubuntu, en posant les questions au début :
# où créer le dossier musics, quel compte, base beets, jeton Discogs, partage Samba, HTTPS.
# À la fin, tout est prêt : il suffit de déposer la musique dans <musics>/Candidats/ puis de lancer list_songs.
#
# Usage : sudo ./installer.sh [options]
#   --musics CHEMIN        dossier musics (sinon demandé)
#   --utilisateur NOM      compte qui lance list_songs (sinon demandé ; défaut : celui qui a fait sudo)
#   --base garder|vider    base beets déjà présente : la garder, ou repartir d'une base vide (l'ancienne est sauvegardée)
#   --discogs              demande le jeton Discogs (pochettes) et l'enregistre dans ~/discog
#   --samba                partage le dossier musics sur le réseau (pas sur openmediavault : passer par son interface)
#   --domaine DOMAINE      publie l'annuaire en HTTPS sur ce domaine (annuaire/publier-https.sh)
#   --port-externe PORT    port de la box redirigé vers 8443 (avec --domaine, défaut 8443)
#   --oui                  aucune question : options données, sinon valeurs par défaut
#
# Sans le dépôt à côté (script copié seul), il est cloné dans ~<utilisateur>/DEV.
# Relançable sans risque : rien d'existant n'est écrasé (musique, configs, mot de passe, certificat).
# Pour repartir d'une sauvegarde : remettre le dossier musics (il contient .beets/, les bases), puis lancer ce script.
set -euo pipefail

MUSICS_DEFAUT=/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics
DEPOT_URL=https://github.com/k-vanier/DEV.git
CONF=/etc/list_songs.conf
MUSICS= UTIL= BASE= DOMAINE= PORT_EXT= DISCOGS= SAMBA= OUI=0 JETON= REPRENDRE=0

aide() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case $1 in
    --musics) MUSICS=${2%/}; shift ;;
    --utilisateur) UTIL=$2; shift ;;
    --base) BASE=$2; shift ;;
    --discogs) DISCOGS=1 ;;
    --samba) SAMBA=1 ;;
    --domaine) DOMAINE=$2; shift ;;
    --port-externe) PORT_EXT=$2; shift ;;
    --oui) OUI=1 ;;
    -h|--help) aide ;;
    *) echo "Option inconnue : $1"; aide 1 ;;
  esac
  shift
done
case $BASE in ''|garder|vider) ;; *) echo "--base : garder ou vider"; exit 1 ;; esac

etape() { echo; echo "=== $*"; }
[ "$(id -u)" = 0 ] || { echo "À lancer avec sudo."; exit 1; }
. /etc/os-release
case "${ID:-} ${ID_LIKE:-}" in *debian*|*ubuntu*) ;; *) echo "Prévu pour Debian / Ubuntu (ici : ${PRETTY_NAME:-inconnu})"; exit 1 ;; esac
OMV=0; [ -d /etc/openmediavault ] && OMV=1
INTER=0; [ -t 0 ] && [ $OUI = 0 ] && INTER=1

# demander VARIABLE "question" [défaut] : la réponse, ou le défaut sans question (--oui, pas de terminal)
demander() {
  local r
  if [ $INTER = 1 ]; then read -rp "$2${3:+ [$3]} : " r; r=${r:-${3:-}}; else r=${3:-}; fi
  printf -v "$1" '%s' "$r"
}
# oui_non "question" o|n : vrai si oui
oui_non() {
  local r
  if [ $INTER = 1 ]; then read -rp "$1 [$([ "$2" = o ] && echo O/n || echo o/N)] : " r; r=${r:-$2}; else r=$2; fi
  case $r in [oOyY]*) return 0 ;; *) return 1 ;; esac
}
chemin_valide() {
  case $1 in /*) ;; *) echo "Chemin absolu attendu (qui commence par /)."; return 1 ;; esac
  case $1 in *['&|"\']*|*"'"*) echo "Pas de & | \\ \" ou ' dans le chemin."; return 1 ;; esac
}

# ---------------------------------------------------------------- questions
[ $INTER = 1 ] && { echo "Installation de list_songs. Entrée = réponse proposée entre crochets."; echo; }

# dossier musics : celui déjà configuré, celui du serveur d'origine, sinon un disque de données
if [ -z "$MUSICS" ]; then
  propose=$( (MUSICS=; [ -r "$CONF" ] && . "$CONF"; echo "${MUSICS:-}") )
  [ -n "$propose" ] || { [ -d "$MUSICS_DEFAUT" ] && propose=$MUSICS_DEFAUT; } || true
  if [ -z "$propose" ]; then
    disque=$(ls -d /srv/dev-disk-by-* 2>/dev/null | head -1 || true)
    propose=${disque:+$disque/musics}; propose=${propose:-/srv/musics}
  fi
  if [ $INTER = 1 ]; then
    echo "Espace disponible :"
    df -h --output=target,avail,size / /srv/dev-disk-by-* /mnt/* /media/* 2>/dev/null | awk 'NR==1 || !seen[$1]++' || true
    echo
  fi
  while :; do
    demander MUSICS "Dossier musique (créé s'il n'existe pas)" "$propose"
    MUSICS=${MUSICS%/}
    chemin_valide "$MUSICS" && break
    [ $INTER = 1 ] || exit 1
  done
fi
chemin_valide "$MUSICS" || exit 1

[ -n "$UTIL" ] || demander UTIL "Compte qui lancera list_songs" "${SUDO_USER:-}"
[ -n "$UTIL" ] && [ "$UTIL" != root ] || { echo "Préciser un compte autre que root : --utilisateur NOM"; exit 1; }
id "$UTIL" >/dev/null 2>&1 || { echo "Compte inconnu : $UTIL"; exit 1; }
MAISON=$(getent passwd "$UTIL" | cut -d: -f6)
GROUPE=$(id -gn "$UTIL")

# base beets : garder celle du dossier, ou repartir de zéro ; reprendre l'ancienne de ~/.config/beets
BASES=0; ls "$MUSICS"/.beets/{lowres,hires}/library.db >/dev/null 2>&1 && BASES=1
if [ $BASES = 1 ]; then
  echo "Base beets déjà présente :"; du -h "$MUSICS"/.beets/{lowres,hires}/library.db 2>/dev/null | sed 's/^/  /'
  if [ -z "$BASE" ]; then
    if oui_non "La garder ? (non = repartir d'une base vide, l'ancienne est sauvegardée)" o; then BASE=garder; else BASE=vider; fi
  fi
  if [ "$BASE" = vider ] && [ -n "$(find "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res" -type f 2>/dev/null | head -1)" ]; then
    echo "Attention : les morceaux déjà rangés dans les bibliothèques ne seront plus dans la base."
  fi
elif [ -f "$MAISON/.config/beets/library.db" ] && [ ! -d "$MUSICS/.beets" ]; then
  echo "Ancienne base trouvée dans $MAISON/.config/beets."
  oui_non "La reprendre ? (non = base vide)" o && REPRENDRE=1
fi
BASE=${BASE:-garder}

if [ -z "$DISCOGS" ]; then
  DISCOGS=0
  if [ ! -s "$MAISON/discog" ] && oui_non "Ajouter un jeton Discogs (meilleures pochettes) ?" n; then DISCOGS=1; fi
fi
if [ $DISCOGS = 1 ] && [ ! -s "$MAISON/discog" ]; then
  if [ $INTER = 1 ] || [ -t 0 ]; then
    echo "Jeton personnel : https://www.discogs.com/settings/developers (« Generate new token »)"
    read -rsp "Jeton (rien ne s'affiche, Entrée pour passer) : " JETON; echo
  else
    echo "--discogs : pas de terminal pour saisir le jeton, étape passée"
  fi
fi

if [ -z "$SAMBA" ]; then
  SAMBA=0
  if [ $OMV = 0 ]; then oui_non "Partager le dossier musique sur le réseau (Samba) ?" n && SAMBA=1; fi
fi

if [ -z "$DOMAINE" ] && oui_non "Publier l'annuaire en HTTPS, accessible depuis Internet ?" n; then
  while [ -z "$DOMAINE" ]; do demander DOMAINE "Nom de domaine (ex. mon-nom.freeboxos.fr)"; done
fi
if [ -n "$DOMAINE" ] && [ -z "$PORT_EXT" ]; then
  demander PORT_EXT "Port externe de la box, redirigé vers ce serveur port 8443" 8443
fi
PORT_EXT=${PORT_EXT:-8443}

etape "Récapitulatif"
cat <<EOF
Dossier musique : $MUSICS$([ -d "$MUSICS" ] || echo ' (sera créé)')
Compte          : $UTIL
Base beets      : $([ $REPRENDRE = 1 ] && echo "reprise de $MAISON/.config/beets" || { [ $BASES = 1 ] && [ "$BASE" = garder ] && echo gardée; } || echo "nouvelle, vide")
Discogs         : $([ -s "$MAISON/discog" ] && echo "déjà configuré" || { [ -n "$JETON" ] && echo oui; } || echo non)
Partage réseau  : $([ $OMV = 1 ] && echo "via openmediavault" || { [ $SAMBA = 1 ] && echo "Samba [musics]"; } || echo non)
HTTPS           : $([ -n "$DOMAINE" ] && echo "https://$DOMAINE:$PORT_EXT/" || echo non)
EOF
if [ $INTER = 1 ]; then echo; oui_non "Lancer l'installation ?" o || { echo "Rien n'a été modifié."; exit 0; }; fi

# ---------------------------------------------------------------- installation
en_tant_que() { runuser -u "$UTIL" -- env HOME="$MAISON" "$@"; }
# sortie d'apt masquée, affichée seulement en cas d'échec
JOURNAL_APT=$(mktemp)
paquets() {
  echo "installation : $*"
  apt-get install -y -qq -o Dpkg::Use-Pty=0 "$@" >"$JOURNAL_APT" 2>&1 || { cat "$JOURNAL_APT" >&2; return 1; }
}

etape "Paquets ($PRETTY_NAME)"
export DEBIAN_FRONTEND=noninteractive
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
# lu par list_songs, regenerer.sh et publier-https.sh
printf "# écrit par list_songs/installer.sh\nMUSICS='%s'\n" "$MUSICS" > "$CONF"
chmod 644 "$CONF"
echo "dossier musique enregistré dans $CONF"
# seuls les dossiers créés ici changent de propriétaire : la musique déjà présente garde ses droits
for d in "$MUSICS" "$MUSICS/Candidats" "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res"; do
  [ -d "$d" ] || { install -d -o "$UTIL" -g "$GROUPE" -m 2775 "$d"; echo "créé : $d"; }
done

etape "Base beets"
if [ $REPRENDRE = 1 ]; then
  # list_songs déplace ~/.config/beets dans musics/.beets à son premier lancement
  en_tant_que "$LS/list_songs" --simulation --sans-internet | sed -n '1,3p'
  grep -h '^directory:' "$MUSICS"/.beets/{lowres,hires}/config.yaml 2>/dev/null | grep -vF "$MUSICS/" \n    && echo "Attention : ces bibliothèques pointent ailleurs que $MUSICS (à corriger dans .beets/*/config.yaml)" || true
fi
for d in "$MUSICS/.beets" "$MUSICS/.beets/lowres" "$MUSICS/.beets/hires" "$MUSICS/.beets/journal"; do
  [ -d "$d" ] || install -d -o "$UTIL" -g "$GROUPE" -m 2775 "$d"
done
en_tant_que test -w "$MUSICS/Candidats" -a -w "$MUSICS/.beets" \
  || { echo "$UTIL ne peut pas écrire dans $MUSICS/Candidats ou $MUSICS/.beets : corriger les droits du dossier"; exit 1; }
for lib in lowres hires; do
  dir=$MUSICS/.beets/$lib
  if [ "$BASE" = vider ] && [ -f "$dir/library.db" ]; then
    sauv=$MUSICS/.beets/journal/${lib}_library_avant_installation_$(date +%Y%m%d-%H%M%S).db
    mv "$dir/library.db" "$sauv"
    echo "ancienne base sauvegardée : $sauv"
  fi
  if [ -f "$dir/config.yaml" ]; then
    echo "configuration gardée : $dir/config.yaml"
  else
    sed "s|$MUSICS_DEFAUT|$MUSICS|g" "$LS/exemples/beets-$lib.yaml" | tr -d '\r' > "$dir/config.yaml"
    chown "$UTIL:$GROUPE" "$dir/config.yaml"
    echo "configuration créée : $dir/config.yaml"
  fi
  if [ ! -f "$dir/library.db" ]; then
    en_tant_que env BEETSDIR="$dir" PYTHONPATH=/usr/share/beets beet stats >/dev/null
    echo "base vide créée : $dir/library.db"
  else
    echo "base gardée : $dir/library.db"
  fi
done

etape "Commandes list_songs et annuaire-regenerer"
for c in "list_songs:$LS/list_songs" "annuaire-regenerer:$LS/annuaire/regenerer.sh"; do
  printf '#!/bin/sh\n# installé par list_songs/installer.sh (dossier musique : %s)\nexec '\''%s'\'' "$@"\n' "$CONF" "${c#*:}" > "/usr/local/bin/${c%%:*}"
  chmod 755 "/usr/local/bin/${c%%:*}"
done
echo "list_songs et annuaire-regenerer utilisables depuis n'importe quel dossier"

if [ -n "$JETON" ]; then
  etape "Jeton Discogs"
  (umask 077; printf '%s\n' "$JETON" > "$MAISON/discog")
  chown "$UTIL:$GROUPE" "$MAISON/discog"; chmod 600 "$MAISON/discog"
  echo "enregistré : $MAISON/discog"
fi

if [ $SAMBA = 1 ] && [ $OMV = 0 ]; then
  etape "Partage Samba"
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
    testparm -s >/dev/null 2>&1 && systemctl restart smbd
  fi
  pdbedit -L 2>/dev/null | grep -q "^$UTIL:" || { echo "Mot de passe réseau (Samba) pour $UTIL :"; smbpasswd -a "$UTIL"; }
  echo "partage : \\\\$(hostname)\\musics"
fi

etape "Annuaire"
en_tant_que "$LS/annuaire/regenerer.sh"

if [ -n "$DOMAINE" ]; then
  etape "HTTPS ($DOMAINE)"
  "$LS/annuaire/publier-https.sh" "$DOMAINE" "$PORT_EXT"
fi

etape "Tout est prêt"
cat <<EOF
1. Dépose ta musique (dossiers, zip, rar, 7z…) dans : $MUSICS/Candidats/
2. Lance : list_songs --simulation   (pour voir), puis : list_songs
Annuaire            : $MUSICS/Annuaire.html (régénérer : annuaire-regenerer)
À sauvegarder       : $MUSICS (musique + .beets/)$([ -s "$MAISON/discog" ] && echo " et $MAISON/discog")
EOF
[ -n "$DOMAINE" ] && echo "Annuaire en ligne   : https://$DOMAINE:$PORT_EXT/"
[ $OMV = 1 ] && echo "Partage réseau      : à créer dans openmediavault (Services → SMB/CIFS) s'il n'existe pas"
exit 0
