#!/usr/bin/python3
"""Range la musique déposée dans les dossiers « Candidats » des bibliothèques.

Pour chaque bibliothèque (Musiques Low-Res = MP3, Musiques Hi-Res = sans perte) :
  1. aiguille les fichiers vers la bonne bibliothèque selon leur format ;
  2. indexe les fichiers avec beets (lecture des tags, sans les modifier) ;
  3. complète artiste/album/année/disque d'après les dossiers si les tags manquent,
     harmonise avec les artistes et albums déjà présents ;
  4. range en Artistes/<Artiste>/(Année) Album/ ou Compilations/(Année) Album/ ;
  5. pose un folder.jpg par album (pochette intégrée, image du dossier déposé,
     Deezer, iTunes, Cover Art Archive, Discogs, sinon pochette générée) ;
  6. régénère Annuaire.html et Annuaire.csv.

Les fichiers audio ne sont jamais modifiés ni écrasés (un doublon devient « .1 »).
Les fichiers non audio (images, .cue, .nfo…) restent dans le dossier Candidats.

Usage :
  list_songs                  range tout ce qui est dans les dossiers Candidats
  list_songs --simulation     montre ce qui serait fait, sans rien déplacer
  list_songs --sans-internet  pas de recherche de pochette en ligne
"""
import argparse, colorsys, datetime, fcntl, hashlib, io, json, os, re, shutil, subprocess, sys
import tempfile, textwrap, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, '/usr/share/beets')
from beets import config  # noqa: E402
from beets.library import Library  # noqa: E402
from mediafile import MediaFile  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from unidecode import unidecode  # noqa: E402

ROOT = os.environ.get('RANGER_ROOT', '/srv/dev-disk-by-uuid-2a16d8ee-941c-4fa7-a2d0-03ce63105226/partage/')
HOME = os.environ.get('RANGER_HOME', os.path.expanduser('~'))
LIBS = {
    'low': dict(nom='Musiques Low-Res', dir=ROOT + 'Musiques Low-Res', beetsdir=HOME + '/.config/beets'),
    'hi': dict(nom='Musiques Hi-Res', dir=ROOT + 'Musiques Hi-Res', beetsdir=HOME + '/.config/beets/hires'),
}
CANDIDATS = 'Candidats'
JOURNAL = HOME + '/.config/beets/journal'
ANNUAIRE = HOME + '/.config/beets/annuaire/annuaire.py'
DISCOGS_TOKEN = HOME + '/discog'
LOW_EXT = ('.mp3',)
HI_EXT = ('.flac', '.wav', '.aiff', '.aif', '.dsf', '.dff', '.wv', '.ape')
OTHER_LOSSY = ('.wma', '.ogg', '.opus', '.aac', '.mpc')
AUDIO_EXT = LOW_EXT + HI_EXT + OTHER_LOSSY + ('.m4a',)
UA = 'list_songs/1.0 (bibliotheque musicale personnelle)'
MINW = 500

LOT = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
LOGF = None


def say(*a):
    msg = ' '.join(str(x) for x in a)
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

def route(simulation):
    """Envoie chaque fichier audio dans le dossier Candidats de la bonne bibliothèque."""
    moved, ignored, emptied = 0, [], set()
    for key, lib in LIBS.items():
        cand = os.path.join(lib['dir'], CANDIDATS)
        for p in list(audio_files(cand)):
            ext = os.path.splitext(p)[1].lower()
            if ext in LOW_EXT:
                target = 'low'
            elif ext in HI_EXT or (ext == '.m4a' and is_alac(p)):
                target = 'hi'
            else:
                ignored.append(p); continue
            if target == key:
                continue
            rel = os.path.relpath(p, cand)
            dest = os.path.join(LIBS[target]['dir'], CANDIDATS, rel)
            say(f'  aiguillage → {LIBS[target]["nom"]} : {rel}')
            if not simulation:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if not os.path.exists(dest):
                    shutil.move(p, dest)
                emptied.add((os.path.dirname(p), os.path.dirname(dest)))
            moved += 1
    # un dossier qui n'a plus d'audio emmène ses pochettes et fichiers annexes avec la musique
    for src, dst in emptied:
        if os.path.isdir(src) and not any(f.lower().endswith(AUDIO_EXT) for f in os.listdir(src)):
            for f in os.listdir(src):
                if os.path.isfile(os.path.join(src, f)) and not os.path.exists(os.path.join(dst, f)):
                    shutil.move(os.path.join(src, f), os.path.join(dst, f))
    return moved, ignored


