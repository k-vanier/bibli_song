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
#   --reprendre            reprend une installation interrompue sans le demander
#   --recommencer          refait toute l'installation sans le demander
#   --oui                  aucune question : options données, sinon valeurs par défaut (et reprise si interrompue)
#
# Chaque étape réussie est notée dans /var/lib/list_songs/ : après un échec, relancer le script propose de reprendre
# là où il s'est arrêté, avec les mêmes réponses, sans refaire les étapes validées.
# Sans le dépôt à côté (script copié seul), il est cloné dans ~<utilisateur>/DEV.
# Rien d'existant n'est écrasé (musique, configs, mot de passe, certificat).
# Pour repartir d'une sauvegarde : remettre le dossier musics (il contient .beets/, les bases), puis lancer ce script.
set -euo pipefail

MUSICS_DEFAUT=/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics
DEPOT_URL=https://github.com/k-vanier/DEV.git
CONF=/etc/list_songs.conf
ETAT=/var/lib/list_songs  # reponses (choix de l'installation), etapes (une étape validée par ligne), termine (date)
REPONSES="MUSICS UTIL BASE ANCIENNE DISCOGS SAMBA DOMAINE PORT_EXT"
MUSICS= UTIL= BASE= ANCIENNE= DISCOGS= SAMBA= DOMAINE= PORT_EXT= OUI=0 JETON= MODE=

aide() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case $1 in
    --musics) MUSICS=${2%/}; shift ;;
    --utilisateur) UTIL=$2; shift ;;
    --base) BASE=$2; shift ;;
    --discogs) DISCOGS=1 ;;
    --samba) SAMBA=1 ;;
    --domaine) DOMAINE=$2; shift ;;
    --port-externe) PORT_EXT=$2; shift ;;
    --reprendre) MODE=reprendre ;;
    --recommencer) MODE=recommencer ;;
    --oui) OUI=1 ;;
    -h|--help) aide ;;
    *) echo "Option inconnue : $1"; aide 1 ;;
  esac
  shift
done
case $BASE in ''|garder|vider) ;; *) echo "--base : garder ou vider"; exit 1 ;; esac

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
fait() { grep -qx "$1" "$ETAT/etapes" 2>/dev/null; }

# ---------------------------------------------------------------- installation précédente
declare -A TITRE=([paquets]=Paquets [depot]=Dépôt [dossiers]=Dossiers [base]="Base beets"
                  [commandes]=Commandes [discogs]="Jeton Discogs" [samba]="Partage Samba"
                  [annuaire]=Annuaire [https]=HTTPS)
if [ -f "$ETAT/reponses" ]; then
  eval "$(sed 's/^/PREC_/' "$ETAT/reponses")"  # réponses précédentes, en PREC_MUSICS, PREC_UTIL…
  faites=$(while read -r e; do [ -z "${TITRE[$e]:-}" ] || printf '%s, ' "${TITRE[$e]}"; done 2>/dev/null < "$ETAT/etapes" || true)
  if [ -f "$ETAT/termine" ]; then
    echo "Une installation est déjà terminée ($(cat "$ETAT/termine")), dossier musique : ${PREC_MUSICS:-?}"
    if [ -z "$MODE" ]; then
      if [ $INTER = 0 ] || oui_non "La refaire ? (questions et toutes les étapes ; rien d'existant n'est écrasé)" n; then
        MODE=recommencer
      else
        echo "Rien à faire."; exit 0
      fi
    fi
  else
    echo "Une installation a été interrompue (dossier musique : ${PREC_MUSICS:-?})."
    echo "Étapes déjà validées : ${faites%, }"
    if [ -z "$MODE" ]; then
      if oui_non "La reprendre là où elle s'est arrêtée ? (non = tout refaire depuis le début)" o; then
        MODE=reprendre
      else
        MODE=recommencer
      fi
    fi
  fi
  if [ "$MODE" = reprendre ]; then
    for v in $REPONSES; do p=PREC_$v; [ -n "${!v}" ] || printf -v "$v" '%s' "${!p:-}"; done
  else
    rm -f "$ETAT/etapes" "$ETAT/termine"
  fi
  echo
else
  MODE=nouvelle
fi

# ---------------------------------------------------------------- questions
if [ "$MODE" != reprendre ]; then
  [ $INTER = 1 ] && { echo "Installation de list_songs. Entrée = réponse proposée entre crochets."; echo; }

  # dossier musics : celui de l'installation précédente ou déjà configuré, celui du serveur d'origine, sinon un disque
  if [ -z "$MUSICS" ]; then
    propose=${PREC_MUSICS:-$( (MUSICS=; [ -r "$CONF" ] && . "$CONF"; echo "${MUSICS:-}") )}
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
  [ -n "$UTIL" ] || demander UTIL "Compte qui lancera list_songs" "${PREC_UTIL:-${SUDO_USER:-}}"
