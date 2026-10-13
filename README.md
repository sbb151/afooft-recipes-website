# AFOOFT Recipes

A cooking-friendly website for the AFOOFT recipe collection. It works on a phone or laptop,
can be added to a phone's home screen, keeps recipes you've opened available offline, and can
keep the screen awake while you cook.

## How the site is built

1. The recipe files live in Dropbox (`/AFOOFT Recipes`). Their text and one photo per file were
   extracted on a Mac into the private repo `sbb151/afooft-recipes-source`
   (`manifest.json`, `text/`, `images/`).
2. `python3 tools/build.py <path to afooft-recipes-source> .` parses each file into title,
   ingredients, directions and notes, assigns categories, drops duplicate recipes (keeping the most
   complete copy), and writes `data/`, `img/` and `data/duplicates.json` (what was left out and why).
3. The site itself is static: `index.html`, `app.js`, `style.css`, `sw.js`. GitHub Pages serves it
   from the `main` branch.

To add new recipes: re-run the extraction for the new files, then re-run `tools/build.py` and commit.