# --------------------------------------------------------------------------- 3. métadonnées

YEAR = re.compile(r'(?<!\d)(19[5-9]\d|20[0-4]\d)(?!\d)')
DISCSEG = re.compile(r'^(?:.*[\[\(_ -])?(?:cd|disc|disk|disque)[\s_-]*(\d+)\b[^/]*$', re.I)
DISCALB = re.compile(r'^(.*?)[\s,_-]*[\[\(]?\b(?:cd|disc|disk)\s*(\d+)\b[^\]\)]*[\]\)]?\s*$', re.I)
FEAT = re.compile(r'\s+(?:feat\.?|ft\.?|featuring|avec)\s+.*$', re.I)
VA = re.compile(r'^(various( artists)?|va|v\.a\.|artistes divers|multi[- ]interpr[eè]tes|compilation)$', re.I)


def clean_dirname(s):
    s = re.sub(r'\[[^\]]*\]', '', s)
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
    album = clean_dirname(album) or clean_dirname(segs[-1]) or 'Titres divers'
    artist = clean_dirname(artist)
    if comp or VA.match(artist or ''):
        return 'Various Artists', album, yr, disc, True
    return artist, album, yr, disc, False


def fix_metadata(lib, cand_dir):
    """Complète et harmonise les métadonnées des pistes du lot courant (dans la base seulement)."""
    batch = list(lib.items(f'lot:{LOT}'))
    if not batch:
        return 0
    old = [i for i in lib.items() if i.get('lot') != LOT]
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
        for sep in (' & ', ' vs. ', ' vs ', ' x ', ', ', ' and ', ' et '):
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
        va = it.albumartist == 'Various Artists' or bool(it.comp)
        it.comp = va; it['va'] = 1 if va else 0; it['atrier'] = 0
        k = (norm(it.albumartist), it.album.lower().strip())
        if k in known_albums:
            it.album, y = known_albums[k]; it.year = y or it.year
        it.store()

    # année, nombre de disques et disques déduits des sous-dossiers, par album
    grp = defaultdict(list)
    for it in lib.items(f'lot:{LOT}'):
        grp[(it.albumartist, it.album.lower())].append(it)
    for its in grp.values():
        yrs = Counter(i.year for i in its if i.year)
        yr = yrs.most_common(1)[0][0] if yrs else 0
        names = Counter(i.album for i in its)
        name = max(names, key=lambda x: (x != x.lower(), x != x.upper(), names[x]))
        ods = sorted({i['origdir'] for i in its})
        if len(ods) > 1 and len({os.path.dirname(o) for o in ods}) == 1 and len({i.disc for i in its}) < len(ods):
            for i in its:
                i.disc = ods.index(i['origdir']) + 1
        dt = max([i.disc or 1 for i in its])
        for i in its:
            i.year, i.album = yr, name
            if dt > 1:
                i.disctotal = dt
            i.store()

    # cohérence des albums beets avec leurs pistes (un album beets = un dossier déposé)
    for aid in {i.album_id for i in lib.items(f'lot:{LOT}') if i.album_id}:
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
    for it in lib.items():
        try:
            st = os.stat(it.path)
        except FileNotFoundError:
            continue
        k = (st.st_dev, st.st_ino)
        if k in seen and it.get('lot') == LOT:
            it.remove(delete=False, with_album=True)
        else:
            seen.setdefault(k, it.id)
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


