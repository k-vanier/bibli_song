#!/usr/bin/python3
"""Range la musique déposée dans musics/Candidats vers les bibliothèques Low-Res et Hi-Res.

  1. aiguille les fichiers vers la bonne bibliothèque selon leur format
     (MP3 → Musiques Low-Res, sans perte → Musiques Hi-Res) ;
  2. indexe les fichiers avec beets (lecture des tags, sans les modifier) ;
  3. complète artiste/album/année/disque d'après les dossiers si les tags manquent,
     harmonise avec les artistes et albums déjà présents ;
  4. range en Artistes/<Artiste>/(Année) Album/ ou Compilations/(Année) Album/ ;
  5. pose un folder.jpg par album (jaquette déjà présente dans le dossier de l'album ou
     le dossier déposé, pochette intégrée, Deezer, iTunes, Cover Art Archive, Discogs, sinon pochette générée) ;
  6. régénère Annuaire.html et Annuaire.csv.

Pas de doublons : une piste déjà présente n'est pas ajoutée. Si son contenu est identique à un fichier
de la bibliothèque, elle est supprimée de Candidats ; sinon (même nom à destination, contenu différent),
elle est mise de côté dans Candidats/_déjà présents/. Jamais de « .1 » ; les fichiers de la bibliothèque
ne sont ni modifiés ni écrasés.
Une fois un album importé, ses fichiers restants dans Candidats (images, .cue, .nfo…) sont supprimés.
Ce qui n'a pas pu être importé (format non pris en charge, illisible) reste dans Candidats.

Usage :
  list_songs                  range tout ce qui est dans Candidats
  list_songs --simulation     montre ce qui serait fait, sans rien ranger
  list_songs --sans-internet  pas de recherche de pochette en ligne
"""
import argparse, colorsys, datetime, fcntl, hashlib, io, json, os, re, shutil, sqlite3, subprocess, sys
import tempfile, textwrap, threading, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, '/usr/share/beets')
from beets import config  # noqa: E402
from beets.library import Library  # noqa: E402
from mediafile import MediaFile  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from unidecode import unidecode  # noqa: E402

ROOT = os.environ.get('RANGER_ROOT', '/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/musics/')
HOME = os.environ.get('RANGER_HOME', os.path.expanduser('~'))
CANDIDATS = 'Candidats'
CAND = os.path.join(ROOT, CANDIDATS)
STAGE = os.path.join(CAND, '.en-cours')  # dossier de travail, un sous-dossier par bibliothèque
LIBS = {
    'low': dict(nom='Musiques Low-Res', dir=ROOT + 'Musiques Low-Res', beetsdir=HOME + '/.config/beets',
                stage=os.path.join(STAGE, 'low')),
    'hi': dict(nom='Musiques Hi-Res', dir=ROOT + 'Musiques Hi-Res', beetsdir=HOME + '/.config/beets/hires',
               stage=os.path.join(STAGE, 'hi')),
}
JOURNAL = HOME + '/.config/beets/journal'
EMPREINTES = ROOT + 'empreintes.db'  # cache des empreintes, rangé avec la musique
EMPREINTES_ANCIEN = HOME + '/.config/beets/empreintes.db'
ANNUAIRE = HOME + '/.config/beets/annuaire/annuaire.py'
DISCOGS_TOKEN = HOME + '/discog'
LOW_EXT = ('.mp3',)
HI_EXT = ('.flac', '.wav', '.aiff', '.aif', '.dsf', '.dff', '.wv', '.ape')
OTHER_LOSSY = ('.wma', '.ogg', '.opus', '.aac', '.mpc')
AUDIO_EXT = LOW_EXT + HI_EXT + OTHER_LOSSY + ('.m4a',)
UA = 'list_songs/1.0 (bibliotheque musicale personnelle)'
MINW = 500
DEJA = '_déjà présents'

LOT = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
LOGF = None


class Spinner:
    """Ligne animée en bas de l'écran (étape en cours + temps écoulé), seulement dans un terminal."""
    FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

    def __init__(self):
        self.on = sys.stderr.isatty()
        self.text = ''
        self.t0 = self.since = time.time()
        self.durations = []
        self.lock = threading.Lock()
        if self.on:
            threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        i = 0
        while True:
            with self.lock:
                if self.text:
                    e = int(time.time() - self.t0)
                    width = shutil.get_terminal_size().columns
                    line = f'{self.FRAMES[i % len(self.FRAMES)]} {self.text}  ({e // 60}:{e % 60:02d})'
                    sys.stderr.write('\r\033[K' + line[:width - 1]); sys.stderr.flush()
            i += 1
            time.sleep(0.1)

    def set(self, text):
        with self.lock:
            now = time.time()
            if self.text:
                self.durations.append((self.text, now - self.since))
            self.text, self.since = text, now
            if not text:
                self.clear()

    def clear(self):
        if self.on:
            sys.stderr.write('\r\033[K'); sys.stderr.flush()


SPIN = Spinner()


def say(*a):
    msg = ' '.join(str(x) for x in a)
    with SPIN.lock:
        SPIN.clear()
        print(msg, flush=True)
    if LOGF:
        LOGF.write(msg + '\n'); LOGF.flush()


# --------------------------------------------------------------------------- utilitaires

def norm(s):
    return re.sub(r'[^a-z0-9]', '', unidecode(re.sub(r'[\(\[].*?[\)\]]', '', s or '')).lower())


