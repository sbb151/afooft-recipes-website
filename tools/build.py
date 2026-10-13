#!/usr/bin/env python3
"""Turn extracted recipe text (from sbb151/afooft-recipes-source) into site data.

usage: python3 tools/build.py SOURCE_DIR [SITE_DIR]

SOURCE_DIR holds manifest.json, text/ and images/ as produced by the extraction
run on the Mac. Writes SITE_DIR/data/index.json, SITE_DIR/data/r/<id>.json,
SITE_DIR/img/<id>.jpg, SITE_DIR/img/t/<id>.jpg and SITE_DIR/data/duplicates.json.
"""
import json, re, sys, os, shutil, subprocess, unicodedata
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
H_YIELD = re.compile(r'^\s*(?:(?:yield|yields|serves|servings|makes)\s*:?\s*(.+)|((?:[\w ]+ for )?\d+\s*(?:[-–]|to)?\s*\d*\s*servings?\.?))$', re.I)
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
    if len(l) < 60 and re.search(r'\b(salt|pepper|to taste|for garnish|for serving|olive oil|as needed)\b', l, re.I) and not l.endswith('.'):
        return True
    return bool(QTY_START.match(l)) or (len(l) < 70 and bool(UNIT.search(l)) and not l.endswith('.'))


def continues(ings, raw, line):
    # PDFs and old slides wrap one ingredient over several lines ("4 pounds plum tomatoes," / "halved lengthwise")
    if not ings or not isinstance(ings[-1], str) or BULLET.match(raw) or QTY_START.match(line):
        return False
    prev = ings[-1].rstrip()
    if line[:1].islower() or line[:1] in '(':
        return True
    return prev.endswith((',', ' or', ' and', ' at', ' of', ' with', ' the', ' a', ' to', ' in', '-', '(')) and len(line) < 80


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
    body_lines = lines[start:]
    nexts = [''] * len(body_lines)
    nxt = ''
    for j in range(len(body_lines) - 1, -1, -1):
        nexts[j] = nxt
        if body_lines[j].strip():
            nxt = body_lines[j].strip()
    for j, raw in enumerate(body_lines):
        line = raw.strip()
        following = nexts[j]
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
        if m and len(line) < 60:
            r['servings'] = r['servings'] or (m.group(1) or m.group(2)).strip()
            continue
        m = H_TIME.match(line)
        if m and len(line) < 60 and section in ('intro', 'ing'):
            k = m.group(1).lower()
            key = 'total' if 'total' in k or k == 'time' else 'prep' if 'prep' in k or 'active' in k else 'cook'
            r[key] = r[key] or m.group(2).strip()
            continue

        if section == 'intro':
            # Unlabelled ingredient lists: switch when a run of ingredient-like lines starts
            if BULLET.match(raw) or looks_like_ingredient(line) or (QTY_START.match(line) and len(line) < 300 and (UNIT.search(line[:40]) or looks_like_ingredient(following))):
                section = 'ing'
            elif len(line) < 30 and not line.endswith('.') and (looks_like_ingredient(following) or QTY_START.match(following)) and intro:
                # a short label right before the first ingredient ("Lamb") is a group heading
                section = 'ing'
                r['ingredients'].append({'h': line.rstrip(':')})
                continue
            else:
                intro.append(line)
                continue
        if section == 'ing':
            sm = NUMSTEP.match(line)
            fb = BULLET.sub('', following)
            if len(line) < 50 and len(fb) > 110 and not QTY_START.match(fb) and not BULLET.match(raw):
                # "Prep" / "Alternate Preparation" style heading right before the method
                section = 'dir'
                if not H_DIR.match(line):
                    r['directions'].append({'h': line.rstrip(':')})
                continue
            if (len(line) > 110 and not QTY_START.match(BULLET.sub('', line))) or (sm and len(line) > 60) or (not BULLET.match(raw) and (len(line) > 160 or (len(line) > 70 and line.endswith('.') and not looks_like_ingredient(line)))):
                section = 'dir'
            elif continues(r['ingredients'], raw, line):
                r['ingredients'][-1] += ' ' + line
                continue
            elif is_subhead(raw) and NUMSTEP.match(following):
                section = 'dir'
                r['directions'].append({'h': line.rstrip(':')})
                continue
            elif is_subhead(raw) or (len(line) < 30 and not line.endswith('.') and not looks_like_ingredient(line)
                                     and not BULLET.match(raw) and looks_like_ingredient(following)):
                r['ingredients'].append({'h': line.rstrip(':')})
                continue
            else:
                r['ingredients'].append(BULLET.sub('', line))
                continue
        if section == 'dir':
            if re.match(r'^step by step\b', line, re.I):
                section = 'notes'
                notes.append(line)
                continue
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
    # very long "ingredients" mean columns of a PDF page got interleaved
    garbled = sum(1 for x in r['ingredients'] if isinstance(x, str) and len(x) > 110)
    score = -2 * min(garbled, 2) + (2 if r['ingredients'] else 0) + (2 if r['directions'] else 0) + (1 if r['description'] else 0) + (1 if r['servings'] else 0) + min(len(text), 20000) / 20000
    if not structured:
        r['text'] = clean(text).strip()
    return r, score


