#!/usr/bin/env python3
"""Turn extracted recipe text (from sbb151/afooft-recipes-source) into site data.

usage: python3 tools/build.py SOURCE_DIR [SITE_DIR]

SOURCE_DIR holds manifest.json, text/ and images/ as produced by the extraction
run on the Mac. Writes SITE_DIR/data/index.json, SITE_DIR/data/r/<id>.json,
SITE_DIR/img/<id>.jpg, SITE_DIR/img/t/<id>.jpg and SITE_DIR/data/duplicates.json.
"""
import json, re, sys, os, shutil, unicodedata, hashlib
from collections import defaultdict
from pathlib import Path

SRC = Path(sys.argv[1])
SITE = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent)

BULLET = re.compile(r'^\s*(?:[·•●▪◦‣∙\-\*–]|||o(?=\s))\s*')
NUMSTEP = re.compile(r'^\s*(?:step\s*)?(\d{1,2})\s*[.):]\s*(.*)$', re.I)
QTY_START = re.compile(r'^\s*(?:\d|[½⅓⅔¼¾⅛⅜⅝⅞]|one\b|two\b|three\b|four\b|a\s+(?:pinch|handful|dash|few|bunch|large|small|medium)|pinch\b|salt\b|kosher salt|freshly|juice of|zest of)', re.I)
UNIT = re.compile(r'\b(cups?|tablespoons?|tbsp?s?|teaspoons?|tsps?|ounces?|oz|pounds?|lbs?|grams?|g|kg|ml|liters?|quarts?|pints?|cloves?|cans?|sprigs?|sticks?|bunch(?:es)?|pinch|dash|large|medium|small|whole|heads?|slices?|pieces?|stalks?|packages?|pkg|jars?|bottles?|inch)\b', re.I)

H_ING = re.compile(r'^\s*(?:ingredients?|what you(?:\'|’)ll need|you will need)\b(.*)$', re.I)
H_DIR = re.compile(r'^\s*(?:preparation|directions?|method|instructions?|steps|procedure|how to make it|to make)\s*:?\s*$', re.I)
H_NOTE = re.compile(r'^\s*(?:tips?|notes?|cook(?:\'|’)s notes?|variations?|to serve|serving suggestions?|make ahead|storage)\s*:?\s*$', re.I)
H_YIELD = re.compile(r'^\s*(?:yield|yields|serves|servings|makes)\s*:?\s*(.+)$', re.I)
H_TIME = re.compile(r'^\s*(total time|prep(?:aration)? time|cook(?:ing)? time|time|active time)\s*:?\s*(.+)$', re.I)


def clean(s):
    s = unicodedata.normalize('NFC', s).replace(' ', ' ').replace(' ', '\n').replace('\r', '\n')
    s = re.sub(r'[ \t]+', ' ', s)
    return s


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')[:70] or 'recipe'


def looks_like_ingredient(line):
    l = BULLET.sub('', line)
    if len(l) > 140:
        return False
    return bool(QTY_START.match(l)) or (len(l) < 70 and bool(UNIT.search(l)) and not l.endswith('.'))


def is_subhead(line):
    l = line.strip()
    if not l or len(l) > 60 or BULLET.match(line) or NUMSTEP.match(l):
        return False
    return bool(re.match(r'^(for (the )?|to make|to serve|to finish|garnish|sauce|marinade|dressing|topping|filling|crust|dough|glaze)', l, re.I)) or (l.endswith(':') and len(l) < 40)