def same(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return a == b or (short in long_ and len(short) / len(long_) >= 0.6)


def beet(beetsdir, *args, capture=False):
    env = dict(os.environ, BEETSDIR=beetsdir, PYTHONPATH='/usr/share/beets')
    r = subprocess.run(['beet', *args], env=env, text=True,
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    return r.stdout if capture else r.returncode


def is_alac(path):
    try:
        return MediaFile(path).format == 'ALAC'
    except Exception:
        return False


def audio_files(top):
    for folder, dirs, files in os.walk(top):
        dirs[:] = [d for d in dirs if not d.startswith('_')]
        for f in files:
            if f.lower().endswith(AUDIO_EXT):
                yield os.path.join(folder, f)


# --------------------------------------------------------------------------- 1. aiguillage

def rows(db, query, args=()):
    """Lecture directe de la base beets (bien plus rapide que de charger toutes les pistes)."""
    con = sqlite3.connect(db)
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def lib_paths(db, exclude=()):
    """(id, chemin) de toutes les pistes de la base, sauf les id exclus."""
    return [(i, bytes(p)) for i, p in rows(db, 'select id, path from items') if i not in exclude]


class Empreintes:
    """Cache des empreintes BLAKE2 des fichiers (chemin, taille, date de modification → empreinte) :
    un fichier n'est relu que s'il est nouveau ou a changé."""

    def __init__(self, path):
        self.con = sqlite3.connect(path)
        self.con.execute('create table if not exists f (path blob primary key, size int, mtime int, hash text)')
        self.memo = {}

    @staticmethod
    def compute(p):
        h = hashlib.blake2b(digest_size=20)
        with open(p, 'rb') as fh:
            for chunk in iter(lambda: fh.read(4 << 20), b''):
                h.update(chunk)
        return h.hexdigest()

    def get(self, p, store=True, force=False):
        p = p if isinstance(p, bytes) else os.fsencode(p)
        if p in self.memo and not force:
            return self.memo[p]
        st = os.stat(p)
        row = self.con.execute('select size, mtime, hash from f where path = ?', (p,)).fetchone()
        if row and row[0] == st.st_size and row[1] == st.st_mtime_ns and not force:
            h = row[2]
        else:
            h = self.compute(p)
            if store:
                self.con.execute('insert or replace into f values (?, ?, ?, ?)', (p, st.st_size, st.st_mtime_ns, h))
        self.memo[p] = h
        return h

    def record(self, p, h):
        p = p if isinstance(p, bytes) else os.fsencode(p)
        st = os.stat(p)
        self.con.execute('insert or replace into f values (?, ?, ?, ?)', (p, st.st_size, st.st_mtime_ns, h))

    def commit(self):
        self.con.commit()


EMP = None


def hidden(rel):
    return any(seg.startswith(('_', '.')) for seg in rel.split(os.sep) if seg != '.')


def route():
    """Répartit le contenu de Candidats entre les dossiers de travail des deux bibliothèques, selon le format.
    Un dossier qui n'a plus d'audio emmène ses pochettes et fichiers annexes avec la musique."""
    moved, ignored = Counter(), []
    targets = defaultdict(Counter)
    for folder, dirs, files in os.walk(CAND, topdown=False):
        rel = os.path.relpath(folder, CAND)
        if hidden(rel):
            continue
        for f in sorted(files):
            p = os.path.join(folder, f)
            ext = os.path.splitext(f)[1].lower()
            if ext not in AUDIO_EXT:
                continue
            if ext in LOW_EXT:
                target = 'low'
            elif ext in HI_EXT or (ext == '.m4a' and is_alac(p)):
                target = 'hi'
            else:
                ignored.append(p); continue
            dst = os.path.join(LIBS[target]['stage'], rel, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(p, dst)
            moved[target] += 1; targets[folder][target] += 1
        for d in dirs:
            targets[folder].update(targets.get(os.path.join(folder, d), Counter()))
        if folder != CAND and targets[folder] and not any(f.lower().endswith(AUDIO_EXT) for f in os.listdir(folder)):
            dst_dir = os.path.join(LIBS[targets[folder].most_common(1)[0][0]]['stage'], rel)
            for f in os.listdir(folder):
                p = os.path.join(folder, f)
                if os.path.isfile(p):
                    move_new(p, os.path.join(dst_dir, f))
                elif os.path.isdir(p) and not targets.get(p) and not f.startswith(('_', '.')) and next(audio_files(p), None) is None:
                    # sous-dossier sans musique (Covers, Scans…) : il suit l'album
                    for sub, _, fs in os.walk(p):
                        for ff in fs:
                            move_new(os.path.join(sub, ff), os.path.join(dst_dir, f, os.path.relpath(sub, p), ff))
    return moved, ignored


def move_new(src, dst):
    """Déplace src vers dst, sauf si dst existe déjà (src reste alors en place)."""
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)


def restore_stage():
    """Remet dans Candidats ce qui reste dans le dossier de travail (non audio, illisibles, simulation,
    lancement interrompu). Renvoie les fichiers qui n'ont pas pu revenir (même nom déjà présent)."""
    kept = []
    for lib in LIBS.values():
        st = lib['stage']
        for folder, dirs, files in os.walk(st, topdown=False):
            for f in files:
                src = os.path.join(folder, f)
                dst = os.path.join(CAND, os.path.relpath(src, st))
                if os.path.exists(dst):
                    kept.append(src); continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
            if not os.listdir(folder):
                os.rmdir(folder)
    if os.path.isdir(STAGE) and not os.listdir(STAGE):
        os.rmdir(STAGE)
    return kept


def discard(src, cand, other):
    """Piste déjà présente : supprimée si son contenu est identique à « other » (fichier déjà rangé),
    sinon mise de côté. Renvoie True si elle a été supprimée."""
    try:
        if other and os.path.isfile(other) and os.path.getsize(src) == os.path.getsize(other) \
                and EMP.get(src, store=False) == EMP.get(other):
            os.remove(src)
            return True
    except OSError:
        pass
    set_aside(src, cand)
    return False


def purge_imported(cand):
    """Supprime les fichiers restants (images, .cue, .nfo…) des dossiers dont toute la musique a été importée.
    Un dossier qui contient encore de l'audio (non importé) est laissé tel quel, avec ses fichiers annexes."""
    n = 0
    for folder, dirs, files in os.walk(cand, topdown=False):
        if folder == cand or any(f.lower().endswith(AUDIO_EXT) for _, _, fs in os.walk(folder) for f in fs):
            continue
        for f in files:
            os.remove(os.path.join(folder, f)); n += 1
        if not os.listdir(folder):
            os.rmdir(folder)
    return n


def set_aside(src, cand):
    """Met de côté un fichier déjà présent dans la bibliothèque, sans le renommer."""
    rel = os.path.relpath(src, cand)
    dst = os.path.join(CAND, DEJA, rel)
    if os.path.exists(dst):
        dst = os.path.join(CAND, DEJA, LOT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)


# --------------------------------------------------------------------------- 3. métadonnées

YEAR = re.compile(r'(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)')
DISCSEG = re.compile(r'^(?:.*[\[\(_ -])?(?:cd|disc|disk|disque)[\s_-]*(\d+)\b[^/]*$', re.I)
DISCALB = re.compile(r'^(.*?)[\s,_-]*[\[\(]?\b(?:cd|disc|disk)\s*(\d+)\b[^\]\)]*[\]\)]?\s*$', re.I)
FEAT = re.compile(r'\s+(?:feat\.?|ft\.?|featuring|avec)\s+.*$', re.I)
VA = re.compile(r'^(various( artists)?|va|v\.a\.|artistes divers|multi[- ]interpr[eè]tes|compilation)$', re.I)
PAYS = r'EU|UE|US|USA|UK|GER|DE|FR|JP|JPN|CAN|CA|AUS|NL|IT|ES|BR|KR|RU|SWE|INT'
EDITION = re.compile(rf'[\[\(,]\s*({PAYS})\s*[,\]\)]')


def clean_dirname(s):
    s = re.sub(r'\[[^\]]*\]|\{[^}]*\}', '', s)
    s = re.sub(r'\((?:[^)]*(?:\bcd\b|flac|mp3|kbps|bit|khz|web|vinyl|vinyle|limited|edition|remaster|\d{3,})[^)]*)\)', '', s, flags=re.I)
    s = re.sub(r'^\s*(?:19|20)\d\d\s*[\.\-_]?\s*-?\s*', '', s)
    s = re.sub(r'[-_ ]+(?:FLAC|MP3|WEB|320|16BIT|24BIT)\b.*$', '', s, flags=re.I)
    return re.sub(r'\s+', ' ', s.replace('_', ' ')).strip(' -.,')


def from_path(origdir):
    """Déduit (artiste, album, année, disque, compilation) du chemin dans Candidats."""
    segs = [s for s in origdir.split('/') if s and s != '.']
    disc = 0
    if len(segs) > 1 and DISCSEG.match(segs[-1]):
        disc = int(DISCSEG.match(segs[-1]).group(1)); segs = segs[:-1]
    if not segs:
        return '', 'Titres divers', 0, disc, False
    yr = 0
    for s in reversed(segs):
        y = YEAR.search(s)
        if y:
            yr = int(y.group(1)); break
    comp = any(re.search(r'\b(va|various|compil)', s, re.I) for s in segs[:1])
    if len(segs) == 1:
        artist, _, album = segs[0].partition(' - ')
        if not album:
            artist, album = '', segs[0]
    else:
        artist, album = segs[0], segs[-1]
        artist = re.split(r'\s+-\s+(?:discograph|discografia|integrale|intégrale)', artist, flags=re.I)[0]
    a2, sep, rest = album.partition(' - ')
    if sep and len(segs) > 1 and same(clean_dirname(a2), clean_dirname(artist)):
        album = rest  # « Artiste - 2001 - Album » rangé dans le dossier de l'artiste
    album = clean_dirname(album) or clean_dirname(segs[-1]) or 'Titres divers'
    artist = clean_dirname(artist)
    if comp or VA.match(artist or ''):
        return 'Various Artists', album, yr, disc, True
    return artist, album, yr, disc, False


def editions(its, ods):
    """Plusieurs dossiers déposés pour un même album : s'ils reprennent les mêmes titres, ce sont des éditions
    (EU, US…) et non des CD d'un coffret. Renvoie {dossier: suffixe d'album}, vide si ce ne sont pas des éditions."""
    titles = {o: {norm(i.title) for i in its if i['origdir'] == o and i.title} for o in ods}
    shared = any(len(titles[a] & titles[b]) > 0.5 * min(len(titles[a]), len(titles[b]))
                 for k, a in enumerate(ods) for b in ods[k + 1:] if titles[a] and titles[b])
    if not shared:
        return {}
    # les CD d'une même édition (Album (EU)/CD1, CD2) restent ensemble
    base = {o: os.path.dirname(o) if DISCSEG.match(os.path.basename(o)) else o for o in ods}
    groups = sorted(set(base.values()))
    if len(groups) < 2:
        return {}
    pays = {g: (EDITION.search(os.path.basename(g)) or [None, None])[1] for g in groups}
    if all(pays.values()) and len(set(pays.values())) == len(groups):
        lab = {g: f' ({pays[g].upper()})' for g in groups}
    else:
        lab = {g: '' if k == 0 else f' (édition {k + 1})' for k, g in enumerate(groups)}
    return {o: lab[base[o]] for o in ods}


def lot(lib, ids):
    """Pistes du lot courant, par leur id (une requête beets sur l'attribut « lot » parcourt toute la base)."""
    return [it for it in (lib.get_item(i) for i in sorted(ids)) if it is not None]


class Old:
    def __init__(self, albumartist, album, year):
        self.albumartist, self.album, self.year = albumartist or '', album or '', year or 0


def fix_metadata(lib, db, ids, cand_dir):
    """Complète et harmonise les métadonnées des pistes du lot courant (dans la base seulement)."""
    batch = lot(lib, ids)
    if not batch:
        return 0
    old = [Old(*r[1:]) for r in rows(db, 'select id, albumartist, album, year from items') if r[0] not in ids]
    known_artists = {}
    for i in old:
        if i.albumartist:
            known_artists.setdefault(norm(i.albumartist), Counter())[i.albumartist] += 1
    known_artists = {k: c.most_common(1)[0][0] for k, c in known_artists.items()}
    known_albums = {}
    for i in old:
        known_albums.setdefault((norm(i.albumartist), i.album.lower().strip()), (i.album, i.year))

    def canon_artist(a):
        a = (a or '').strip()
        if VA.match(a):
            return 'Various Artists'
        if norm(a) in known_artists:
            return known_artists[norm(a)]
        b = FEAT.sub('', a)
        for sep in (' & ', ' vs. ', ' vs ', ' x ', ', ', ' and ', ' et ', '/'):
            first = b.split(sep)[0]
            if norm(first) in known_artists:
                return known_artists[norm(first)]
        return known_artists.get(norm(b), b)

    for it in batch:
        od = os.path.relpath(os.path.dirname(it.path.decode('utf-8', 'replace')), cand_dir)
        it['origdir'] = od
        if it.year and it.year < 1900:
            it.year = 0
        if not (it.artist and it.title and it.album):
            artist, album, yr, disc, comp = from_path(od)
            if not it.artist and artist:
                it.artist = artist
            it.album = it.album or album
            it.albumartist = it.albumartist or artist or it.artist
            it.year = it.year or yr
            if disc:
                it.disc = disc
            if comp:
                it.albumartist = 'Various Artists'
        if not it.album:
            it.album = 'Titres divers'
        m = DISCALB.match(it.album)
        if m and len(m.group(1).strip()) > 2:
            it.album = m.group(1).strip(' -_,([:'); it.disc = int(m.group(2))
        m = re.match(r'^\s*((?:19|20)\d\d)\s*[-.]\s*(.+)$', it.album)
        if m:
            it.album = m.group(2).strip(); it.year = it.year or int(m.group(1))
        it.albumartist = canon_artist(it.albumartist or it.artist)
        if not it.albumartist:
            it.albumartist = 'Artiste inconnu'
        va = it.albumartist == 'Various Artists' or bool(it.comp)
        it.comp = va; it['va'] = 1 if va else 0; it['atrier'] = 0
        k = (norm(it.albumartist), it.album.lower().strip())
        if k in known_albums:
            it.album, y = known_albums[k]; it.year = y or it.year
        it.store()

    # année, nombre de disques et disques déduits des sous-dossiers, par album
    grp = defaultdict(list)
    for it in lot(lib, ids):
        grp[(it.albumartist, it.album.lower())].append(it)
    for its in grp.values():
        yrs = Counter(i.year for i in its if i.year)
        yr = yrs.most_common(1)[0][0] if yrs else 0
        names = Counter(i.album for i in its)
        name = max(names, key=lambda x: (x != x.lower(), x != x.upper(), names[x]))
        ods = sorted({i['origdir'] for i in its})
        eds = editions(its, ods) if len(ods) > 1 else {}
        if not eds and len(ods) > 1 and len({os.path.dirname(o) for o in ods}) == 1 and len({i.disc for i in its}) < len(ods):
            for i in its:
                i.disc = ods.index(i['origdir']) + 1
        dt = max([i.disc or 1 for i in its])
        for i in its:
            i.year, i.album = yr, name + eds.get(i['origdir'], '')
            if dt > 1:
                i.disctotal = dt
            i.store()

    # cohérence des albums beets avec leurs pistes (un album beets = un dossier déposé)
    for aid in {i.album_id for i in lot(lib, ids) if i.album_id}:
        a = lib.get_album(aid)
        if a is None:
            continue
        its = list(a.items())
        sub = defaultdict(list)
        for i in its:
            sub[(i.albumartist, i.album, i.year)].append(i)
        first = True
        for (aa, al, yr), l in sub.items():
            tgt = a if first else lib.add_album(l)
            first = False
            tgt.albumartist, tgt.album, tgt.year, tgt.comp = aa, al, yr, l[0].comp
            tgt.disctotal = max(i.disctotal or 1 for i in l)
            tgt.store()

    # entrées pointant vers un fichier déjà référencé (liens physiques) : on garde la première
    seen = {}
    for iid, path in sorted(lib_paths(db), key=lambda r: r[0] in ids):
        try:
            st = os.stat(path)
        except FileNotFoundError:
            continue
        k = (st.st_dev, st.st_ino)
        if k in seen and iid in ids:
            lib.get_item(iid).remove(delete=False, with_album=True); ids.discard(iid)
        else:
            seen.setdefault(k, iid)
    return len(batch)


# --------------------------------------------------------------------------- 5. pochettes

def http(url, as_json=True, headers=None, pause=0):
    if pause:
        time.sleep(pause)
    h = {'User-Agent': UA, **(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return json.load(r) if as_json else r.read()


def save_cover(data, folder, source, minw=MINW):
    try:
        im = Image.open(io.BytesIO(data)); im.load()
    except Exception:
        return False
    w, h = im.size
    if min(w, h) < minw or abs(w - h) > 0.12 * max(w, h):
        return False
    out = os.path.join(folder, 'folder.jpg')
    if not os.path.exists(out):
        (im.convert('RGB') if im.mode not in ('RGB', 'L') else im).save(out, 'JPEG', quality=92)
        say(f'    pochette ({source}, {w}×{h}) : {folder}')
    return True


def cover_embedded(folder):
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(AUDIO_EXT):
            continue
        try:
            imgs = MediaFile(os.path.join(folder, f)).images
        except Exception:
            continue
        for im in imgs or []:
            if save_cover(im.data, folder, 'intégrée'):
                return True
    return False


IMG_EXT = ('.jpg', '.jpeg', '.png', '.webp')
SCANS = ('scans', 'scan', 'artwork', 'artworks', 'covers', 'cover', 'pochette', 'pochettes', 'images')


def local_images(folder, srcdirs):
    """Images de jaquette déjà présentes : dans le dossier de l'album (bibliothèque), dans le dossier déposé,
    son parent et leurs sous-dossiers de scans. Renvoie (score, taille, chemin) ;
    score 2 = nom de face avant (folder, cover, front…), 1 = nom quelconque ; les dos, CD, livrets… sont écartés."""
    prio, bad = ('folder', 'cover', 'front', 'albumart', 'pochette', 'jaquette', 'recto'), \
        ('back', 'cd', 'disc', 'booklet', 'inlay', 'inside', 'tray', 'verso', 'dos', 'label', 'livret')
    dirs = [folder]
    for d in srcdirs:
        dirs += [d, os.path.dirname(d)]
    for d in list(dirs):
        if os.path.isdir(d):
            dirs += [os.path.join(d, s) for s in os.listdir(d) if s.lower() in SCANS]
    cands, seen = [], set()
    for dd in dirs:
        if not os.path.isdir(dd) or os.path.realpath(dd) in seen:
            continue
        seen.add(os.path.realpath(dd))
        for f in os.listdir(dd):
            fl = f.lower()
            p = os.path.join(dd, f)
            if fl.endswith(IMG_EXT) and fl != 'folder.jpg' and os.path.isfile(p):
                score = 2 if fl.startswith(prio) else (0 if any(x in fl for x in bad) else 1)
                if score:
                    cands.append((score, os.path.getsize(p), p))
    return sorted(cands, reverse=True)


def cover_local(folder, cands, source):
    for _, _, p in cands:
        try:
            with open(p, 'rb') as fh:
                if save_cover(fh.read(), folder, f'{source} : {os.path.basename(p)}'):
                    return True
        except OSError:
            continue
    return False


def cover_online(folder, artist, album, token):
    a = '' if artist == 'Various Artists' else artist
    tries = []

    def deezer():
        q = f'artist:"{a}" album:"{album}"' if a else f'album:"{album}"'
        for r in http('https://api.deezer.com/search/album?limit=10&q=' + urllib.parse.quote(q)).get('data', []):
            if same(album, r.get('title')) and (not a or same(a, r.get('artist', {}).get('name'))):
                return r.get('cover_xl')

    def itunes():
        q = urllib.parse.quote(f'{a} {album}'.strip())
        for r in http(f'https://itunes.apple.com/search?term={q}&entity=album&limit=10&country=FR').get('results', []):
            if same(album, r.get('collectionName')) and (not a or same(a, r.get('artistName'))):
                return r.get('artworkUrl100', '').replace('100x100bb', '1200x1200bb')

    def caa():
        q = f'release:"{album}"' + (f' AND artist:"{a}"' if a else '')
        for r in http('https://musicbrainz.org/ws/2/release/?fmt=json&limit=10&query=' + urllib.parse.quote(q), pause=1.1).get('releases', []):
            ra = ' '.join(c.get('name', '') for c in r.get('artist-credit', []))
            if same(album, r.get('title')) and (not a or same(a, ra)):
                return f'https://coverartarchive.org/release/{r["id"]}/front-1200'

    def discogs():
        params = {'release_title': album, 'per_page': 10, 'type': 'master'}
        if a:
            params['artist'] = a
        hdr = {'Authorization': f'Discogs token={token}'}
        for typ in ('master', 'release'):
            params['type'] = typ
            for r in http('https://api.discogs.com/database/search?' + urllib.parse.urlencode(params), headers=hdr, pause=1.1).get('results', []):
                ra, _, t = r.get('title', '').partition(' - ')
                img = r.get('cover_image', '')
                if same(album, t or ra) and (not a or same(a, ra)) and img and 'spacer.gif' not in img:
                    return img

    tries = [('Deezer', deezer), ('iTunes', itunes), ('Cover Art Archive', caa)]
    if token:
        tries.append(('Discogs', discogs))
    for name, fn in tries:
        try:
            url = fn()
            if url and save_cover(http(url, as_json=False), folder, name):
                return True
        except Exception:
            continue
    return False


def cover_generated(folder, artist, album, year):
    h = int(hashlib.md5(f'{artist}/{album}'.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    bg = tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, 0.28, 0.45))
    ac = tuple(int(c * 255) for c in colorsys.hls_to_rgb(h, 0.40, 0.50))
    font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    fontb = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    im = Image.new('RGB', (1000, 1000), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([60, 60, 940, 940], outline=ac, width=6)

    def fit(text, path, start, mn, chars):
        size = start
        while size >= mn:
            f = ImageFont.truetype(path, size)
            lines = textwrap.wrap(text, width=max(8, int(chars * start / size)))[:4]
            if all(d.textlength(l, font=f) <= 780 for l in lines):
                return f, lines
            size -= 4
        return ImageFont.truetype(path, mn), textwrap.wrap(text, width=int(chars * start / mn))[:4]

    fr, lr = fit('Compilation' if artist == 'Various Artists' else artist, font, 60, 32, 24)
    fa, la = fit(album, fontb, 92, 40, 16)
    y = 230
    for l in lr:
        d.text((110, y), l, font=fr, fill=(235, 235, 235)); y += fr.size + 14
    d.line([110, y + 20, 330, y + 20], fill=ac, width=6); y += 70
    for l in la:
        d.text((110, y), l, font=fa, fill=(255, 255, 255)); y += fa.size + 16
    if year:
        d.text((110, 830), str(year), font=ImageFont.truetype(font, 48), fill=(200, 200, 200))
    im.save(os.path.join(folder, 'folder.jpg'), 'JPEG', quality=90)
    say(f'    pochette (générée) : {folder}')


def covers(lib, ids, cand_dir, internet):
    token = open(DISCOGS_TOKEN).read().strip() if internet and os.path.exists(DISCOGS_TOKEN) else ''
    folders = defaultdict(set)
    info = {}
    for it in lot(lib, ids):
        f = os.path.dirname(it.path.decode('utf-8', 'replace'))
        folders[f].add(os.path.join(cand_dir, it.get('origdir') or ''))
        info[f] = (it.albumartist, it.album, it.year)
    stats = Counter()
    for k, (f, srcs) in enumerate(sorted(folders.items()), 1):
        SPIN.set(f'Pochettes {k}/{len(folders)} : {os.path.basename(f)}')
        if os.path.exists(os.path.join(f, 'folder.jpg')) or not os.path.isdir(f):
            continue
        aa, al, yr = info[f]
        # une jaquette déjà présente (nommée cover, front…) passe avant la pochette intégrée,
        # souvent plus petite ; une image au nom quelconque ne vient qu'après
        imgs = local_images(f, srcs)
        if cover_local(f, [c for c in imgs if c[0] == 2], 'image présente'):
            stats['image présente'] += 1
        elif cover_embedded(f):
            stats['intégrée'] += 1
        elif cover_local(f, [c for c in imgs if c[0] == 1], 'image présente'):
            stats['image présente'] += 1
        elif internet and cover_online(f, aa, re.sub(rf'\s*\((?:{PAYS}|édition \d+)\)', '', al), token):
            stats['internet'] += 1
        else:
            cover_generated(f, aa, al, yr); stats['générée'] += 1
    return stats


# --------------------------------------------------------------------------- traitement d'une bibliothèque

def process(key, args):
    lib_cfg = LIBS[key]
    cand = lib_cfg['stage']
    SPIN.set(f'{lib_cfg["nom"]} : recherche des fichiers dans {CANDIDATS}/')
    tops = [os.path.join(cand, e) for e in sorted(os.listdir(cand)) if not e.startswith('_')] if os.path.isdir(cand) else []
    files = [p for p in audio_files(cand)
             if p.lower().endswith(LOW_EXT if key == 'low' else HI_EXT + ('.m4a',))]
    say(f'\n=== {lib_cfg["nom"]} : {len(files)} fichier(s) audio dans {CANDIDATS}/')
    if not files:
        return None
    beetsdir = lib_cfg['beetsdir']
    tmp = None
    if args.simulation:
        tmp = tempfile.mkdtemp(prefix='ranger-sim-')
        cfg = open(os.path.join(beetsdir, 'config.yaml')).read()
        shutil.copy(os.path.join(beetsdir, 'library.db'), os.path.join(tmp, 'library.db'))
        cfg = re.sub(r'(?m)^library: .*$', f'library: {tmp}/library.db', cfg)
        cfg = re.sub(r'(?m)^  log: .*$', f'  log: {tmp}/import.log', cfg)
        open(os.path.join(tmp, 'config.yaml'), 'w').write(cfg)
        beetsdir = tmp
    else:
        shutil.copy(os.path.join(beetsdir, 'library.db'), f'{JOURNAL}/{key}_library_avant_{LOT}.db')
        # entrées laissées par un lancement interrompu (fichiers revenus depuis dans Candidats)
        stale = [i for i, p in lib_paths(os.path.join(beetsdir, 'library.db')) if p.startswith(os.fsencode(STAGE + '/'))]
        if stale:
            old = Library(os.path.join(beetsdir, 'library.db'))
            for i in stale:
                old.get_item(i).remove(delete=False, with_album=True)

    SPIN.set(f'{lib_cfg["nom"]} : indexation de {len(files)} fichier(s) par beets')
    out = beet(beetsdir, 'import', '-q', '-A', '-C', '-W', '--set', f'lot={LOT}', *tops, capture=True)
    unreadable = [l.split('unreadable file: ', 1)[1] for l in out.splitlines() if 'unreadable file: ' in l]
    config.clear(); config.read()
    db = os.path.join(beetsdir, 'library.db')
    lib = Library(db)
    ids = {i for i, p in lib_paths(db) if p.startswith(os.fsencode(cand + '/'))}
    # formats qui n'appartiennent pas à cette bibliothèque (ne devrait pas arriver après l'aiguillage)
    for it in lot(lib, ids):
        ext = os.path.splitext(it.path.decode('utf-8', 'replace'))[1].lower()
        if (key == 'low') != (ext in LOW_EXT):
            it.remove(delete=False, with_album=True); ids.discard(it.id)
    # déjà présent : contenu identique à un fichier de la bibliothèque, ou au même fichier déposé deux fois.
    # Fait avant la complétion des métadonnées, pour que les copies écartées ne comptent pas comme des CD.
    SPIN.set(f'{lib_cfg["nom"]} : recherche des musiques déjà présentes')
    # seuls les fichiers de même taille sont comparés, par empreinte (gardée en cache pour la bibliothèque)
    by_size = defaultdict(list)
    for _, p in lib_paths(db, exclude=ids):
        try:
            by_size[os.path.getsize(p)].append(p)
        except OSError:
            pass
    deja, batch_size, new_hash = [], defaultdict(list), {}
    for it in lot(lib, ids):
        src = it.path.decode('utf-8', 'replace')
        size = os.path.getsize(src)
        if by_size.get(size) or batch_size.get(size):
            h = new_hash[src] = EMP.get(src, store=False)
            other = next((o for o in by_size.get(size, []) if EMP.get(o) == h), None)
            if other:
                other = other.decode('utf-8', 'replace')
                deja.append((it, src, os.path.relpath(os.path.dirname(other), lib_cfg['dir']), other))
                continue
            twin = next((o for o in batch_size[size] if EMP.get(o, store=False) == h), None)
            if twin:
                deja.append((it, src, os.path.join(CANDIDATS, os.path.relpath(os.path.dirname(twin), cand)), twin))
                continue
        batch_size[size].append(src)
    EMP.commit()
    for it, src, *_ in deja:
        it.remove(delete=False, with_album=True); ids.discard(it.id)

    SPIN.set(f'{lib_cfg["nom"]} : complétion des métadonnées')
    n = fix_metadata(lib, db, ids, cand)
    say(f'  {n + len(deja)} piste(s) indexée(s), {len(unreadable)} illisible(s) par beets')

    SPIN.set(f'{lib_cfg["nom"]} : calcul des nouveaux emplacements')
    preview = beet(beetsdir, 'move', '-p', f'path:{cand}', capture=True)
    lines = [re.sub(r'\x1b\[[0-9;]*m', '', l) for l in preview.splitlines()]
    dest_of = {lines[i - 1].rstrip(): l.split(' -> ', 1)[1].strip()
               for i, l in enumerate(lines) if l.startswith('  -> ') and i > 0}

    # même nom de fichier déjà à destination : on n'ajoute rien, jamais de .1 / .2
    taken = set()
    for it in lot(lib, ids):
        src = it.path.decode('utf-8', 'replace')
        dest = dest_of.get(src, src)
        if os.path.exists(dest) or dest in taken:
            deja.append((it, src, os.path.relpath(os.path.dirname(dest), lib_cfg['dir']), dest if os.path.exists(dest) else None))
            dest_of.pop(src, None)
            it.remove(delete=False, with_album=True); ids.discard(it.id)
        else:
            taken.add(dest)
    for a, c in sorted(Counter(d for _, _, d, _ in deja).items()):
        say(f'  déjà présent, non ajouté : {a}  ({c} piste{"s" if c > 1 else ""})')
    # les copies d'un fichier du même lot ne sont traitées qu'après le déplacement de l'original
    twins = [d for d in deja if d[3] and d[3].startswith(cand + '/')]
    deja_lib = [d for d in deja if d not in twins]
    supprimes = 0
    if not args.simulation:
        for _, src, _, other in deja_lib:
            supprimes += discard(src, cand, other)

    albums = Counter(os.path.relpath(os.path.dirname(d), lib_cfg['dir']) for d in dest_of.values())
    for a, c in sorted(albums.items()):
        say(f'  → {a}  ({c} piste{"s" if c > 1 else ""})')
    if args.simulation:
        shutil.rmtree(tmp, ignore_errors=True)
        return dict(pistes=len(dest_of), albums=len(albums), illisibles=len(unreadable), deja=len(deja))

    before = {i.id: i.path for i in lot(lib, ids)}
    SPIN.set(f'{lib_cfg["nom"]} : déplacement des fichiers')
    beet(beetsdir, 'move', f'path:{cand}', capture=True)
    lib = Library(db)
    moved_items = lot(lib, ids)
    albums = Counter(os.path.relpath(os.path.dirname(i.path.decode('utf-8', 'replace')), lib_cfg['dir'])
                     for i in moved_items)
    new_path = {}
    with open(f'{JOURNAL}/ranger_{LOT}_{key}.tsv', 'w', encoding='utf-8') as j:
        for it in moved_items:
            old_p, new_p = before.get(it.id, b'').decode('utf-8', 'replace'), it.path.decode('utf-8', 'replace')
            j.write(f"{old_p}\t{new_p}\n")
            new_path[old_p] = new_p
            if old_p in new_hash and os.path.exists(new_p):
                EMP.record(new_p, new_hash[old_p])  # empreinte déjà calculée : on la garde pour la suite
    EMP.commit()
    for _, src, _, twin in twins:
        supprimes += discard(src, cand, new_path.get(twin))

    # fichiers illisibles : placés à côté de leurs pistes sœurs
    by_od = {}
    for it in moved_items:
        by_od.setdefault(it.get('origdir'), os.path.dirname(it.path.decode('utf-8', 'replace')))
    lib_inodes = set()
    for _, p in lib_paths(db):
        try:
            lib_inodes.add(os.stat(p).st_ino)
        except FileNotFoundError:
            pass
    SPIN.set(f'{lib_cfg["nom"]} : fichiers illisibles')
    left = []
    for p in audio_files(cand):
        if not p.lower().endswith(LOW_EXT if key == 'low' else HI_EXT + ('.m4a',)):
            continue
        if os.stat(p).st_ino in lib_inodes:
            continue  # second nom d'un fichier déjà rangé (lien physique)
        dest_dir = by_od.get(os.path.relpath(os.path.dirname(p), cand))
        dest = os.path.join(dest_dir, os.path.basename(p)) if dest_dir else None
        if dest and os.path.exists(dest):
            supprimes += discard(p, cand, dest); deja.append((None, p, os.path.relpath(dest_dir, lib_cfg['dir']), dest))
        elif dest:
            shutil.move(p, dest)
            say(f'  illisible placé avec son album : {dest}')
        else:
            left.append(os.path.join(CAND, os.path.relpath(p, cand)))
    stats = covers(lib, ids, cand, not args.sans_internet) if not args.sans_pochettes else Counter()
    SPIN.set(f'{lib_cfg["nom"]} : suppression des fichiers importés dans {CANDIDATS}/')
    annexes = purge_imported(cand)  # après les pochettes, qui peuvent venir des images déposées
    SPIN.set(f'{lib_cfg["nom"]} : nettoyage des dossiers vides')
    # nettoyage : dossiers devenus vides dans la bibliothèque
    for folder, dirs, fs in os.walk(lib_cfg['dir'], topdown=False):
        if folder != lib_cfg['dir'] and not os.listdir(folder):
            os.rmdir(folder)
    return dict(pistes=sum(albums.values()), albums=len(albums), illisibles=len(unreadable), restants=left, pochettes=stats,
                deja=len(deja), supprimes=supprimes, annexes=annexes)


def build_hashes(force=False, extra=()):
    """Empreinte de chaque fichier des bibliothèques (et des fichiers de « extra »).
    force=True : tout est relu, sans se fier au cache. Renvoie {chemin: empreinte}."""
    paths = [p for lib in LIBS.values() for _, p in lib_paths(lib['beetsdir'] + '/library.db')]
    paths += [os.fsencode(p) for p in extra]
    todo, sizes = [], {}
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            continue
        sizes[p] = st.st_size
        row = None if force else EMP.con.execute('select size, mtime from f where path = ?', (p,)).fetchone()
        if not (row and row[0] == st.st_size and row[1] == st.st_mtime_ns):
            todo.append(p)
    total = sum(sizes[p] for p in todo) or 1
    t0, read = time.time(), 0
    for k, p in enumerate(todo, 1):
        el = time.time() - t0
        rest = el / read * (total - read) if read else 0
        SPIN.set(f'Empreintes {k}/{len(todo)} ({read / 1e9:.0f}/{total / 1e9:.0f} Go)'
                 + (f', reste ~{int(rest) // 3600} h {int(rest) % 3600 // 60:02d}' if read else ''))
        try:
            EMP.get(p, force=True)
        except OSError:
            continue
        read += sizes[p]
        if k % 100 == 0:
            EMP.commit()
    EMP.commit()
    SPIN.set('')
    say(f'  {len(todo)} empreinte(s) calculée(s) ({read / 1e9:.1f} Go lus), {len(sizes)} fichier(s) au total')
    return {p: EMP.get(p) for p in sizes}


def regen_annuaires(keys):
    if not os.path.exists(ANNUAIRE):
        return
    say('\n--- Mise à jour des annuaires')
    for k in keys:
        lib = LIBS[k]
        SPIN.set(f'Annuaire {lib["nom"]}')
        r = subprocess.run([sys.executable, ANNUAIRE, lib['dir'], lib['beetsdir'] + '/library.db', lib['nom']],
                           env=dict(os.environ, PYTHONPATH='/usr/share/beets'), text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for l in r.stdout.splitlines():
            say('  ' + l)
    SPIN.set('')


def resolve(arg):
    """Chemin donné par l'utilisateur → (bibliothèque, chemin absolu). Accepte un chemin absolu, relatif à
    musics/ (« Musiques Hi-Res/Artistes/… ») ou relatif à une bibliothèque (« Artistes/… »)."""
    arg = arg.rstrip('/')
    tries = [arg] if os.path.isabs(arg) else [os.path.join(ROOT, arg)] + [os.path.join(l['dir'], arg) for l in LIBS.values()]
    found = {}
    for p in tries:
        p = os.path.normpath(p)
        for k, lib in LIBS.items():
            rel = os.path.relpath(p, lib['dir'])
            if not rel.startswith('..') and os.path.exists(p):
                parts = rel.split(os.sep)
                if rel == '.' or len(parts) < 2 or parts[0] not in ('Artistes', 'Compilations', 'À trier'):
                    sys.exit(f'Refusé, trop large : {p}\n(il faut au moins un artiste ou un album, '
                             f'par exemple « Artistes/<Artiste> » ou « Compilations/<Album> »)')
                found[p] = k
    if not found:
        sys.exit(f'Introuvable dans les bibliothèques : {arg}')
    if len(found) > 1:
        sys.exit(f'« {arg} » existe dans les deux bibliothèques, précisez laquelle :\n'
                 + '\n'.join(f'  {os.path.relpath(p, ROOT)}' for p in found))
    (p, k), = found.items()
    return k, p


def retirer(args):
    """Supprime proprement des morceaux ou des albums : fichiers, entrées de la base et du cache, annuaire."""
    targets = [resolve(a) for a in args.retirer]
    plan = defaultdict(lambda: {'audio': [], 'autres': [], 'ids': []})
    for k, p in targets:
        files = [p] if os.path.isfile(p) else [os.path.join(f, x) for f, _, xs in os.walk(p) for x in xs]
        audio = [f for f in files if f.lower().endswith(AUDIO_EXT)]
        others = [f for f in files if f not in audio]
        # un dossier d'album qui n'aurait plus de musique : on retire aussi sa pochette et ses fichiers annexes
        for d in {os.path.dirname(f) for f in audio}:
            rest = [x for x in os.listdir(d) if os.path.join(d, x) not in audio]
            if not any(x.lower().endswith(AUDIO_EXT) for x in rest) and not any(os.path.isdir(os.path.join(d, x)) for x in rest):
                others += [os.path.join(d, x) for x in rest if os.path.join(d, x) not in others]
        pref = os.fsencode(p)
        ids = [i for i, q in lib_paths(LIBS[k]['beetsdir'] + '/library.db') if q == pref or q.startswith(pref + b'/')]
        plan[k]['audio'] += audio; plan[k]['autres'] += others; plan[k]['ids'] += ids
    total = sum(os.path.getsize(f) for pl in plan.values() for f in pl['audio'] + pl['autres'])
    for k, pl in plan.items():
        say(f'\n{LIBS[k]["nom"]} : {len(pl["audio"])} morceau(x), {len(pl["autres"])} autre(s) fichier(s), '
            f'{len(pl["ids"])} entrée(s) de la base')
        shown = sorted(pl['audio'] + pl['autres'])
        for f in shown[:30]:
            say('  ' + os.path.relpath(f, LIBS[k]['dir']))
        if len(shown) > 30:
            say(f'  … et {len(shown) - 30} autre(s)')
    say(f'\nTotal : {total / 1e9:.2f} Go')
    if args.simulation:
        say('SIMULATION : rien n\'a été supprimé.')
        return
    if not args.oui:
        if not sys.stdin.isatty():
            sys.exit('Confirmation impossible sans terminal : relancez avec --oui pour confirmer.')
        if input('\nSupprimer définitivement ces fichiers ? (o/N) ').strip().lower() not in ('o', 'oui', 'y', 'yes'):
            say('Annulé, rien n\'a été supprimé.')
            return
    global LOGF
    LOGF = open(f'{JOURNAL}/retrait_{LOT}.log', 'w', encoding='utf-8')
    for k, pl in plan.items():
        lib = LIBS[k]
        db = lib['beetsdir'] + '/library.db'
        shutil.copy(db, f'{JOURNAL}/{k}_library_avant_retrait_{LOT}.db')
        blib = Library(db)
        for i in pl['ids']:
            it = blib.get_item(i)
            if it:
                it.remove(delete=False, with_album=True)
        for f in pl['audio'] + pl['autres']:
            if os.path.lexists(f):
                os.remove(f)
                LOGF.write(f'supprimé\t{f}\n')
        EMP.con.executemany('delete from f where path = ?', [(os.fsencode(f),) for f in pl['audio']])
        EMP.commit()
        # dossiers devenus vides, en remontant jusqu'à Artistes / Compilations (jamais au-delà)
        for d in sorted({os.path.dirname(f) for f in pl['audio'] + pl['autres']} | {p for kk, p in targets if kk == k},
                        key=len, reverse=True):
            while os.path.isdir(d) and not os.listdir(d) and len(os.path.relpath(d, lib['dir']).split(os.sep)) >= 2:
                os.rmdir(d); d = os.path.dirname(d)
        say(f'{lib["nom"]} : {len(pl["audio"]) + len(pl["autres"])} fichier(s) supprimé(s), {len(pl["ids"])} entrée(s) retirée(s) de la base')
    regen_annuaires(list(plan))
    say(f'\nJournal : {JOURNAL}/retrait_{LOT}.log')


def verification(simulation):
    """Recalcule toutes les empreintes et contrôle les deux bibliothèques. Ne touche à aucun fichier de musique :
    seules les entrées de la base dont le fichier a disparu et les entrées périmées du cache sont retirées."""
    report = f'{JOURNAL}/verification_{LOT}.tsv'
    out, all_untracked, changed = [], [], []
    say('\n--- Base beets et disque')
    for key, lib in LIBS.items():
        db = lib['beetsdir'] + '/library.db'
        SPIN.set(f'{lib["nom"]} : comparaison de la base et du disque')
        known = lib_paths(db)
        missing = [(i, p) for i, p in known if not os.path.exists(p)]
        in_db = {p for _, p in known}
        untracked, nocover = [], []
        for folder, dirs, files in os.walk(lib['dir']):
            if folder == lib['dir']:
                dirs[:] = [d for d in dirs if d in ('Artistes', 'Compilations', 'À trier')]
            audio = [f for f in files if f.lower().endswith(AUDIO_EXT)]
            for f in audio:
                if os.fsencode(os.path.join(folder, f)) not in in_db:
                    untracked.append(os.path.join(folder, f))
            if audio and 'folder.jpg' not in files:
                nocover.append(folder)
        if missing and not simulation:
            changed.append(key)
            shutil.copy(db, f'{JOURNAL}/{key}_library_avant_verification_{LOT}.db')
            blib = Library(db)
            for i, _ in missing:
                it = blib.get_item(i)
                if it:
                    it.remove(delete=False, with_album=True)
        out += [('fichier disparu (retiré de la base)' if not simulation else 'fichier disparu', lib['nom'],
                 p.decode('utf-8', 'replace')) for _, p in missing]
        all_untracked += untracked
        out += [('absent de la base', lib['nom'], p) for p in untracked]
        out += [('album sans pochette', lib['nom'], f) for f in nocover]
        say(f'  {lib["nom"]} : {len(known)} piste(s) en base, {len(missing)} fichier(s) disparu(s)'
            + ('' if simulation or not missing else ' (retirés de la base)')
            + f', {len(untracked)} fichier(s) audio absent(s) de la base, {len(nocover)} album(s) sans pochette')

    say('\n--- Empreintes (calcul complet, sans le cache)')
    hashes = build_hashes(force=True, extra=all_untracked)
    groups = defaultdict(list)
    for p, h in hashes.items():
        groups[h].append(p)
    dups = [sorted(g) for g in groups.values() if len(g) > 1]
    for g in sorted(dups):
        for p in g:
            out.append(('fichier identique', f'groupe {dups.index(g) + 1}', p.decode('utf-8', 'replace')))
    say(f'  {len(dups)} groupe(s) de fichiers identiques ({sum(len(g) - 1 for g in dups)} copie(s) en trop)')
    stale = [p for (p,) in EMP.con.execute('select path from f') if bytes(p) not in hashes]
    if stale and not simulation:
        EMP.con.executemany('delete from f where path = ?', [(p,) for p in stale])
        EMP.commit()
    say(f'  cache : {len(stale)} entrée(s) périmée(s)' + ('' if simulation or not stale else ' retirée(s)'))

    if os.path.isdir(STAGE):
        n = sum(len(fs) for _, _, fs in os.walk(STAGE))
        out.append(('reste d\'un rangement interrompu', CANDIDATS, STAGE))
        say(f'\n  {n} fichier(s) dans {STAGE} : reste d\'un rangement interrompu, ils reviendront dans {CANDIDATS} au prochain lancement')

    if changed:
        regen_annuaires(changed)
    with open(report, 'w', encoding='utf-8') as fh:
        fh.write('problème\tbibliothèque\tchemin\n')
        for row in out:
            fh.write('\t'.join(row) + '\n')
    say(f'\nRapport détaillé : {report}')


def main():
    global LOGF, EMP
    ap = argparse.ArgumentParser(description='Range la musique déposée dans musics/Candidats.')
    ap.add_argument('--simulation', action='store_true', help='montre ce qui serait fait, sans rien ranger')
    ap.add_argument('--sans-internet', action='store_true', help='pas de recherche de pochette en ligne')
    ap.add_argument('--sans-pochettes', action='store_true', help='ne pose aucune pochette')
    ap.add_argument('--empreintes', action='store_true',
                    help="calcule d'avance l'empreinte de chaque fichier des bibliothèques (long la première fois), puis s'arrête")
    ap.add_argument('--retirer', nargs='+', metavar='CHEMIN',
                    help='supprime proprement un ou plusieurs morceaux ou albums (fichiers, base, cache, annuaire), '
                         'après confirmation ; chemin relatif à la bibliothèque, ex. « Artistes/X/(2004) Album »')
    ap.add_argument('--oui', action='store_true', help='avec --retirer : ne pas demander de confirmation')
    ap.add_argument('--verification', action='store_true',
                    help='recalcule toutes les empreintes sans le cache et vérifie les bibliothèques (base, disque, '
                         'doublons, pochettes), puis s\'arrête ; avec --simulation, ne corrige rien')
    args = ap.parse_args()
    os.makedirs(JOURNAL, exist_ok=True)
    lock = open(f'{JOURNAL}/.ranger.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Un rangement est déjà en cours.')
    if not os.path.exists(EMPREINTES) and os.path.exists(EMPREINTES_ANCIEN):
        shutil.move(EMPREINTES_ANCIEN, EMPREINTES)  # ancien emplacement du cache
    EMP = Empreintes(EMPREINTES)
    if args.empreintes:
        build_hashes()
        return
    if args.retirer:
        retirer(args)
        return
    if args.verification:
        LOGF = open(f'{JOURNAL}/verification_{LOT}.log', 'w', encoding='utf-8')
        say(f'Vérification complète {LOT}' + (' — SIMULATION, rien ne sera corrigé' if args.simulation else ''))
        verification(args.simulation)
        return
    if not args.simulation:
        LOGF = open(f'{JOURNAL}/ranger_{LOT}.log', 'w', encoding='utf-8')
    say(f'Rangement {LOT}' + (' — SIMULATION, rien ne sera rangé' if args.simulation else ''))
    os.makedirs(CAND, exist_ok=True)
    restore_stage()  # restes d'un lancement interrompu
    say('\n--- Aiguillage par format')
    SPIN.set('Aiguillage par format')
    moved, ignored = route()
    say('  ' + ', '.join(f'{moved[k]} fichier(s) → {LIBS[k]["nom"]}' for k in LIBS))
    for p in ignored:
        say(f'  format non pris en charge, laissé en place : {os.path.relpath(p, CAND)}')
    try:
        results = {k: process(k, args) for k in LIBS}
    finally:
        SPIN.set(f'Retour des fichiers restants dans {CANDIDATS}/')
        kept = restore_stage()
        for folder, dirs, fs in os.walk(CAND, topdown=False):
            if folder != CAND and not hidden(os.path.relpath(folder, CAND)) and not os.listdir(folder):
                os.rmdir(folder)
    for p in kept:
        say(f'  resté dans le dossier de travail (même nom déjà dans {CANDIDATS}/) : {p}')
    if not args.simulation and any(results.values()):
        regen_annuaires(LIBS)
    SPIN.set('')
    say('\n=== Bilan')
    for k, r in results.items():
        if not r:
            say(f'  {LIBS[k]["nom"]} : rien à ranger'); continue
        line = f'  {LIBS[k]["nom"]} : {r["pistes"]} piste(s), {r["albums"]} album(s)'
        if r.get('deja'):
            line += f', {r["deja"]} déjà présente(s) non ajoutée(s)'
            if not args.simulation:
                aside = r['deja'] - r['supprimes']
                line += f' ({r["supprimes"]} identique(s) supprimée(s) de {CANDIDATS}/' + \
                        (f', {aside} mise(s) de côté dans {CANDIDATS}/{DEJA}/' if aside else '') + ')'
        if r.get('annexes'):
            line += f', {r["annexes"]} fichier(s) annexe(s) supprimé(s) de {CANDIDATS}/'
        if r.get('pochettes'):
            line += ', pochettes : ' + ', '.join(f'{v} {s}' for s, v in r['pochettes'].items())
        say(line)
        for p in r.get('restants', []):
            say(f'    non rangé (illisible, sans album) : {os.path.relpath(p, CAND)}')
    slow = sorted(SPIN.durations, key=lambda d: -d[1])[:8]
    if LOGF and slow:
        LOGF.write('\nÉtapes les plus longues :\n' + ''.join(f'  {int(d) // 60}:{int(d) % 60:02d}  {t}\n' for t, d in slow))
    if os.environ.get('RANGER_DUREES'):
        for t, d in slow:
            say(f'  {int(d) // 60}:{int(d) % 60:02d}  {t}')
    if not args.simulation:
        say(f'\nJournal : {JOURNAL}/ranger_{LOT}.log')


if __name__ == '__main__':
    main()
