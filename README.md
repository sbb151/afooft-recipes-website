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

## Adding, editing and deleting on the site

The ＋ button adds a recipe, and ✎ and 🗑 on a recipe edit or delete it. Saves go to `data/edits.json`
(and photos to `img/u/`) through the GitHub API, using a fine-grained GitHub key entered once per device
under "Editing settings". The key never leaves that device except to talk to GitHub. Deleting never touches
Dropbox, and `build.py` keeps deleted files out of later rebuilds.

## Daily Dropbox check

`tools/mac/install.sh` (run once on the Mac that syncs Dropbox) sets up a launchd job that runs
`tools/mac/afooft_sync.py` every day at 7:00: it reads new or changed files in `AFOOFT Recipes`,
updates the source repo, rebuilds the site and pushes it. Log: `~/afooft-sync/sync.log`.
`bash install.sh remove` turns it off.
