#!/usr/bin/env python3
"""Daily Dropbox check for the AFOOFT recipe site. Runs on the Mac that syncs Dropbox.

1. Compares the "AFOOFT Recipes" Dropbox folder with the private source repo's manifest.
2. Extracts text and one photo from new or changed files (and drops removed ones).
3. Pushes the source repo, rebuilds the site with tools/build.py, and pushes the site.

Nothing in Dropbox is changed. Recipes deleted or edited on the website stay that way,
because build.py reads data/edits.json from the site repo.

usage: python3 afooft_sync.py            (normally run by launchd; see install.sh)
       python3 afooft_sync.py --dry-run  (report what would change)
"""
import json, os, re, shutil, subprocess, sys, tempfile, unicodedata, zipfile
from datetime import datetime
from pathlib import Path

HOME = Path.home()
DROPBOX = Path(os.environ.get('AFOOFT_DROPBOX', HOME / 'Library/CloudStorage/Dropbox/AFOOFT Recipes'))
WORK = Path(os.environ.get('AFOOFT_WORK', HOME / 'afooft-sync'))
SOURCE = WORK / 'source'    # clone of sbb151/afooft-recipes-source
SITE = WORK / 'website'     # clone of sbb151/afooft-recipes-website
DRY = '--dry-run' in sys.argv

TEXT_TYPES = {'doc', 'docx', 'rtf', 'pdf', 'pptx', 'ppt', 'txt', 'csv'}
IMAGE_TYPES = {'jpg', 'jpeg', 'png', 'heic'}


def log(msg):
    print(f'{datetime.now():%Y-%m-%d %H:%M} {msg}', flush=True)


def run(*cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f'{" ".join(map(str, cmd))} failed: {r.stderr.strip() or r.stdout.strip()}')
    return r.stdout


def nfc(s):
    return unicodedata.normalize('NFC', s)


# ---------- extraction ----------
def text_of(path, ext):
    if ext in ('doc', 'docx', 'rtf'):
        with tempfile.NamedTemporaryFile(suffix='.txt') as t:
            run('textutil', '-convert', 'txt', '-output', t.name, str(path))
            return Path(t.name).read_text(errors='replace')
    if ext == 'pdf':
        if shutil.which('pdftotext'):
            return run('pdftotext', '-layout', str(path), '-')
        # PDFKit through JavaScript for Automation; built into macOS
        js = ("ObjC.import('Quartz');var d=$.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(%s));"
              "d.isNil()?'':ObjC.unwrap(d.string)") % json.dumps(str(path))
        return run('osascript', '-l', 'JavaScript', '-e', js, check=False)
    if ext == 'pptx':
        out = []
        with zipfile.ZipFile(path) as z:
            slides = sorted((n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)),
                            key=lambda n: int(re.findall(r'\d+', n)[-1]))
            for n in slides:
                xml = z.read(n).decode('utf8', 'replace')
                for para in re.findall(r'<a:p>(.*?)</a:p>', xml, re.S):
                    line = ''.join(re.findall(r'<a:t>([^<]*)</a:t>', para))
                    if line.strip():
                        out.append(line)
        return '\n'.join(out)
    if ext == 'ppt':
        # old binary PowerPoint: pull the UTF-16 text runs out of the file
        data = path.read_bytes()
        runs = re.findall(rb'(?:[\x20-\x7e\xa0-\xff]\x00|[\x09\x0a\x0d]\x00){4,}', data)
        return '\n'.join(r.decode('utf-16-le', 'replace') for r in runs)
    return path.read_text(errors='replace')


def photo_of(path, ext, out):
    """Write one photo for this file to `out` (jpg, max 1000px). Returns True if one was written."""
    src = None
    tmpdir = None
    if ext in IMAGE_TYPES:
        src = path
    elif ext in ('docx', 'pptx'):
        with zipfile.ZipFile(path) as z:
            media = [i for i in z.infolist() if re.match(r'(word|ppt)/media/.*\.(jpe?g|png)$', i.filename, re.I) and i.file_size >= 20000]
            if media:
                best = max(media, key=lambda i: i.file_size)
                tmpdir = tempfile.mkdtemp()
                src = Path(z.extract(best, tmpdir))
    if not src:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    run('sips', '-Z', '1000', '-s', 'format', 'jpeg', '-s', 'formatOptions', '70', str(src), '--out', str(out), check=False)
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out.exists()


