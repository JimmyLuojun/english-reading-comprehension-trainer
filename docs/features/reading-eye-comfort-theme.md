# Reading Eye-Comfort (护眼) Theme — Executable Plan

Status: implemented

Add a single warm "米黄/sepia" reading theme plus a header toggle, persisted per browser, to reduce screen glare during long reading. Default stays the current light theme. This is the smallest change that delivers eye comfort without a full theming system.

## Scope decision (reverses a prior exclusion)

`docs/design.md` §0 (recorded 2026-06-15) excluded "字号 / 行距 / 主题切换(夜间 / 米黄 / 高对比)". This plan implements the **米黄/护眼** part of that exclusion. As part of execution, update §0 so the document no longer claims it is out of scope (mark 米黄 theme as implemented; 夜间 / 字号 / 行距 stay deferred).

Implementation note: §0 now marks 米黄 / sepia as implemented and keeps 夜间 / 高对比 / 字号 / 行距 deferred.

## Risks to avoid

1. **Flash of wrong theme (FOUC).** Applying the theme after `<body>` paints means the first frame is the bright default, then flips — worse than no theme. The theme attribute must be set on `document.documentElement` synchronously in `<head>`, **before** the `<style>` block.
2. **Hard-coded surface colors won't follow the theme.** `styles.py` is mostly `:root`-variable driven, but a few surface colors are written as literal hex (e.g. `#ffffff` ~L65, table header `#f2f4f7` ~L147). On a warm background these stay bright white and become glare spots. Convert only those **surface** literals to a variable. Do **not** touch semantic highlight colors (marked-sentence yellow, selection blue) — they read fine on a warm background and carry meaning.
3. **Do not add a dark/night mode here.** Dark mode breaks every hard-coded light value (light-blue highlights, white cards) and needs a full hex audit — much larger surface and regression risk. The sepia theme is compatible with the existing literal light colors; that is what keeps this change small. Defer dark mode.
4. **Preference must be global, not per page.** Store it in `localStorage` and inject the bootstrap + toggle once in the shared `layout.py`, never per route.
5. **No untested merge.** Add/adjust tests for `styles.py` and `layout.py`, and run `ruff check app/web` (project rule for web changes).

## Files to change

### 1. `english-reading-trainer/app/web/views/styles.py`

Inside `_css()`, immediately after the `:root { … }` block, append a theme-override block that only re-binds variables (no layout rules):

```css
html[data-theme="sepia"] {
  color-scheme: light;
  --bg: #f3ead6;        /* 米黄底，替代近白 #f7f8fa */
  --surface: #faf4e4;   /* 暖色卡片，替代纯白 */
  --line: #e2d8be;
  --text: #463a28;      /* 暖深灰，非纯黑 */
  --muted: #8a7a5c;
}
```

Then convert the small number of hard-coded **surface** literals so they follow the theme:
- The `#ffffff` element background (~L65) and the table header `#f2f4f7` (~L147) → `var(--surface)`. If a second distinct surface shade is needed, add a `--surface-alt` to both `:root` and the `[data-theme="sepia"]` block rather than another literal.
- Leave `--accent` / `--ok` / `--danger*` and all highlight/selection colors unchanged.

### 2. `english-reading-trainer/app/web/views/layout.py`

In `_html_page`:

- Insert a pre-paint bootstrap script in `<head>`, **before** `<style>{_css()}</style>`:
  ```html
  <script>try{var t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>
  ```
- Add a toggle button at the end of `<nav>` (after the Profile link) that flips between default and `sepia`, writes `localStorage`, and sets/clears `data-theme` live:
  ```html
  <button type="button" id="theme-toggle" onclick="(function(){var d=document.documentElement,s=d.dataset.theme==='sepia';if(s){delete d.dataset.theme;localStorage.removeItem('theme');}else{d.dataset.theme='sepia';localStorage.setItem('theme','sepia');}})()">护眼</button>
  ```
- Add minimal styling for `#theme-toggle` if the nav layout needs it (reuse the existing button class if one exists, e.g. push it to the right with `margin-left:auto`); keep it consistent with the current nav.

Because `layout.py` is the single shared shell, this covers every page (Dashboard / Books / Import / Cards / Review / Profile / Reader) at once.

## Tests (no untested merge)

- `tests/web/test_styles.py` (or the existing styles test): assert `_css()` contains `html[data-theme="sepia"]` and the sepia variables (`--bg: #f3ead6`, `--surface: #faf4e4`). Assert the previously hard-coded surface literals are gone (no stray `#ffffff` / `#f2f4f7` in the converted rules).
- `tests/web/test_layout.py` (or the existing layout test): assert the rendered page contains the pre-paint bootstrap script and the `id="theme-toggle"` button, and that the bootstrap appears before the `<style>` block.
- Mirror any test that snapshots the nav markup / page `<head>`.

## Verification

- `english-reading-trainer/.venv/bin/python -m pytest tests/` (full suite).
- `english-reading-trainer/.venv/bin/python -m ruff check app/web`.
- Manual: load any page, click 护眼 → warm background, reload → preference persists with no white flash, click again → back to default. Confirm marked-sentence and selection highlights stay legible on the warm background.
- Update `docs/design.md` §0 (米黄 theme implemented) and add a line to `STATUS.md`.

## Explicitly out of scope (deferred)

- Dark / night mode and high-contrast theme (needs a full hard-coded-color audit).
- Font size / line-height controls.

Add these only on real need, batched so the CSS-variable audit is paid once.
