# list_songs

Automatically files the music dropped into `musics/Candidats/` into two libraries
(`musics/Musiques Low-Res` for MP3, `musics/Musiques Hi-Res` for FLAC/WAV/DSD/AIFF/WavPack/APE/ALAC),
using [beets](https://beets.io).

## What the script does

0. Extracts the archives dropped into `Candidats/` (`.zip`, `.rar` including multi-volume, `.7z`, `.tar`, `.tar.gz`…),
   each next to itself, then deletes the archive; archives inside archives are extracted too. An archive holding a
   single folder gives that folder; otherwise its content goes into a folder named after the archive.
   An unreadable or password-protected archive, or one whose target folder already exists, stays in place.
   If there is no archive, the script goes straight to the next step. `.zip` and `.tar` need nothing extra;
   `.rar` and `.7z` need `unrar`, `7z` or `unar` (see Requirements).
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
   in `musics/empreintes.db`.
5. `folder.jpg` cover: image already present (in the album folder of the library, the dropped folder,
   its parent or a `Scans`/`Artwork`/`Covers` subfolder) → embedded → Deezer → iTunes → Cover Art Archive
   → Discogs → generated. A present image named `cover`, `front`, `folder`, `jaquette`… wins over the embedded
   cover; an image with another name is used only if there is no embedded cover; `back`, `cd`, `booklet`… are ignored.
6. Regenerates a single directory page for both libraries: `musics/Annuaire.html` / `musics/Annuaire.csv`
   (filter by library, sort A–Z or by date added, download button next to each track).
   The search box also lists the matching tracks (title, with artist or album words to narrow it down);
   clicking one opens its album with the track highlighted.
   Date added: from beets, except for tracks of the initial import of a library (all on the same day), where the
   file date on disk is used; an album takes the date of its most recent track.
   Opened from the network share, the page also has foobar2000 buttons (play a track, play or add an album).
   Once per Windows PC, double-click `musics\foobar\Installer le lien foobar.cmd` (no admin rights;
   `Retirer le lien foobar.cmd` removes it). Downloading from the share: right-click ⬇ → "Save link as…".
   Subfolders: any depth is accepted (`Artist - Discography/Singles/Artist - 1996 - Title/`…).
   Subfolders without music (`Covers/`, `Scans/`…) follow their album, so their images are used as covers
   and then cleaned up. Several dropped folders of the same album with the same titles are editions, not CDs:
   they are filed separately, as `Album (EU)` / `Album (US)` (or `Album (édition 2)`).
7. Cleans up `Candidats/`: once an album is imported, its remaining files (images, `.cue`, `.nfo`…)
   are deleted. Anything that could not be imported (unsupported format, unreadable file) stays in place.

## Installing from scratch

On a fresh Debian or Ubuntu server:

```
sudo apt install -y git
git clone https://github.com/k-vanier/DEV.git ~/DEV
sudo ~/DEV/list_songs/installer.sh
```

`installer.sh` asks its questions first, shows a summary, then installs without stopping:

- where to create the music folder (it shows the free space per disk and proposes the folder already configured,
  the original server's folder or a data disk), and which account runs list_songs;
- if a beets database already exists there: keep it, or start from an empty one (the old one is saved in
  `.beets/journal/`); an old `~/.config/beets` can be taken over;
- Discogs token, Samba share (not on openmediavault: use its interface), HTTPS publishing (domain, external port).

It then installs the packages (beets, Pillow, mediafile, unidecode, DejaVu fonts, unar, 7-Zip), saves the chosen
folder in `/etc/list_songs.conf` (read by `list_songs`, `regenerer.sh` and `publier-https.sh`), creates `Candidats/`,
both libraries and `.beets/` with both beets configurations and two empty databases, installs the `list_songs` and
`annuaire-regenerer` commands in `/usr/local/bin` and builds the directory page. Then just drop music into
`Candidats/` and run `list_songs`.

With `--samba`, the share is `\<server IP>\musics`, user = the account, password = the Samba password typed during
the installation. Under WSL, the machine name is the Windows PC's own name, so use the IP address (`hostname -I`),
which changes when WSL restarts; in NAT mode only that PC can reach it. Run a single Samba at a time across WSL
distributions: they share the network, and two servers on port 445 answer connections at random.

Each successful step is recorded in `/var/lib/list_songs/` (with the answers, never the Discogs token). If a step
fails, the script says which one and how to resume: run it again and it offers to resume where it stopped, with the
same answers, skipping the validated steps, or to start over. Once an installation is finished, running it again
asks whether to redo it. `--reprendre` / `--recommencer` skip that question.

Every answer can also be given as an option (`--musics`, `--utilisateur`, `--base garder|vider`, `--discogs`,
`--samba`, `--domaine`, `--port-externe`); `--oui` asks nothing and uses the defaults. Nothing that already exists is
overwritten, so it can be run again. To restore from a backup, put the music folder back first, then run it.

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

The `musics/` folder comes from `/etc/list_songs.conf`; the `RANGER_ROOT` environment variable overrides it (`RANGER_HOME` too).

## Requirements

- Debian: `apt install beets python3-pil python3-mediafile python3-unidecode fonts-dejavu-core`
- Archives `.rar` / `.7z`: `apt install 7zip unar` (or `p7zip-full`; `unrar` from non-free also works).
- beets configurations: see `exemples/` (Low-Res in `musics/.beets/lowres/config.yaml`, Hi-Res in `musics/.beets/hires/config.yaml`).
- Discogs (optional): personal token in `~/discog` (chmod 600) — **never commit it**.

## Publishing the directory page over HTTPS

`sudo annuaire/publier-https.sh <domain> [external port]` serves `musics/` with nginx on port 8443, behind a password
and with a Let's Encrypt certificate (example: `sudo annuaire/publier-https.sh name.freeboxos.fr 8081`).
Beforehand, in the router: forward external port 80 to this server's port 8080 (needed by Let's Encrypt, keep it
for renewals) and the chosen external port to 8443. The script installs nginx, certbot and apache2-utils, asks for a
user name and password, refuses to run if 8080 or 8443 is used by another program, hides `.beets/`, `Candidats/` and
`*.db`, and sets up automatic renewal. It can be run again safely; add a user with
`sudo htpasswd -B /etc/nginx/annuaire.htpasswd <name>`.

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
Report: `musics/.beets/journal/verification_<date>.tsv`.

A log is written to `musics/.beets/journal/ranger_<date>.log` and the beets database is backed up before each run.

## Where things are, and what to back up

Everything needed to rebuild the libraries is in `musics/`, so backing up `musics/` is enough:

- the music and its `folder.jpg` covers;
- `musics/.beets/lowres/` and `musics/.beets/hires/`: beets configuration (`config.yaml`) and database (`library.db`).
  The script never writes tags (`-W`), so metadata it fills in from folder names and the dates added exist only there;
- `musics/.beets/journal/`: logs, and a copy of each database taken before each run.

Only the Discogs token `~/discog` stays outside `musics/`, since `musics/` is shared on the network: back it up separately.
`musics/empreintes.db`, `Annuaire.html`, `Annuaire.csv` and `musics/foobar/` are rebuilt automatically.

Older versions kept the beets folder in `~/.config/beets`. The first run moves it to `musics/.beets/` (fixing the paths
in both `config.yaml`) and renames the old folder `~/.config/beets.ancien-<date>`; delete it once everything works.
To run beets by hand: `BEETSDIR=musics/.beets/lowres beet ls …` (or `.beets/hires`).
To rebuild only the directory page: `annuaire/regenerer.sh`.