fi
chemin_valide "$MUSICS" || exit 1
[ -n "$UTIL" ] && [ "$UTIL" != root ] || { echo "Préciser un compte autre que root : --utilisateur NOM"; exit 1; }
id "$UTIL" >/dev/null 2>&1 || { echo "Compte inconnu : $UTIL"; exit 1; }
MAISON=$(getent passwd "$UTIL" | cut -d: -f6)
GROUPE=$(id -gn "$UTIL")

if [ "$MODE" != reprendre ]; then
  # base beets : garder celle du dossier, ou repartir de zéro ; reprendre l'ancienne de ~/.config/beets
  if ls "$MUSICS"/.beets/{lowres,hires}/library.db >/dev/null 2>&1; then
    echo "Base beets déjà présente :"; du -h "$MUSICS"/.beets/{lowres,hires}/library.db 2>/dev/null | sed 's/^/  /'
    if [ -z "$BASE" ]; then
      if oui_non "La garder ? (non = repartir d'une base vide, l'ancienne est sauvegardée)" o; then BASE=garder; else BASE=vider; fi
    fi
    if [ "$BASE" = vider ] && [ -n "$(find "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res" -type f 2>/dev/null | head -1)" ]; then
      echo "Attention : les morceaux déjà rangés dans les bibliothèques ne seront plus dans la base."
    fi
  elif [ -f "$MAISON/.config/beets/library.db" ] && [ ! -d "$MUSICS/.beets" ]; then
    echo "Ancienne base trouvée dans $MAISON/.config/beets."
    if oui_non "La reprendre ? (non = base vide)" o; then ANCIENNE=1; fi
  fi
  if [ -z "$DISCOGS" ]; then
    DISCOGS=0
    if [ ! -s "$MAISON/discog" ] && oui_non "Ajouter un jeton Discogs (meilleures pochettes) ?" n; then DISCOGS=1; fi
  fi
  if [ -z "$SAMBA" ]; then
    SAMBA=0
    if [ $OMV = 0 ] && oui_non "Partager le dossier musique sur le réseau (Samba) ?" n; then SAMBA=1; fi
  fi
  if [ -z "$DOMAINE" ] && oui_non "Publier l'annuaire en HTTPS, accessible depuis Internet ?" n; then
    while [ -z "$DOMAINE" ]; do demander DOMAINE "Nom de domaine (ex. mon-nom.freeboxos.fr)"; done
  fi
  if [ -n "$DOMAINE" ] && [ -z "$PORT_EXT" ]; then
    demander PORT_EXT "Port externe de la box, redirigé vers ce serveur port 8443" 8443
  fi
fi
BASE=${BASE:-garder} ANCIENNE=${ANCIENNE:-0} DISCOGS=${DISCOGS:-0} SAMBA=${SAMBA:-0} PORT_EXT=${PORT_EXT:-8443}
# le jeton n'est jamais enregistré dans l'état : redemandé si l'étape reste à faire
if [ "$DISCOGS" = 1 ] && [ ! -s "$MAISON/discog" ] && ! fait discogs; then
  if [ -t 0 ]; then
    echo "Jeton personnel Discogs : https://www.discogs.com/settings/developers (« Generate new token »)"
    read -rsp "Jeton (rien ne s'affiche, Entrée pour passer) : " JETON; echo
  else
    echo "--discogs : pas de terminal pour saisir le jeton, étape passée"
  fi
fi

# étapes de cette installation, dans l'ordre
ETAPES="paquets depot dossiers base commandes"
[ -n "$JETON" ] && ETAPES+=" discogs"
[ "$SAMBA" = 1 ] && [ $OMV = 0 ] && ETAPES+=" samba"
ETAPES+=" annuaire"
[ -n "$DOMAINE" ] && ETAPES+=" https"