def cover_local(folder, srcdirs):
    prio, bad = ('folder', 'cover', 'front', 'albumart', 'pochette'), ('back', 'cd', 'disc', 'booklet', 'inlay', 'inside', 'tray', 'verso', 'dos', 'label')
    cands = []
    for d in srcdirs:
        for dd in (d, os.path.dirname(d)):
            if not os.path.isdir(dd):
                continue
            for f in os.listdir(dd):
                fl = f.lower()
                if fl.endswith(('.jpg', '.jpeg', '.png')):
                    score = 2 if fl.startswith(prio) else (0 if any(x in fl for x in bad) else 1)
                    if score:
                        cands.append((score, os.path.getsize(os.path.join(dd, f)), os.path.join(dd, f)))
    for _, _, p in sorted(cands, reverse=True):
        with open(p, 'rb') as fh:
            if save_cover(fh.read(), folder, 'image déposée'):
                return True
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


def covers(lib, cand_dir, internet):
    token = open(DISCOGS_TOKEN).read().strip() if internet and os.path.exists(DISCOGS_TOKEN) else ''
    folders = defaultdict(set)
    info = {}
    for it in lib.items(f'lot:{LOT}'):
        f = os.path.dirname(it.path.decode('utf-8', 'replace'))
        folders[f].add(os.path.join(cand_dir, it.get('origdir') or ''))
        info[f] = (it.albumartist, it.album, it.year)
    stats = Counter()
    for f, srcs in sorted(folders.items()):
        if os.path.exists(os.path.join(f, 'folder.jpg')) or not os.path.isdir(f):
            continue
        aa, al, yr = info[f]
        if cover_embedded(f):
            stats['intégrée'] += 1
        elif cover_local(f, srcs):
            stats['image déposée'] += 1
        elif internet and cover_online(f, aa, re.sub(r'\s*\((?:UK|US|édition \d+)\)', '', al), token):
            stats['internet'] += 1
        else:
            cover_generated(f, aa, al, yr); stats['générée'] += 1
    return stats


# --------------------------------------------------------------------------- traitement d'une bibliothèque

def process(key, args):
    lib_cfg = LIBS[key]
    cand = os.path.join(lib_cfg['dir'], CANDIDATS)
    os.makedirs(cand, exist_ok=True)
    tops = [os.path.join(cand, e) for e in sorted(os.listdir(cand)) if not e.startswith('_')]
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

    out = beet(beetsdir, 'import', '-q', '-A', '-C', '-W', '--set', f'lot={LOT}', *tops, capture=True)
    unreadable = [l.split('unreadable file: ', 1)[1] for l in out.splitlines() if 'unreadable file: ' in l]
    config.clear(); config.read()
    lib = Library(os.path.join(beetsdir, 'library.db'))
    # formats qui n'appartiennent pas à cette bibliothèque (ne devrait pas arriver après l'aiguillage)
    for it in lib.items(f'lot:{LOT}'):
        ext = os.path.splitext(it.path.decode('utf-8', 'replace'))[1].lower()
        if (key == 'low') != (ext in LOW_EXT):
            it.remove(delete=False, with_album=True)
    n = fix_metadata(lib, cand)
    say(f'  {n} piste(s) indexée(s), {len(unreadable)} illisible(s) par beets')

    preview = beet(beetsdir, 'move', '-p', f'lot:{LOT}', capture=True)
    dests = [l.split(' -> ', 1)[1].strip() for l in preview.splitlines() if l.startswith('  -> ')]
    albums = Counter(os.path.relpath(os.path.dirname(d), lib_cfg['dir']) for d in dests)
    for a, c in sorted(albums.items()):
        say(f'  → {a}  ({c} piste{"s" if c > 1 else ""})')
    if args.simulation:
        shutil.rmtree(tmp, ignore_errors=True)
        return dict(pistes=n, albums=len(albums), illisibles=len(unreadable))

    before = {i.id: i.path for i in lib.items(f'lot:{LOT}')}
    beet(beetsdir, 'move', f'lot:{LOT}', capture=True)
    lib = Library(os.path.join(beetsdir, 'library.db'))
    with open(f'{JOURNAL}/ranger_{LOT}_{key}.tsv', 'w', encoding='utf-8') as j:
        for it in lib.items(f'lot:{LOT}'):
            j.write(f"{before.get(it.id, b'').decode('utf-8', 'replace')}\t{it.path.decode('utf-8', 'replace')}\n")

    # fichiers illisibles : placés à côté de leurs pistes sœurs
    by_od = {}
    for it in lib.items(f'lot:{LOT}'):
        by_od.setdefault(it.get('origdir'), os.path.dirname(it.path.decode('utf-8', 'replace')))
    lib_inodes = set()
    for it in lib.items():
        try:
            lib_inodes.add(os.stat(it.path).st_ino)
        except FileNotFoundError:
            pass
    left = []
    for p in audio_files(cand):
        if not p.lower().endswith(LOW_EXT if key == 'low' else HI_EXT + ('.m4a',)):
            continue
        if os.stat(p).st_ino in lib_inodes:
            continue  # second nom d'un fichier déjà rangé (lien physique)
        dest_dir = by_od.get(os.path.relpath(os.path.dirname(p), cand))
        if dest_dir:
            stem, ext = os.path.splitext(os.path.basename(p))
            dest = os.path.join(dest_dir, stem + ext); k = 1
            while os.path.exists(dest):
                dest = os.path.join(dest_dir, f'{stem}.{k}{ext}'); k += 1
            shutil.move(p, dest)
            say(f'  illisible placé avec son album : {dest}')
        else:
            left.append(p)
    stats = covers(lib, cand, not args.sans_internet) if not args.sans_pochettes else Counter()
    # nettoyage : dossiers devenus vides dans Candidats et dans la bibliothèque
    for top in (cand, lib_cfg['dir']):
        for folder, dirs, fs in os.walk(top, topdown=False):
            if folder not in (cand, lib_cfg['dir']) and not os.listdir(folder):
                os.rmdir(folder)
    return dict(pistes=n, albums=len(albums), illisibles=len(unreadable), restants=left, pochettes=stats)