# ---------- categories ----------
CATS = [
    ('Desserts', r'\b(jell-o|gelatin|lime syrup|cake|cookie|pie|tart|brownie|pudding|ice cream|sorbet|gelato|cobbler|crisp|crumble|meringue|mousse|custard|frosting|cheesecake|fudge|truffle|biscotti|macaroon|blondie|dessert|sweet|caramel|chocolate|baked apples|pavlova|shortbread|scone|cupcake|torte|galette|bars?)\b'),
    ('Breads & Baking', r'\b(bread|rolls?|focaccia|biscuits?|muffins?|loaf|brioche|pizza|dough|no-knead|bagels?|crackers?|cornbread|popovers?)\b'),
    ('Breakfast', r'\b(breakfast|pancakes?|waffles?|french toast|granola|omelet|frittata|strata|eggs? benedict|quiche|oatmeal|brunch)\b'),
    ('Appetizers', r'\b(appetizers?|dip|hummus|crostini|bruschetta|toasts?|deviled|canap|tapenade|fondue|mezze|nuts|pâté|pate|gougères|gougeres|cheese balls?|spread|guacamole|baba ganoush|brie|croustades|cheese puffs|gruyère puff|pecans|stuffed dates|dates stuffed|goat chee\w*|fonduta|celery sticks|pigs in a blanket|soufflé|souffle)\b'),
    ('Soups & Stews', r'\b(soup|stew|chowder|bisque|chili|gumbo|bouillabaisse|cioppino|broth|gazpacho|ragout|pho|ramen|minestrone)\b'),
    ('Salads', r'\b(salad|slaw|coleslaw|vinaigrette|niçoise|nicoise|carpaccio)\b'),
    ('Pasta & Grains', r'\b(pasta|spaghetti|linguine|penne|rigatoni|ziti|lasagna|noodles?|gnocchi|risotto|orzo|fettuccine|macaroni|mac and cheese|bolognese|pesto|couscous|farro|quinoa|rice|polenta|bulgur|ravioli|tortellini|carbonara|orecchiette|bucatini|mac|cacio e pepe|sugo|ragu)\b'),
    ('Chicken & Poultry', r'\b(coq au vin|chicken|turkey|duck|cornish|hen|poultry|quail|capon)\b'),
    ('Beef', r'\b(beef|steak|brisket|short ribs?|burgers?|meatloaf|wellington|filet|tenderloin|prime rib|veal|veau|oxtail|bolognese|meatballs|hamburger|leberkäse)\b|bdgveal'),
    ('Pork & Lamb', r'\b(pork|ham|bacon|sausages?|prosciutto|pancetta|chops?|lamb|porchetta|carnitas|ribs|choucroute|chorizo|cassoulet)\b'),
    ('Seafood', r'\b(fish|salmon|tuna|cod|halibut|shrimp|prawns?|scallops?|crab|lobster|clams?|mussels?|oysters?|seafood|swordfish|trout|bass|sole|snapper|anchov|cioppino|bouillabaisse|paella|calamari|squid|octopus|mahi|coquilles)\w*'),
    ('Vegetables & Sides', r'\b(potato(?:es)?|squash|zucchini|eggplant|cauliflower|broccoli|carrots?|beets?|brussels|asparagus|green beans|spinach|kale|cabbage|mushrooms?|corn|peppers?|tomato(?:es)?|onions?|sweet potato(?:es)?|stuffing|dressing|gratin|vegetables?|veggie|leeks?|fennel|artichokes?|peas|fries|latkes|parsnips?|applesauce|cucumbers?|slaws?|hash browns?|radishes)\b'),
    ('Sauces & Condiments', r'\b(sauce|ketchup|mayo|aioli|chutney|relish|jam|pickles?|salsa|gravy|dressing|vinaigrette|butter|marinade|rub|compote|pesto|chimichurri|hollandaise|mayonnaise|pan sauces)\b'),
    ('Drinks', r'\b(cocktail|martini|punch|sangria|lemonade|smoothie|margarita|negroni|spritz|eggnog|cider|tea|coffee|drinks?|glogg|bloody mary)\b'),
    ('Menus & Holidays', r'\b(thanksgiving|christmas|easter|passover|hanukkah|new year|menu|holiday|party|dinner 20\d\d|birthday)\b'),
    ('Pressure Cooker & Slow Cooker', r'\b(pressure cooker|instant pot|slow cooker|crock ?pot|multicooker)\b'),
    ('Sheet Pan', r'\bsheet[- ]pan\b'),
    ('Grilling', r'\b(grill(?:ed|ing)?|barbecue|bbq|smoked?|kebabs?|skewers?)\b'),
]
MAIN = {'Chicken & Poultry', 'Beef', 'Pork & Lamb', 'Seafood'}


