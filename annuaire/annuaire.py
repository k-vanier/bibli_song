#!/usr/bin/python3
"""Génère Annuaire.html et Annuaire.csv à la racine du dossier musics, pour toutes les bibliothèques.

Usage : annuaire.py <dossier musics> <bibliothèque>:<base beets> [<bibliothèque>:<base beets>…]
  ex. : annuaire.py …/musics "Musiques Low-Res:~/.config/beets/library.db" "Musiques Hi-Res:~/.config/beets/hires/library.db"
Les métadonnées viennent de beets ; un fichier audio absent de la base est
listé d'après son nom. Les anciens annuaires par bibliothèque sont supprimés.
"""
import csv, datetime, json, os, re, sys
from beets import config
from beets.library import Library

root, libs = sys.argv[1], [a.split(':', 1) for a in sys.argv[2:]]
AUDIO = ('.mp3', '.flac', '.wav', '.dsf', '.aiff', '.wv', '.m4a', '.ape', '.part', '.mpg', '.iso')

config.read()


def quality(it, ext):
    if it is None:
        return ext.upper()
    fmt = it.format or ext.upper()
    if fmt == 'MP3':
        return f'MP3 {round(it.bitrate / 1000)} kbps' if it.bitrate else 'MP3'
    bits = f'{it.bitdepth} bits / ' if it.bitdepth else ''
    sr = f'{it.samplerate / 1000:g} kHz' if it.samplerate else ''
    return f'{fmt} {bits}{sr}'.strip()


albums = []
for name, dbp in libs:
    base = os.path.join(root, name)
    meta = {it.path.decode('utf-8', 'replace'): it for it in Library(os.path.expanduser(dbp)).items()}
    for old in ('Annuaire.html', 'Annuaire.csv'):  # ancien annuaire propre à la bibliothèque
        if os.path.exists(os.path.join(base, old)):
            os.remove(os.path.join(base, old))
    for folder, dirs, files in os.walk(base):
        if folder == base:
            dirs[:] = [d for d in dirs if d in ('Artistes', 'Compilations', 'À trier')]
        dirs.sort()
        audio = sorted(f for f in files if f.lower().endswith(AUDIO))
        if not audio:
            continue
        rel = os.path.relpath(folder, base)
        parts = rel.split('/')
        section = parts[0]
        if section == 'Artistes' and len(parts) >= 3:
            artist, al = parts[1], parts[2]
        else:
            artist, al = 'Compilations', parts[-1]
        m = re.match(r'^\((\d{4})\) (.*)$', al)
        year, title = (m.group(1), m.group(2)) if m else ('', al)
        tracks = []
        for f in audio:
            p = os.path.join(folder, f)
            it = meta.get(p)
            stem, ext = os.path.splitext(f)
            tracks.append({
                'n': f'{it.disc}-{it.track:02d}' if it and it.disctotal and it.disctotal > 1 and it.track
                     else (f'{it.track:02d}' if it and it.track else ''),
                't': (it.title if it and it.title else re.sub(r'^\d+(-\d+)?\s*-\s*', '', stem)),
                'a': (it.artist if it and it.artist else ''),
                'd': int(it.length) if it and it.length else 0,
                'q': quality(it, ext.lstrip('.')),
                'f': f,
            })
        albums.append({
            's': 'C' if section == 'Compilations' else 'A',
            'b': name, 'ar': artist, 'al': title, 'y': year, 'p': os.path.join(name, rel),
            'c': os.path.exists(os.path.join(folder, 'folder.jpg')),
            'tr': tracks,
        })

data = sorted(albums, key=lambda a: (a['s'] != 'A', a['ar'].lower(), a['y'] or '9999', a['al'].lower(), a['b']))
ntr = sum(len(a['tr']) for a in data)
dur = sum(t['d'] for a in data for t in a['tr'])
stats = {
    'title': 'Musiques',
    'libs': [name for name, _ in libs],
    'albums': len(data),
    'artists': len({a['ar'] for a in data if a['s'] == 'A'}),
    'compils': sum(1 for a in data if a['s'] == 'C'),
    'tracks': ntr,
    'hours': round(dur / 3600),
    'date': datetime.date.today().strftime('%d/%m/%Y'),
}

# CSV (séparateur ; et BOM UTF-8 pour Excel en français)
with open(os.path.join(root, 'Annuaire.csv'), 'w', encoding='utf-8-sig', newline='') as fh:
    w = csv.writer(fh, delimiter=';')
    w.writerow(['Bibliothèque', 'Section', 'Artiste', 'Année', 'Album', 'N°', 'Titre', 'Interprète', 'Durée', 'Qualité', 'Chemin'])
    for a in data:
        for t in a['tr']:
            w.writerow([a['b'], 'Compilations' if a['s'] == 'C' else 'Artistes', a['ar'], a['y'], a['al'], t['n'], t['t'], t['a'],
                        f"{t['d'] // 60}:{t['d'] % 60:02d}" if t['d'] else '', t['q'], f"{a['p']}/{t['f']}"])

tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'annuaire_template.html'), encoding='utf-8').read()
payload = json.dumps({'stats': stats, 'albums': data}, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
with open(os.path.join(root, 'Annuaire.html'), 'w', encoding='utf-8') as fh:
    fh.write(tpl.replace('__TITLE__', stats['title']).replace('__DATA__', payload))
print(f"{stats['title']}: {stats['albums']} albums, {stats['tracks']} pistes, {stats['hours']} h")