def parse(text, fallback_title):
    lines = [l.strip() for l in clean(text).split('\n')]
    lines = [l for l in lines if l is not None]
    nonblank = [l for l in lines if l]
    r = {'title': '', 'description': '', 'servings': '', 'prep': '', 'cook': '', 'total': '', 'ingredients': [], 'directions': [], 'notes': ''}
    if not nonblank:
        r['title'] = fallback_title
        return r, 0

    # Title: first short line, else file name
    first = nonblank[0]
    if len(first) <= 90 and not looks_like_ingredient(first):
        r['title'] = first.rstrip(':')
        start = lines.index(first) + 1
    else:
        r['title'] = fallback_title
        start = 0

    section = 'intro'
    intro, notes = [], []
    step_buf = None
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            if step_buf is not None and section == 'dir':
                pass
            continue
        m = H_ING.match(line)
        if m and len(line) < 60 and section in ('intro', 'ing', 'dir'):
            rest = m.group(1).strip(' :–-')
            if rest:
                rest = re.sub(r'^(for|serves)\s+', '', rest, flags=re.I)
                r['servings'] = r['servings'] or rest
            section = 'ing'
            continue
        if H_DIR.match(line):
            section = 'dir'
            continue
        if H_NOTE.match(line) and section in ('dir', 'ing', 'notes'):
            section = 'notes'
            notes.append(line.rstrip(':') + ':')
            continue
        m = H_YIELD.match(line)
        if m and len(line) < 60 and section in ('intro', 'ing'):
            r['servings'] = r['servings'] or m.group(1).strip()
            continue
        m = H_TIME.match(line)
        if m and len(line) < 60 and section in ('intro', 'ing'):
            k = m.group(1).lower()
            key = 'total' if 'total' in k or k == 'time' else 'prep' if 'prep' in k or 'active' in k else 'cook'
            r[key] = r[key] or m.group(2).strip()
            continue

        if section == 'intro':
            # Unlabelled ingredient lists: switch when a run of ingredient-like lines starts
            if BULLET.match(raw) or looks_like_ingredient(line):
                section = 'ing'
            else:
                intro.append(line)
                continue
        if section == 'ing':
            sm = NUMSTEP.match(line)
            if (sm and len(line) > 60) or (not BULLET.match(raw) and (len(line) > 160 or (len(line) > 70 and line.endswith('.') and not looks_like_ingredient(line)))):
                section = 'dir'
            elif is_subhead(raw):
                r['ingredients'].append({'h': line.rstrip(':')})
                continue
            else:
                r['ingredients'].append(BULLET.sub('', line))
                continue
        if section == 'dir':
            sm = NUMSTEP.match(line)
            body = sm.group(2) if sm else BULLET.sub('', line)
            if not body:
                continue
            if is_subhead(raw) and not sm and len(r['directions']) > 0 and len(body) < 40:
                r['directions'].append({'h': body.rstrip(':')})
            else:
                r['directions'].append(body)
            continue
        if section == 'notes':
            notes.append(line)

    r['description'] = '\n'.join(intro).strip()
    r['notes'] = '\n'.join(notes).strip()
    # A "recipe" with a huge intro and nothing else is really unstructured text
    structured = bool(r['ingredients']) and bool(r['directions'])
    score = (2 if r['ingredients'] else 0) + (2 if r['directions'] else 0) + (1 if r['description'] else 0) + (1 if r['servings'] else 0) + min(len(text), 20000) / 20000
    if not structured:
        r['text'] = clean(text).strip()
    return r, score