echo; echo "=== Récapitulatif"
cat <<EOF
Dossier musique : $MUSICS$([ -d "$MUSICS" ] || echo ' (sera créé)')
Compte          : $UTIL
Base beets      : $([ "$ANCIENNE" = 1 ] && echo "reprise de $MAISON/.config/beets" || { [ "$BASE" = vider ] && echo "nouvelle, vide (l'ancienne est sauvegardée)"; } || echo "gardée si elle existe, sinon nouvelle et vide")
Discogs         : $([ -s "$MAISON/discog" ] && echo "déjà configuré" || { [ -n "$JETON" ] && echo oui; } || echo non)
Partage réseau  : $([ $OMV = 1 ] && echo "via openmediavault" || { [ "$SAMBA" = 1 ] && echo "Samba [musics]"; } || echo non)
HTTPS           : $([ -n "$DOMAINE" ] && echo "https://$DOMAINE:$PORT_EXT/" || echo non)
Étapes          : $(for e in $ETAPES; do printf '%s%s, ' "${TITRE[$e]}" "$(fait "$e" && echo ' (validée)')"; done | sed 's/, $//')
EOF
if [ $INTER = 1 ]; then echo; oui_non "Lancer l'installation ?" o || { echo "Rien n'a été modifié."; exit 0; }; fi

mkdir -p "$ETAT"; chmod 700 "$ETAT"
: > "$ETAT/reponses"
for v in $REPONSES; do printf '%s=%q\n' "$v" "${!v}" >> "$ETAT/reponses"; done
touch "$ETAT/etapes"

# ---------------------------------------------------------------- étapes
en_tant_que() { runuser -u "$UTIL" -- env HOME="$MAISON" "$@"; }
# sortie d'apt masquée, affichée seulement en cas d'échec
JOURNAL_APT=$(mktemp)
paquets() {
  echo "installation : $*"
  apt-get install -y -qq -o Dpkg::Use-Pty=0 "$@" >"$JOURNAL_APT" 2>&1 || { cat "$JOURNAL_APT" >&2; return 1; }
}
ICI=$(dirname "$(readlink -f "$0")")
if [ -f "$ICI/list_songs.py" ]; then LS=$ICI; else LS=$MAISON/DEV/list_songs; fi

etape_paquets() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  paquets git sudo beets python3-pil python3-mediafile python3-unidecode fonts-dejavu-core unar
  # 7z pour les archives .7z (et .rar en secours) : paquet « 7zip » récent, sinon « p7zip-full »
  paquets 7zip 2>/dev/null || paquets p7zip-full
  PYTHONPATH=/usr/share/beets python3 -c 'import beets, mediafile, PIL, unidecode' \
    || { echo "Modules Python manquants (beets, mediafile, PIL, unidecode)"; return 1; }
}

etape_depot() {
  if [ "$LS" != "$ICI" ]; then
    if [ ! -d "$MAISON/DEV/.git" ]; then
      en_tant_que git clone -q "$DEPOT_URL" "$MAISON/DEV"
    else
      en_tant_que git -C "$MAISON/DEV" pull -q --ff-only || echo "(mise à jour du dépôt impossible, on garde la version présente)"
    fi
  fi
  chmod +x "$LS/list_songs" "$LS/list_songs.py" "$LS/annuaire/regenerer.sh" "$LS/annuaire/publier-https.sh" "$LS/installer.sh"
  echo "list_songs : $LS"
}

etape_dossiers() {
  # lu par list_songs, regenerer.sh et publier-https.sh
  printf "# écrit par list_songs/installer.sh\nMUSICS='%s'\n" "$MUSICS" > "$CONF"
  chmod 644 "$CONF"
  echo "dossier musique enregistré dans $CONF"
  # seuls les dossiers créés ici changent de propriétaire : la musique déjà présente garde ses droits
  local d
  for d in "$MUSICS" "$MUSICS/Candidats" "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res"; do
    [ -d "$d" ] || { install -d -o "$UTIL" -g "$GROUPE" -m 2775 "$d"; echo "créé : $d"; }
  done
  # dossier déjà là mais appartenant à un autre compte (root, dossier partagé…) : list_songs doit pouvoir y écrire
  if ! en_tant_que test -w "$MUSICS"; then
    if [ -z "$(ls -A "$MUSICS" | grep -vxE 'Candidats|Musiques Low-Res|Musiques Hi-Res' || true)" ]; then
      chown "$UTIL:$GROUPE" "$MUSICS"; chmod 2775 "$MUSICS"
      echo "droits donnés à $UTIL sur $MUSICS (dossier vide)"
    fi
  fi
  for d in "$MUSICS" "$MUSICS/Candidats" "$MUSICS/Musiques Low-Res" "$MUSICS/Musiques Hi-Res"; do
    en_tant_que test -w "$d" || {
      echo "$UTIL ne peut pas écrire dans $d (propriétaire : $(stat -c %U:%G "$d"))."
      echo "Par exemple : sudo chown $UTIL \"$d\"  (ou ajouter $UTIL au groupe $(stat -c %G "$d")), puis relancer."
      return 1
    }
  done
}