# ---------- main ----------
def main():
    if not DROPBOX.exists():
        raise SystemExit(f'Dropbox folder not found: {DROPBOX}')
    for repo in (SOURCE, SITE):
        run('git', 'pull', '--rebase', '--quiet', cwd=repo)

    manifest = json.loads((SOURCE / 'manifest.json').read_text())
    known = {nfc(m['path']): m for m in manifest}
    on_disk = {}
    for f in DROPBOX.rglob('*'):
        if f.is_file() and not f.name.startswith(('.', '~$')):
            rel = f.relative_to(DROPBOX).as_posix()
            on_disk[nfc(rel)] = f

    added, changed, removed = [], [], []
    for rel, f in on_disk.items():
        ext = f.suffix.lower().lstrip('.')
        if ext not in TEXT_TYPES | IMAGE_TYPES:
            continue
        st = f.stat()
        m = known.get(rel)
        if not m:
            added.append(rel)
        elif m.get('size') != st.st_size:
            changed.append(rel)
    for rel in known:
        if rel not in on_disk:
            removed.append(rel)

    log(f'{len(added)} new, {len(changed)} changed, {len(removed)} removed in Dropbox')
    if DRY or not (added or changed or removed):
        for label, xs in (('new', added), ('changed', changed), ('removed', removed)):
            for x in xs:
                log(f'  {label}: {x}')
        return

    by_path = {nfc(m['path']): m for m in manifest}
    for rel in removed:
        m = by_path.pop(rel)
        for key in ('text', 'image'):
            if m.get(key):
                (SOURCE / m[key]).unlink(missing_ok=True)
    for rel in added + changed:
        f = on_disk[rel]
        ext = f.suffix.lower().lstrip('.')
        stem = rel.rsplit('.', 1)[0]
        entry = {'path': rel, 'size': f.stat().st_size,
                 'modified': datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec='seconds'),
                 'text': None, 'image': None, 'error': None}
        try:
            if ext in TEXT_TYPES:
                text = text_of(f, ext)
                tp = SOURCE / 'text' / f'{stem}.txt'
                tp.parent.mkdir(parents=True, exist_ok=True)
                tp.write_text(text)
                entry['text'] = f'text/{stem}.txt'
        except Exception as e:  # keep going; the manifest records what failed
            entry['error'] = str(e)[:300]
            log(f'  could not read {rel}: {e}')
        try:
            if photo_of(f, ext, SOURCE / 'images' / f'{stem}.jpg'):
                entry['image'] = f'images/{stem}.jpg'
        except Exception as e:
            log(f'  no photo from {rel}: {e}')
        by_path[rel] = entry
        log(f'  read {rel}')

    (SOURCE / 'manifest.json').write_text(json.dumps(sorted(by_path.values(), key=lambda m: m['path']), ensure_ascii=False, indent=1))
    msg = f'Dropbox check: {len(added)} new, {len(changed)} changed, {len(removed)} removed'
    run('git', 'add', '-A', cwd=SOURCE)
    run('git', 'commit', '-q', '-m', msg, cwd=SOURCE)
    run('git', 'push', '-q', cwd=SOURCE)

    print(run(sys.executable, str(SITE / 'tools' / 'build.py'), str(SOURCE), str(SITE)).strip())
    run('git', 'add', '-A', 'data', 'img', cwd=SITE)
    if run('git', 'status', '--porcelain', cwd=SITE).strip():
        run('git', 'commit', '-q', '-m', msg, cwd=SITE)
        # someone may have saved a recipe on the website meanwhile
        run('git', 'pull', '--rebase', '--quiet', cwd=SITE)
        run('git', 'push', '-q', cwd=SITE)
    log('site updated')


if __name__ == '__main__':
    main()