def main():
    global LOGF
    ap = argparse.ArgumentParser(description='Range la musique déposée dans les dossiers Candidats.')
    ap.add_argument('--simulation', action='store_true', help='montre ce qui serait fait, sans rien déplacer')
    ap.add_argument('--sans-internet', action='store_true', help='pas de recherche de pochette en ligne')
    ap.add_argument('--sans-pochettes', action='store_true', help='ne pose aucune pochette')
    args = ap.parse_args()
    os.makedirs(JOURNAL, exist_ok=True)
    lock = open(f'{JOURNAL}/.ranger.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit('Un rangement est déjà en cours.')
    if not args.simulation:
        LOGF = open(f'{JOURNAL}/ranger_{LOT}.log', 'w', encoding='utf-8')
    say(f'Rangement {LOT}' + (' — SIMULATION, rien ne sera déplacé' if args.simulation else ''))
    say('\n--- Aiguillage par format')
    moved, ignored = route(args.simulation)
    say(f'  {moved} fichier(s) aiguillé(s)' + (' (en simulation, ils ne sont pas comptés ci-dessous)' if args.simulation and moved else ''))
    for p in ignored:
        say(f'  format non pris en charge, laissé en place : {p}')
    results = {k: process(k, args) for k in LIBS}
    if not args.simulation:
        for lib in LIBS.values():
            cand = os.path.join(lib['dir'], CANDIDATS)
            for folder, dirs, fs in os.walk(cand, topdown=False):
                if folder != cand and not os.listdir(folder):
                    os.rmdir(folder)
    if not args.simulation and any(results.values()) and os.path.exists(ANNUAIRE):
        say('\n--- Mise à jour des annuaires')
        for k, lib in LIBS.items():
            subprocess.run([sys.executable, ANNUAIRE, lib['dir'], lib['beetsdir'] + '/library.db', lib['nom']],
                           env=dict(os.environ, PYTHONPATH='/usr/share/beets'))
    say('\n=== Bilan')
    for k, r in results.items():
        if not r:
            say(f'  {LIBS[k]["nom"]} : rien à ranger'); continue
        line = f'  {LIBS[k]["nom"]} : {r["pistes"]} piste(s), {r["albums"]} album(s)'
        if r.get('pochettes'):
            line += ', pochettes : ' + ', '.join(f'{v} {s}' for s, v in r['pochettes'].items())
        say(line)
        for p in r.get('restants', []):
            say(f'    non rangé (illisible, sans album) : {p}')
    if not args.simulation:
        say(f'\nJournal : {JOURNAL}/ranger_{LOT}.log')


if __name__ == '__main__':
    main()