# Titles the keyword rules can't place
CATEGORY_OVERRIDES = {
    '1905': ['Salads'], '101 Appetizers': ['Appetizers'], 'Panzanella': ['Salads'], 'Tabbouleh With Apples': ['Salads'], 'Watermelon Salads': ['Salads'],
    '101Appetizers': ['Appetizers'], 'Dips for Super Bowl or Tailgate': ['Appetizers'], 'Gougères': ['Appetizers'],
    'Gruyère Puff': ['Appetizers'], 'Marinated Manchego': ['Appetizers'], 'Marinated Olives': ['Appetizers'],
    'Marinated Olives and Salami': ['Appetizers'], 'Olives With Hot Cheese': ['Appetizers'], 'Pâté': ['Appetizers'],
    'Taralli': ['Appetizers'], 'Taramosalata': ['Appetizers'], 'Ricotta That’s Fresh and Homemade': ['Appetizers'],
    'Daiquiri No2': ['Drinks'], 'Pumpkin Spice Old Fashioned': ['Drinks'], 'Spiked Blackberry-Marjoram Limeade': ['Drinks'],
    'Mango Soft Serve': ['Desserts'], 'Sherbet – The Secret Recipe From Hawaii': ['Desserts'], 'Brandied Dried Fruit': ['Desserts'],
    'Marsala Honey Pears with Gorgonzola from Nigella Express': ['Desserts'], 'Sformata di Ricotta': ['Desserts'],
    'Cranberry': ['Sauces & Condiments'],
    'Kabobs': ['Beef', 'Grilling'], 'Leberkäse': ['Pork & Lamb'], 'Meatball – Of Ikea Fame': ['Beef'],
    'Mexican Birria de Res': ['Beef', 'Soups & Stews'], 'Milanesa Napolitana From Argentina': ['Beef'],
    'Mississippi Roast': ['Beef', 'Pressure Cooker & Slow Cooker'], 'Momofuku Bo Ssam': ['Pork & Lamb'],
    'Smashed Cheeseburger Sliders for a Group': ['Beef'], 'Parasite’s Ram-Don': ['Beef', 'Pasta & Grains'],
    'Italian Picnic Heroes': ['Sandwiches'], 'Monte Cubano Gourmet': ['Sandwiches'], 'Paninnis': ['Sandwiches'],
    'Perfect Steam-Boiled Eggs': ['Breakfast'], 'Poached Egg in a Microwave': ['Breakfast'], 'Savory Dutch Baby': ['Breakfast'],
    'Pommes Darphin': ['Vegetables & Sides'], 'Caillettes': ['Pork & Lamb'], 'Cottage Cheese Egg Bites': ['Breakfast'],
    'Raspberry Sablés with Lemon Curd': ['Desserts'], 'Ratatouille By Melissa Clark': ['Vegetables & Sides'],
    'Tian – Made Ahead With Beautiful Presentation': ['Vegetables & Sides'], 'Vegducken': ['Vegetables & Sides'],
    'Sabudana Khichdi (Maharashtrian Tapioca Pilaf)': ['Pasta & Grains'], 'Asian Takeout': ['Chicken & Poultry', 'Pork & Lamb'],
    'PSU vs Nevada 2025': ['Menus & Holidays'],
    'Cook’s Illustrated’s Recipe of the Year 1993–2015': ['Notes & Guides'], 'Deep Flavor, No Browning': ['Notes & Guides'],
    'Fancy Extra Virgin Olive Oils': ['Notes & Guides'], 'Meat Cooking Temperatures': ['Notes & Guides'],
    'Joel Robuchon': ['Notes & Guides'], '10 Unexpected Ways to Use Your Microwave': ['Notes & Guides'],
}