etape_base() {
  if [ "$ANCIENNE" = 1 ] && [ ! -d "$MUSICS/.beets" ]; then
    # list_songs déplace ~/.config/beets dans musics/.beets à son premier lancement
    en_tant_que "$LS/list_songs" --simulation --sans-internet | sed -n '1,3p'
    if grep -h '^directory:' "$MUSICS"/.beets/{lowres,hires}/config.yaml 2>/dev/null | grep -vF "$MUSICS/"; then
      echo "Attention : ces bibliothèques pointent ailleurs que $MUSICS (à corriger dans .beets/*/config.yaml)"
    fi
  fi
  local d lib dir sauv
  for d in "$MUSICS/.beets" "$MUSICS/.beets/lowres" "$MUSICS/.beets/hires" "$MUSICS/.beets/journal"; do
    [ -d "$d" ] || install -d -o "$UTIL" -g "$GROUPE" -m 2775 "$d"
  done
  en_tant_que test -w "$MUSICS/Candidats" -a -w "$MUSICS/.beets" \
    || { echo "$UTIL ne peut pas écrire dans $MUSICS/Candidats ou $MUSICS/.beets : corriger les droits du dossier"; return 1; }
  for lib in lowres hires; do
    dir=$MUSICS/.beets/$lib
    # vider : une seule fois par base (une reprise après échec ne revide pas une base déjà neuve)
    if [ "$BASE" = vider ] && [ -f "$dir/library.db" ] && ! fait "base-videe-$lib"; then
      sauv=$MUSICS/.beets/journal/${lib}_library_avant_installation_$(date +%Y%m%d-%H%M%S).db
      mv "$dir/library.db" "$sauv"
      echo "base-videe-$lib" >> "$ETAT/etapes"
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
}

etape_commandes() {
  local c
  for c in "list_songs:$LS/list_songs" "annuaire-regenerer:$LS/annuaire/regenerer.sh"; do
    printf '#!/bin/sh\n# installé par list_songs/installer.sh (dossier musique : %s)\nexec '\''%s'\'' "$@"\n' "$CONF" "${c#*:}" > "/usr/local/bin/${c%%:*}"
    chmod 755 "/usr/local/bin/${c%%:*}"
  done
  echo "list_songs et annuaire-regenerer utilisables depuis n'importe quel dossier"
}

etape_discogs() {
  (umask 077; printf '%s\n' "$JETON" > "$MAISON/discog")
  chown "$UTIL:$GROUPE" "$MAISON/discog"; chmod 600 "$MAISON/discog"
  echo "enregistré : $MAISON/discog"
}

etape_samba() {
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
}

etape_annuaire() { en_tant_que "$LS/annuaire/regenerer.sh"; }

etape_https() { "$LS/annuaire/publier-https.sh" "$DOMAINE" "$PORT_EXT"; }

EN_COURS=
trap 'c=$?; if [ $c != 0 ] && [ -n "$EN_COURS" ]; then
  echo; echo "*** Échec à l'\''étape « $EN_COURS »."
  echo "Corrige le problème, puis relance : sudo $0"
  echo "et choisis de reprendre : les étapes déjà validées ne seront pas refaites."; fi' EXIT

for e in $ETAPES; do
  echo
  if fait "$e"; then echo "=== ${TITRE[$e]} : déjà validée"; continue; fi
  echo "=== ${TITRE[$e]}"
  EN_COURS=${TITRE[$e]}
  "etape_$e"
  echo "$e" >> "$ETAT/etapes"
done
EN_COURS=
date '+%d/%m/%Y %H:%M' > "$ETAT/termine"

echo; echo "=== Tout est prêt"
cat <<EOF
1. Dépose ta musique (dossiers, zip, rar, 7z…) dans : $MUSICS/Candidats/
2. Lance : list_songs --simulation   (pour voir), puis : list_songs
Annuaire            : $MUSICS/Annuaire.html (régénérer : annuaire-regenerer)
À sauvegarder       : $MUSICS (musique + .beets/)$([ -s "$MAISON/discog" ] && echo " et $MAISON/discog")
EOF
[ -n "$DOMAINE" ] && echo "Annuaire en ligne   : https://$DOMAINE:$PORT_EXT/"
[ $OMV = 1 ] && echo "Partage réseau      : à créer dans openmediavault (Services → SMB/CIFS) s'il n'existe pas"
exit 0
