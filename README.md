# list_songs

Automatically files the music dropped into `musics/Candidats/` into two libraries
(`musics/Musiques Low-Res` for MP3, `musics/Musiques Hi-Res` for FLAC/WAV/DSD/AIFF/WavPack/APE/ALAC),
using [beets](https://beets.io).

## What the script does

1. Routes files to the right library based on their format.
2. Imports them with beets **without modifying tags** (`-A -C -W`).
3. Fills in missing metadata from folder names (artist, album, year, disc),
   matches existing artists/albums, cleans up names (`[FLAC]`, `CD1`…).
4. Files tracks as `Artistes/<Artist>/(<Year>) <Album>/NN - Title` or `Compilations/(<Year>) <Album>/`.
   No duplicates and no `.1` files: a track that is already present is not added. If its content is
   identical to a file in the library (or to another dropped file), it is deleted from `Candidats/`;
   if only the name matches (different content), it is set aside in `Candidats/_déjà présents/`.
   A missing track of an existing album is added.
   Comparison uses BLAKE2 hashes, only between files of the same size; the library hashes are cached
   in `musics/empreintes.db` (the old cache `~/.config/beets/empreintes.db` is moved there automatically).
5. `folder.jpg` cover: image already present (in the album folder of the library, the dropped folder,
   its parent or a `Scans`/`Artwork`/`Covers` subfolder) → embedded → Deezer → iTunes → Cover Art Archive
   → Discogs → generated. A present image named `cover`, `front`, `folder`, `jaquette`… wins over the embedded
   cover; an image with another name is used only if there is no embedded cover; `back`, `cd`, `booklet`… are ignored.
6. Regenerates a single directory page for both libraries: `musics/Annuaire.html` / `musics/Annuaire.csv`
   (filter by library, download button next to each track).
   Opened from the network share, the page also has foobar2000 buttons (play a track, play or add an album).
   Once per Windows PC, double-click `musics\foobar\Installer le lien foobar.cmd` (no admin rights;
   `Retirer le lien foobar.cmd` removes it). Downloading from the share: right-click ⬇ → "Save link as…".
   Subfolders: any depth is accepted (`Artist - Discography/Singles/Artist - 1996 - Title/`…).
   Subfolders without music (`Covers/`, `Scans/`…) follow their album, so their images are used as covers
   and then cleaned up. Several dropped folders of the same album with the same titles are editions, not CDs:
   they are filed separately, as `Album (EU)` / `Album (US)` (or `Album (édition 2)`).
7. Cleans up `Candidats/`: once an album is imported, its remaining files (images, `.cue`, `.nfo`…)
   are deleted. Anything that could not be imported (unsupported format, unreadable file) stays in place.

## Usage

```
./list_songs --simulation     # preview, nothing is moved
./list_songs                  # actual filing
./list_songs --sans-internet  # covers without online lookup
./list_songs --sans-pochettes # no covers
./list_songs --empreintes     # precompute hashes for the whole library (optional)
./list_songs --verification   # full hash recomputation + library check
./list_songs --verification --simulation  # same, without fixing anything
./list_songs --retirer "Artistes/X/(2004) Album"                  # cleanly remove an album
./list_songs --retirer "Artistes/X/(2004) Album/01 - Titre.flac"  # or a track
```

Environment variables: `RANGER_ROOT` (the `musics/` folder containing `Candidats` and the libraries), `RANGER_HOME`.

## Requirements

- Debian: `apt install beets python3-pil python3-mediafile python3-unidecode fonts-dejavu-core`
- beets configurations: see `exemples/` (Low-Res in `~/.config/beets`, Hi-Res in `~/.config/beets/hires`).
- Directory pages: copy `annuaire/` to `~/.config/beets/annuaire/`.
- Discogs (optional): personal token in `~/discog` (chmod 600) — **never commit it**.

## Removing a track or an album

`--retirer PATH…` removes cleanly: files (plus the cover / extra files if the album has no music left),
beets database entries and hash cache entries, folders left empty, then regenerates the directory pages.
The path can be relative to the library (`Artistes/…`), to `musics/` (`Musiques Hi-Res/Artistes/…`) or absolute;
if it exists in both libraries, the script asks you to be more specific. Lists and asks for confirmation
before deleting (`--oui` to skip the prompt, `--simulation` to only preview). Refuses paths that are too broad
(the whole `Artistes` folder, a library root). The database is backed up first.

## Full check

`--verification` rereads every file (without trusting the cache) and checks both libraries:
database entries whose file has disappeared (removed from the database, after a backup), audio files
missing from the database, identical files present several times (even under another name), albums without
a cover, leftovers from an interrupted run, stale cache entries. No music file is deleted or moved.
Report: `~/.config/beets/journal/verification_<date>.tsv`.

A log is written to `~/.config/beets/journal/ranger_<date>.log` and the beets database is backed up before each run.