def categorize(title, folder):
    if title.split('  ')[0] in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[title.split('  ')[0]]
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


# Word files parse most cleanly; PDFs and old PowerPoints lose structure
FORMAT_RANK = {'docx': 5, 'doc': 4, 'pptx': 3, 'txt': 3, 'pdf': 2, 'ppt': 1}

PPT_JUNK = re.compile(r'^(click to edit master .*|second level|third level|fourth level|fifth level|\*|slide \d+|default design|office theme|title and content|<number>|‹#›|\d{1,2}/\d{1,2}/\d{2,4})$', re.I)


QTY_ONLY = re.compile(r'^\s*[\d½¼¾⅓⅔⅛/.\- ]+\s*$')


def strip_junk(text):
    # Word field codes left behind by pages saved from the web
    text = re.sub(r'(?:INCLUDEPICTURE|HYPERLINK)\s+(?:\\l\s+)?"[^"]*"(?:\s*\\\*\s*MERGEFORMATINET)?', ' ', text)
    lines = [l for l in text.split('\n') if not PPT_JUNK.match(l.strip())]
    out = []
    i = 0
    while i < len(lines):
        l = lines[i]
        # Cook's Illustrated pages put the quantity on its own line: "2" / "tablespoons oil"
        if QTY_ONLY.match(l) and l.strip() and i + 1 < len(lines) and lines[i + 1].strip() and not QTY_ONLY.match(lines[i + 1]):
            out.append(l.strip() + ' ' + lines[i + 1].strip())
            i += 2
            continue
        # several numbered steps run together on one line
        if len(l) > 200 and re.search(r'\s{2,}\d{1,2}\.\s', l):
            out.extend(p.strip() for p in re.split(r'\s{2,}(?=\d{1,2}\.\s)', l) if p.strip())
        else:
            out.append(l)
        i += 1
    return '\n'.join(out)


def file_title(name):
    name = unicodedata.normalize('NFC', name)
    name = re.sub(r'^(NYTimes|NYT|BDG|CI)(?=[A-Z0-9])', '', name)
    name = re.sub(r'(?<=\d)(?=[A-Z])', ' ', name).replace('NCheese', "'N Cheese")
    # Sam's file names are the clean titles ("Potatoes – Salt Baked ..."); split CamelCase ones
    t = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name) if ' ' not in name else name
    t = re.sub(r"\s*\((?:[^)]*conflicted copy[^)]*|\d+)\)", '', t)
    return re.sub(r'\s+', ' ', t).strip()


# Files in the folder that aren't recipes (letters, articles, layout notes, the book's own
# index). "code" holds what looks like a private passphrase and must never be published.
EXCLUDE = {
    'code', '_Blank', 'AFOOFT', 'Format', 'Cover Page', 'CoverPage', 'AFOOFT Cover Page', 'AFOOFT Cover Page 3',
    'AFOOFT RECIPES Index', 'AFOOFT Recipes Edited and Printed (Autosaved)', 'AFOOFTDedication',
    'CFA - Incentives Are Dangerously Aligned in Private Markets', 'AI Paris Ideas', 'IKEA Scraps Book',
    'Christmas Alphabet Dictionary', 'Nurses', 'Fresh Market Ketchup Note', 'Oregon 2025', 'Kent State 2024',
    "Cook's Illustrated Annual 2021", "Cook's Illustrated Annual 2022", 'NYTThe best trattoria in Rome', 'NYT - 12 Restaurant Triumphs of 2012',
}
# Reviewed 2026-10-13: entries that aren't recipes (file name without extension -> why)
NOT_RECIPES = {
    '10 Unexpected Ways to Use Your Microwave': 'microwave tips article', 'AFOOFT Dedication': 'the book’s dedication',
    'Braised Red Cabbage With Caraway and Apple': 'empty file, title only', 'Butter Boards': 'trend article, no recipe',
    'Christmas 2021': 'menu of dish names', 'Christmas 2022 (no border)': 'menu of dish names', 'Christmas 2023': 'menu of dish names',
    'Christmas 2024': 'menu of dish names', 'Christmas 2025': 'menu of dish names', 'Christmas Dinner 2018': 'menu of dish names',
    'Thanksgiving 2021': 'menu of dish names', 'Thanksgiving 2022': 'menu of dish names', 'Thanksgiving 2023': 'menu of dish names',
    'Thanksgiving 2024': 'menu of dish names', 'Thanksgiving 2025': 'menu of dish names',
    'Come': 'mealtime grace', 'Graces': 'mealtime graces', 'Dear Cook': 'letter to Cook’s Illustrated',
    'FancyExtraVirginOliveOils': 'olive oil tasting', 'TastingOliveOilMA01': 'olive oil tasting', 'Tasting-BalsamicVinegar': 'balsamic vinegar tasting',
    'Meat Cooking Temperatures': 'temperature chart', 'Steak Cuts (Flat Steaks)': 'article on steak cuts',
    'The Best Pizza in America': 'restaurant profile, no recipe', 'PSU vs Nevada 2025': 'tailgate theme ideas',
    'Race Day Soiree - General Potter Farm': 'event directions', 'Sous Vide Basics': 'two web links',
    'Tomahawk Ribeye Steak vs Lamb Lollipops': 'size notes', 'zz': 'layout scratch file',
}