# ---------- categories ----------
CATS = [
    ('Desserts', r'\b(cake|cookie|pie|tart|brownie|pudding|ice cream|sorbet|gelato|cobbler|crisp|crumble|meringue|mousse|custard|frosting|cheesecake|fudge|truffle|biscotti|macaroon|blondie|dessert|sweet|caramel|chocolate|baked apples|pavlova|shortbread|scone|cupcake|torte|galette|bars?)\b'),
    ('Breads & Baking', r'\b(bread|rolls?|focaccia|biscuits?|muffins?|loaf|brioche|pizza|dough|no-knead|bagels?|crackers?|cornbread|popovers?)\b'),
    ('Breakfast', r'\b(breakfast|pancakes?|waffles?|french toast|granola|omelet|frittata|strata|eggs? benedict|quiche|oatmeal|brunch)\b'),
    ('Appetizers', r'\b(appetizers?|dip|hummus|crostini|bruschetta|toasts?|deviled|canap|tapenade|fondue|mezze|nuts|pâté|pate|gougères|cheese ball|spread)\b'),
    ('Soups & Stews', r'\b(soup|stew|chowder|bisque|chili|gumbo|bouillabaisse|cioppino|broth|gazpacho|ragout|pho|ramen|minestrone)\b'),
    ('Salads', r'\b(salad|slaw|coleslaw|vinaigrette|niçoise|nicoise|carpaccio)\b'),
    ('Pasta & Grains', r'\b(pasta|spaghetti|linguine|penne|rigatoni|ziti|lasagna|noodles?|gnocchi|risotto|orzo|fettuccine|macaroni|mac and cheese|bolognese|pesto|couscous|farro|quinoa|rice|polenta|bulgur|ravioli|tortellini|carbonara|orecchiette|bucatini)\b'),
    ('Chicken & Poultry', r'\b(chicken|turkey|duck|cornish|hen|poultry|quail|capon)\b'),
    ('Beef', r'\b(beef|steak|brisket|short ribs?|burgers?|meatloaf|wellington|filet|tenderloin|prime rib|veal|oxtail|bolognese)\b'),
    ('Pork & Lamb', r'\b(pork|ham|bacon|sausages?|prosciutto|pancetta|chops?|lamb|porchetta|carnitas|ribs|choucroute|chorizo)\b'),
    ('Seafood', r'\b(fish|salmon|tuna|cod|halibut|shrimp|prawns?|scallops?|crab|lobster|clams?|mussels?|oysters?|seafood|swordfish|trout|bass|sole|snapper|anchov|cioppino|bouillabaisse|paella|calamari|squid|octopus|mahi)\w*'),
    ('Vegetables & Sides', r'\b(potato(?:es)?|squash|zucchini|eggplant|cauliflower|broccoli|carrots?|beets?|brussels|asparagus|green beans|spinach|kale|cabbage|mushrooms?|corn|peppers?|tomato(?:es)?|onions?|sweet potato(?:es)?|stuffing|dressing|gratin|vegetables?|veggie|leeks?|fennel|artichokes?|peas)\b'),
    ('Sauces & Condiments', r'\b(sauce|ketchup|mayo|aioli|chutney|relish|jam|pickles?|salsa|gravy|dressing|vinaigrette|butter|marinade|rub|compote|pesto|chimichurri)\b'),
    ('Drinks', r'\b(cocktail|martini|punch|sangria|lemonade|smoothie|margarita|negroni|spritz|eggnog|cider|tea|coffee|drinks?)\b'),
    ('Menus & Holidays', r'\b(thanksgiving|christmas|easter|passover|hanukkah|new year|menu|holiday|party|dinner 20\d\d|birthday)\b'),
    ('Pressure Cooker & Slow Cooker', r'\b(pressure cooker|instant pot|slow cooker|crock ?pot|multicooker)\b'),
    ('Sheet Pan', r'\bsheet[- ]pan\b'),
    ('Grilling', r'\b(grill(?:ed|ing)?|barbecue|bbq|smoked?|kebabs?|skewers?)\b'),
]
MAIN = {'Chicken & Poultry', 'Beef', 'Pork & Lamb', 'Seafood'}


def categorize(title, folder):
    t = title.lower()
    cats = [name for name, pat in CATS if re.search(pat, t, re.I)]
    if folder:
        cats.append(folder)
    # sides get dropped when the dish is clearly a main
    if 'Vegetables & Sides' in cats and MAIN & set(cats):
        cats.remove('Vegetables & Sides')
    if 'Sauces & Condiments' in cats and len(cats) > 1 and not re.search(r'\b(sauce|ketchup|mayo|aioli|chutney|jam|pickles?|salsa|gravy|vinaigrette|marinade|rub|compote|chimichurri)$', t):
        cats.remove('Sauces & Condiments')
    return cats or ['Other']


# ---------- duplicates ----------
STOP = set('a an and the of with in on for to or from my best easy simple classic recipe version copy new old style'.split())


def title_key(t):
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().lower()
    t = re.sub(r'\(\d+\)|\bcopy\b|\bv\d\b|\bversion \d\b|\bedited\b|\bprinted\b|\bautosaved\b', ' ', t)
    words = [w for w in re.findall(r'[a-z0-9]+', t) if w not in STOP]
    return ' '.join(sorted(words))


