#!/bin/bash
# Publie l'annuaire (musics/Annuaire.html) en HTTPS avec nginx, mot de passe et certificat Let's Encrypt.
#
# Usage : sudo ./publier-https.sh <domaine> [port externe]
#   ex. : sudo ./publier-https.sh mon-nom.freeboxos.fr 8081
# Le port externe est celui de la box redirigé vers 8443 (par défaut 8443).
# Avant de lancer : dans la box, rediriger le port externe 80 vers <ce serveur>:8080 (TCP),
# et le port externe choisi vers <ce serveur>:8443 (TCP).
# Relançable sans risque : ce qui existe déjà (mot de passe, certificat) est gardé.
set -euo pipefail

DOMAINE=${1:-}
PORT_EXT=${2:-8443}
# dossier musics : variable MUSICS, sinon /etc/list_songs.conf (écrit par installer.sh), sinon celui du serveur
M=${MUSICS:-}; MUSICS=; [ -r /etc/list_songs.conf ] && . /etc/list_songs.conf
MUSICS=${M:-${MUSICS:-/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics}}; MUSICS=${MUSICS%/}
HTTP=8080
HTTPS=8443
CONF=/etc/nginx/conf.d/annuaire.conf
HTPASSWD=/etc/nginx/annuaire.htpasswd
ACME=/var/www/acme
AUTOSIGNE=/etc/ssl/annuaire
LE=/etc/letsencrypt/live/$DOMAINE

[ -n "$DOMAINE" ] || { sed -n '3,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ "$(id -u)" = 0 ] || { echo "À lancer avec sudo."; exit 1; }
[ -f "$MUSICS/Annuaire.html" ] || { echo "Annuaire introuvable : $MUSICS/Annuaire.html (lancer list_songs une fois)"; exit 1; }

# ports déjà pris par autre chose que nginx (un conteneur Docker, par exemple)
for p in $HTTP $HTTPS; do
  if ss -ltnpH "sport = :$p" | grep -qv nginx; then
    echo "Le port $p est déjà utilisé par un autre programme :"; ss -ltnpH "sport = :$p"; exit 1
  fi
done

echo "--- Paquets"
apt-get install -y -q nginx certbot apache2-utils >/dev/null

echo "--- Accès de nginx (www-data) à la musique"
if ! sudo -u www-data test -r "$MUSICS/Annuaire.html"; then
  g=$(stat -c %G "$MUSICS")
  usermod -aG "$g" www-data
  echo "www-data ajouté au groupe $g"
  sudo -u www-data test -r "$MUSICS/Annuaire.html" || { echo "nginx ne peut toujours pas lire $MUSICS (droits du partage ?)"; exit 1; }
fi

echo "--- Mot de passe"
if [ -s "$HTPASSWD" ]; then
  echo "Déjà défini ($HTPASSWD) ; pour ajouter quelqu'un : sudo htpasswd -B $HTPASSWD <nom>"
else
  read -rp "Nom d'utilisateur pour la page : " nom
  htpasswd -B -c "$HTPASSWD" "$nom"
fi
chown root:www-data "$HTPASSWD"; chmod 640 "$HTPASSWD"

# écrit la config nginx avec le certificat donné
ecrire_conf() {
  cat > "$CONF" <<EOF
# généré par list_songs/annuaire/publier-https.sh
server {
    listen $HTTP;
    location /.well-known/acme-challenge/ { root $ACME; }
    location / { return 301 https://\$host:$PORT_EXT\$request_uri; }
}

server {
    listen $HTTPS ssl;
    ssl_certificate     $1;
    ssl_certificate_key $2;
    ssl_protocols       TLSv1.2 TLSv1.3;
    auth_basic           "Annuaire";
    auth_basic_user_file $HTPASSWD;

    root $MUSICS;
    index Annuaire.html;
    charset utf-8;

    # ne pas exposer les bases beets (.beets/), Candidats/ ni le cache
    location ~ /\.            { deny all; }
    location ^~ /Candidats/   { deny all; }
    location ~ \.db\$          { deny all; }

    location / { try_files \$uri \$uri/ =404; }
}
EOF
  nginx -t -q && systemctl reload nginx
}

echo "--- Configuration nginx"
[ -f "$CONF" ] && ! grep -q 'publier-https.sh' "$CONF" && cp "$CONF" "$CONF.avant-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ACME"
if [ ! -f "$LE/fullchain.pem" ]; then
  # certificat provisoire, le temps d'obtenir celui de Let's Encrypt
  if [ ! -f "$AUTOSIGNE/annuaire.crt" ]; then
    mkdir -p "$AUTOSIGNE"
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -keyout "$AUTOSIGNE/annuaire.key" -out "$AUTOSIGNE/annuaire.crt" \
      -subj "/CN=$DOMAINE" -addext "subjectAltName=DNS:$DOMAINE" 2>/dev/null
    chmod 600 "$AUTOSIGNE/annuaire.key"
  fi
  ecrire_conf "$AUTOSIGNE/annuaire.crt" "$AUTOSIGNE/annuaire.key"

  echo "--- Certificat Let's Encrypt"
  echo "La box doit rediriger le port externe 80 vers ce serveur, port $HTTP (TCP)."
  read -rp "Entrée quand c'est fait… " _
  certbot certonly --webroot -w "$ACME" -d "$DOMAINE"
fi
ecrire_conf "$LE/fullchain.pem" "$LE/privkey.pem"

echo "--- Renouvellement automatique"
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/nginx.sh
chmod +x /etc/letsencrypt/renewal-hooks/deploy/nginx.sh
certbot renew --dry-run -q && echo "Renouvellement : OK"

echo
echo "Annuaire publié : https://$DOMAINE:$PORT_EXT/"
echo "Garder la redirection du port 80 dans la box : Let's Encrypt en a besoin tous les 90 jours."