COMMON = set('the and a of to with in for or until about cup cups tablespoon tablespoons teaspoon teaspoons salt '
             'pepper add heat minutes oil butter large it is on into over at then pan oven cook serve'.split())


def readable(text):
    # OCR'd scans sometimes come back as gibberish; real recipe text is full of common words
    words = re.findall(r'[a-z]+', text.lower())
    return len(words) >= 15 and sum(w in COMMON for w in words) / len(words) >= 0.08


def resolve(rel):
    # the manifest was written on a Mac (NFD names); git stored the files as NFC
    if not rel:
        return None
    for form in ('NFC', 'NFD'):
        p = SRC / unicodedata.normalize(form, rel)
        if p.exists():
            return p
    return None


def main():
    manifest = json.loads((SRC / 'manifest.json').read_text())
    # Recipes deleted on the website stay deleted when the folder is re-read
    edits_path = SITE / 'data' / 'edits.json'
    edits = json.loads(edits_path.read_text()) if edits_path.exists() else {}
    deleted = {unicodedata.normalize('NFC', f) for f in edits.get('deleted', [])}
    items = []
    skipped = []
    for m in manifest:
        if unicodedata.normalize('NFC', m['path']) in deleted:
            skipped.append({'file': m['path'], 'reason': 'deleted on the website'})
            continue
        p = m['path']
        ext = p.rsplit('.', 1)[-1].lower() if '.' in p else ''
        name = os.path.basename(p).rsplit('.', 1)[0]
        folder = os.path.dirname(p)
        if ext in ('jpg', 'jpeg', 'png', 'gif', 'heic', 'tmp', 'prn', 'xlsx', 'csv') or name.startswith('~$'):
            continue
        if name in EXCLUDE:
            skipped.append({'file': p, 'reason': 'not a recipe'})
            continue
        if unicodedata.normalize('NFC', name) in NOT_RECIPES:
            skipped.append({'file': p, 'reason': 'not a recipe: ' + NOT_RECIPES[unicodedata.normalize('NFC', name)]})
            continue
        tp = resolve(m.get('text'))
        if not tp:
            skipped.append({'file': p, 'reason': m.get('error') or 'no text extracted'})
            continue
        text = strip_junk(tp.read_text(errors='replace'))
        if len(text.strip()) < 40:
            skipped.append({'file': p, 'reason': 'no readable text (probably a scan)'})
            continue
        if ext == 'pdf' and not readable(text):
            skipped.append({'file': p, 'reason': 'text unreadable (scan with poor OCR)'})
            continue
        r, score = parse(text, name)
        r['title'] = file_title(name)
        r['file'] = p
        r['folder'] = folder
        r['modified'] = m.get('modified', '')
        r['_score'] = score
        ip = resolve(m.get('image'))
        r['_img'] = str(ip.relative_to(SRC)) if ip else None
        r['_sh'] = shingles(text)
        r['_w'] = set(re.findall(r'[a-z]{3,}', text.lower()))
        r['_tk'] = title_key(r['title']) or title_key(name)
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
        # size ratio keeps a single recipe from merging with a compilation that contains it
        ratio = min(len(A), len(B)) / max(1, max(len(A), len(B)))
        same_title = items[a]['_tk'] == items[b]['_tk']
        if (c >= 0.8 and ratio >= 0.6) or (c >= 0.9 and ratio >= 0.4) or (same_title and c >= 0.4 and ratio >= 0.35):
            pairs.append((a, b, c))
    # Same title saved in two formats (an old slide and a PDF) can share few exact phrases
    # once line wrapping differs, so compare plain word sets for those.
    for ids in by_title.values():
        for x in range(len(ids)):
            for y in range(x + 1, len(ids)):
                wa, wb = items[ids[x]]['_w'], items[ids[y]]['_w']
                if wa and wb and len(wa & wb) / min(len(wa), len(wb)) >= 0.6:
                    pairs.append((ids[x], ids[y], 0))
    for a, b, c in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)

    kept, dupes = [], []
    for g in groups.values():
        g.sort(key=lambda i: (round(items[i]['_score']), FORMAT_RANK.get(items[i]['file'].rsplit('.', 1)[-1].lower(), 0),
                              len(items[i]['_sh']), items[i]['modified']), reverse=True)
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
    shutil.rmtree(rdir, ignore_errors=True)
    rdir.mkdir(parents=True, exist_ok=True)
    (img / 't').mkdir(parents=True, exist_ok=True)
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
        r['categories'] = categorize(r['title'] + '  ' + os.path.basename(r['file']), r['folder'])
        if r['categories'] == ['Other'] and r['title'] not in CATEGORY_OVERRIDES:
            ing = ' '.join(x for x in r['ingredients'] if isinstance(x, str)).lower()
            guess = [name for name, pat in CATS if name in MAIN and re.search(pat, ing, re.I)]
            if len(guess) == 1:
                r['categories'] = guess
            elif re.search(r'\bsugar\b', ing) and re.search(r'\b(flour|cream|chocolate|eggs?)\b', ing) and not guess:
                r['categories'] = ['Desserts']
        if not (r['ingredients'] and r['directions']) and r['categories'] == ['Other']:
            r['categories'] = ['Notes & Guides']
        image = thumb = None
        if r['_img'] and (SRC / r['_img']).exists():
            image, thumb = f'img/{rid}.jpg', f'img/t/{rid}.jpg'
            src = SRC / r['_img']
            fresh = (SITE / thumb).exists() and (SITE / thumb).stat().st_mtime >= src.stat().st_mtime \
                and (SITE / image).exists()
            if fresh:
                pass
            elif Image:
                with Image.open(src) as im:
                    im = im.convert('RGB')
                    big = im.copy(); big.thumbnail((1000, 1000)); big.save(SITE / image, quality=72, optimize=True)
                    w, h = im.size; s = min(w, h)
                    sq = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((128, 128))
                    sq.save(SITE / thumb, quality=70, optimize=True)
            elif shutil.which('sips'):
                # macOS without Pillow (the scheduled Dropbox check runs there)
                subprocess.run(['sips', '-Z', '1000', '-s', 'format', 'jpeg', str(src), '--out', str(SITE / image)], capture_output=True)
                subprocess.run(['sips', '-Z', '160', '-s', 'format', 'jpeg', str(src), '--out', str(SITE / thumb)], capture_output=True)
            else:
                shutil.copy(src, SITE / image); shutil.copy(src, SITE / thumb)
        out = {k: v for k, v in r.items() if not k.startswith('_') and v not in ('', [], None)}
        out['image'] = image
        (rdir / f'{rid}.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
        ing_text = ' '.join(x for x in r['ingredients'] if isinstance(x, str))
        snippet = ', '.join(r['categories'][:2])
        index_out.append({'id': rid, 'f': r['file'], 't': r['title'], 'c': r['categories'], 'img': thumb, 's': snippet,
                          'k': re.sub(r'\s+', ' ', ing_text.lower())[:600]})
    for d, pat in ((img, '*.jpg'), (img / 't', '*.jpg')):
        for f in d.glob(pat):
            if f.stem not in used:
                f.unlink()
    (data / 'index.json').write_text(json.dumps(index_out, ensure_ascii=False, separators=(',', ':')))
    (data / 'duplicates.json').write_text(json.dumps({'duplicates': dupes, 'skipped': skipped}, ensure_ascii=False, indent=1))
    structured = sum(1 for r in kept if r['ingredients'] and r['directions'])
    print(f'files read: {len(items)}  recipes kept: {len(kept)}  structured: {structured}  '
          f'duplicate groups: {len(dupes)}  files excluded as duplicates: {sum(len(d["excluded"]) for d in dupes)}  skipped: {len(skipped)}')


if __name__ == '__main__':
    main()