def shingles(text, k=4):
    words = re.findall(r'[a-z0-9]+', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower())
    return {' '.join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def main():
    manifest = json.loads((SRC / 'manifest.json').read_text())
    items = []
    skipped = []
    for m in manifest:
        p = m['path']
        ext = p.rsplit('.', 1)[-1].lower() if '.' in p else ''
        name = os.path.basename(p).rsplit('.', 1)[0]
        folder = os.path.dirname(p)
        if ext in ('jpg', 'jpeg', 'png', 'gif', 'heic', 'tmp', 'prn', 'xlsx', 'csv') or name.startswith('~$'):
            continue
        if not m.get('text') or not (SRC / m['text']).exists():
            skipped.append({'file': p, 'reason': m.get('error') or 'no text extracted'})
            continue
        text = (SRC / m['text']).read_text(errors='replace')
        if len(text.strip()) < 40:
            skipped.append({'file': p, 'reason': 'empty or nearly empty'})
            continue
        r, score = parse(text, name)
        r['file'] = p
        r['folder'] = folder
        r['modified'] = m.get('modified', '')
        r['_score'] = score
        r['_img'] = m.get('image')
        r['_sh'] = shingles(text)
        r['_tk'] = title_key(name) or title_key(r['title'])
        items.append(r)

    # Find duplicate groups: union-find over pairs that share most of their text,
    # or share a title and a good chunk of text.
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # inverted index on shingles to avoid comparing every pair
    index = defaultdict(list)
    for i, it in enumerate(items):
        for s in it['_sh']:
            index[s].append(i)
    shared = defaultdict(int)
    for s, ids in index.items():
        if len(ids) > 40:  # boilerplate phrases
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                shared[(ids[a], ids[b])] += 1
    by_title = defaultdict(list)
    for i, it in enumerate(items):
        by_title[it['_tk']].append(i)

    pairs = []
    for (a, b), n in shared.items():
        A, B = items[a]['_sh'], items[b]['_sh']
        c = n / max(1, min(len(A), len(B)))
        same_title = items[a]['_tk'] == items[b]['_tk']
        if c >= 0.8 or (same_title and c >= 0.4):
            pairs.append((a, b, c))
    for a, b, c in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)

    kept, dupes = [], []
    for g in groups.values():
        g.sort(key=lambda i: (round(items[i]['_score'], 1), len(items[i]['_sh']), items[i]['modified']), reverse=True)
        keep = items[g[0]]
        if not keep['_img']:
            keep['_img'] = next((items[i]['_img'] for i in g[1:] if items[i]['_img']), None)
        kept.append(keep)
        if len(g) > 1:
            dupes.append({'kept': keep['file'], 'excluded': [items[i]['file'] for i in g[1:]]})

    # Write output
    data = SITE / 'data'
    rdir = data / 'r'
    img = SITE / 'img'
    for d in (rdir, img / 't'):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    used = set()
    index_out = []
    try:
        from PIL import Image
    except ImportError:
        Image = None
    for r in sorted(kept, key=lambda r: r['title'].lower()):
        base = slug(r['title'])
        rid, n = base, 2
        while rid in used:
            rid, n = f'{base}-{n}', n + 1
        used.add(rid)
        r['id'] = rid
        r['categories'] = categorize(r['title'] + ' ' + os.path.basename(r['file']), r['folder'])
        image = thumb = None
        if r['_img'] and (SRC / r['_img']).exists():
            image, thumb = f'img/{rid}.jpg', f'img/t/{rid}.jpg'
            src = SRC / r['_img']
            if Image:
                with Image.open(src) as im:
                    im = im.convert('RGB')
                    big = im.copy(); big.thumbnail((1000, 1000)); big.save(SITE / image, quality=72, optimize=True)
                    w, h = im.size; s = min(w, h)
                    sq = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((128, 128))
                    sq.save(SITE / thumb, quality=70, optimize=True)
            else:
                shutil.copy(src, SITE / image); thumb = image
        out = {k: v for k, v in r.items() if not k.startswith('_') and v not in ('', [], None)}
        out['image'] = image
        (rdir / f'{rid}.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
        ing_text = ' '.join(x for x in r['ingredients'] if isinstance(x, str))
        snippet = ', '.join(r['categories'][:2])
        index_out.append({'id': rid, 't': r['title'], 'c': r['categories'], 'img': thumb, 's': snippet,
                          'k': re.sub(r'\s+', ' ', ing_text.lower())[:600]})
    (data / 'index.json').write_text(json.dumps(index_out, ensure_ascii=False, separators=(',', ':')))
    (data / 'duplicates.json').write_text(json.dumps({'duplicates': dupes, 'skipped': skipped}, ensure_ascii=False, indent=1))
    structured = sum(1 for r in kept if r['ingredients'] and r['directions'])
    print(f'files read: {len(items)}  recipes kept: {len(kept)}  structured: {structured}  '
          f'duplicate groups: {len(dupes)}  files excluded as duplicates: {sum(len(d["excluded"]) for d in dupes)}  skipped: {len(skipped)}')


if __name__ == '__main__':
    main()
