# Deploying the frostpine pixel game to the web

`game_pixel.py` is a browser-ready [pygbag](https://pygame-web.github.io/) build of
the tuned **frostpine** world — the walk-around pixel twin of `view_play.py`. It's a
pure View: it only reads `GameSession` state and calls its action methods, so the
sim, rules, contract, and golden master are untouched. This doc is the exact recipe
to turn it into a link a neutral tester can play.

> **Scope:** this MVP ships frostpine only (our one tuned world). The generic
> multi-scenario body is `game.py`; the web build here is deliberately the single
> tuned experience.

---

## 1. Build the static site

```bash
python -m pip install pygbag        # one-time
./build_web.sh                      # -> build/web/
```

`build/web/` is a self-contained static site (`index.html` + a bundled `.apk` of
the Python files + the pygbag/WASM runtime). `build/` is gitignored.

Preview locally before publishing (a plain file:// open will NOT work — WASM needs
an HTTP server):

```bash
python -m http.server -d build/web 8000
# open http://localhost:8000
```

Or build and serve in one step: `./build_web.sh --serve`.

You should see the title screen; **WASD/arrows** to walk, **E/Space** to act at a
fixture, **C** to carry the word, **Enter** at the hut to sleep/end the day.

---

## 2a. Publish on itch.io (primary — works with a private repo)

itch.io hosts HTML5 games directly; no public repo needed.

1. Zip the **contents** of `build/web/` (so `index.html` is at the top level of the
   zip, not inside a `web/` folder):
   ```bash
   (cd build/web && zip -r ../frostpine-web.zip .)
   ```
2. On itch.io: **Dashboard → Create new project**.
3. **Kind of project:** `HTML`.
4. Upload `frostpine-web.zip`, then tick **"This file will be played in the
   browser."**
5. **Embed options:** set the viewport to **928 × 640** (the game's size) and enable
   **"Click to launch in fullscreen"** and **"Mobile friendly"** off (keyboard game).
6. Set visibility to **Draft** or **Restricted** while testing; share the secret
   link with testers. Publish when ready.

First load fetches the Python/WASM runtime (a few MB), so it takes a few seconds;
subsequent loads are cached.

---

## 2b. Publish on GitHub Pages (needs a PUBLIC repo)

Free GitHub Pages serves only public repositories.

1. Build (`./build_web.sh`).
2. Publish the `build/web/` folder to a `gh-pages` branch — e.g. with
   [`ghp-import`](https://pypi.org/project/ghp-import/):
   ```bash
   python -m pip install ghp-import
   ghp-import -n -p -f build/web        # pushes build/web/ to gh-pages
   ```
   (`-n` adds `.nojekyll` so Jekyll doesn't strip the `_`-prefixed runtime files.)
3. On GitHub: **Settings → Pages → Build and deployment → Source: Deploy from a
   branch**, branch **`gh-pages`**, folder **`/ (root)`**.
4. Wait for the deploy, then open `https://<user>.github.io/<repo>/`.

If the page is blank, it's almost always the missing `.nojekyll` (the `-n` flag) or
opening over `file://` instead of `https://`.

---

## Notes / gotchas

- **First load is slow, then cached** — pygbag ships a CPython-in-WASM runtime.
- **Keyboard focus** — the player may need to click the canvas once so it receives
  key events; the title screen's "press any key" covers this.
- **No disk save/load in the browser** — the browser filesystem is virtual, so this
  build has no save/load (the desktop dashboard `game.py` keeps that). The end-of-
  year counterfactual (two ghost simulations the brain runs) is fenced behind a
  painted "tallying…" beat so the tab never freezes on a blank frame.
- **Determinism** — unchanged; the same seed yields the same year in the browser as
  on desktop, because the sim is stdlib-only and runs identically under Pyodide.
- **Rebuild after any change** — re-run `./build_web.sh` and re-upload; there is no
  hot reload for the hosted build.
