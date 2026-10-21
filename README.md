# list_songs

Range automatiquement la musique déposée dans `musics/Candidats/` vers deux bibliothèques
(`musics/Musiques Low-Res` pour le MP3, `musics/Musiques Hi-Res` pour FLAC/WAV/DSD/AIFF/WavPack/APE/ALAC),
avec [beets](https://beets.io).

## Ce que fait le script

1. Aiguillage des fichiers vers la bonne bibliothèque selon leur format.
2. Import beets **sans modifier les tags** (`-A -C -W`).
3. Complétion des métadonnées manquantes d'après les noms de dossiers (artiste, album, année, CD),
   rattachement aux artistes/albums existants, nettoyage des noms (`[FLAC]`, `CD1`…).
4. Rangement en `Artistes/<Artiste>/(<Année>) <Album>/NN - Titre` ou `Compilations/(<Année>) <Album>/`.
   Pas de doublons ni de `.1` : une piste dont le fichier existe déjà à destination, ou identique
   (contenu) à un fichier de la bibliothèque ou à un autre fichier déposé, n'est pas ajoutée ; elle est
   mise de côté dans `Candidats/_déjà présents/`. Une piste manquante d'un album existant est ajoutée.
5. Pochette `folder.jpg` : intégrée → image déposée → Deezer → iTunes → Cover Art Archive → Discogs → générée.
6. Régénération de `Annuaire.html` / `Annuaire.csv` dans chaque bibliothèque.

## Utilisation

```
./list_songs --simulation     # aperçu, rien n'est déplacé
./list_songs                  # rangement réel
./list_songs --sans-internet  # pochettes sans recherche en ligne
./list_songs --sans-pochettes
```

Variables d'environnement : `RANGER_ROOT` (dossier `musics/` contenant `Candidats` et les bibliothèques), `RANGER_HOME`.

## Prérequis

- Debian : `apt install beets python3-pil python3-mediafile python3-unidecode fonts-dejavu-core`
- Configurations beets : voir `exemples/` (Low-Res dans `~/.config/beets`, Hi-Res dans `~/.config/beets/hires`).
- Annuaire : copier `annuaire/` dans `~/.config/beets/annuaire/`.
- Discogs (facultatif) : jeton personnel dans `~/discog` (chmod 600) — **ne jamais le committer**.

Un journal est écrit dans `~/.config/beets/journal/ranger_<date>.log` et la base beets est sauvegardée avant chaque rangement.
