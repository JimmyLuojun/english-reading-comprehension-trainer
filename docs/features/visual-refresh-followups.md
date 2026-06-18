# Visual Refresh Follow-ups (主按钮 / 数字对齐 / 站点标识) — Executable Plan

Status: planned

Three small, high-payoff polish items on top of the implemented [visual refresh](visual-refresh.md). All are CSS-variable / single-selector / `<head>` edits — no layout change, no new dependency, no new static file. Builds on the teal `--accent` and the `--font-display` / radius / shadow scale already in `styles.py`.

1. **Filled primary button** — give the main CTAs (Open/Read book) a real filled-accent style so visual hierarchy reads. *Highest payoff.*
2. **Tabular figures for metrics** — dashboard numbers align and stop jittering.
3. **Site identity** — an inline-SVG favicon (zero new file) and a tidied `<title>`.

## Risks to avoid

1. **The shared hover rule must not make filled-primary text invisible.** `styles.py` currently has (around L87):
   ```css
   nav a.active, .button.primary, button:hover, .button:hover {
     border-color: var(--accent); color: var(--accent-strong);
   }
   ```
   This sets `.button.primary` text to `--accent-strong` (dark teal). A new filled rule must come **after** this line (same specificity → later wins) and set `color: #fff`, plus its own `:hover`. If placed before, the filled background gets dark teal text on a teal fill — unreadable.
2. **Don't let filled-primary leak into the dark toolbar/panels.** `.selection-toolbar button` and the word/translation panels have their own light-on-dark button styling. Today `.button.primary` is used only in `books.py` (read link) and `imports.py` ("Open existing book") — both on light surfaces, none inside the toolbar/panel. Keep it that way; if a `.primary` is ever placed inside `.selection-toolbar`, it needs a scoped override. Don't restyle toolbar buttons here.
3. **favicon must be an inline data-URI SVG, properly URL-encoded.** Use `<link rel="icon" href="data:image/svg+xml,...">` so there is no new static file and no `/static` route (consistent with 自用先行, zero deps). The `#` in any hex color and the `<`/`>`/`"` in the SVG **must** be percent-encoded (`%23`, `%3C`, `%3E`, `%27`) or the browser silently drops the icon. Prefer `'` (then `%27`) over `"` inside the SVG to keep the HTML attribute clean.
4. **Don't touch semantic / theme colors.** Filled primary uses `var(--accent)` (themed: teal in both default and sepia — reads fine on the warm background). `tabular-nums` is numeric-only. Leave highlight literals, `--danger*`, `--ok` alone.
5. **No untested merge.** Extend `tests/web/views/test_styles.py` and `tests/web/views/test_layout.py`; run `ruff check app/web` (layout.py changes).

## Files to change

### 1. `english-reading-trainer/app/web/views/styles.py`

**a) Filled primary button.** Add a dedicated rule **after** the existing `nav a.active, .button.primary, ...` rule (so source order wins). Reuse the radius/transition already on the base button:

```css
.button.primary, button.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.button.primary:hover, button.primary:hover {
  background: var(--accent-strong);
  border-color: var(--accent-strong);
  color: #fff;
}
```

(Keep the base `transition` from the `.button` rule. Do not change the non-primary hover behavior.)

**b) Tabular figures.** Change the metrics number rule:

```css
.metric strong { font-size: 24px; font-variant-numeric: tabular-nums; }
```

### 2. `english-reading-trainer/app/web/views/layout.py`

In the `<head>` of `_html_page` (currently `<meta>`, `<title>`, bootstrap `<script>`, `<style>`):

**c) Inline-SVG favicon.** Add one `<link rel="icon">` line with a percent-encoded data-URI SVG — a single character mark on an accent square (mirrors the reference site's letter-mark idea, teal to match `--accent`). Example mark "读" (or "E") on a teal rounded square, e.g.:

```html
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%27http://www.w3.org/2000/svg%27 viewBox=%270 0 32 32%27%3E%3Crect width=%2732%27 height=%2732%27 rx=%276%27 fill=%27%230f8f83%27/%3E%3Ctext x=%2716%27 y=%2722%27 font-family=%27Georgia,serif%27 font-size=%2718%27 font-weight=%27600%27 fill=%27%23ffffff%27 text-anchor=%27middle%27%3E读%3C/text%3E%3C/svg%3E">
```
Verify the encoding renders (no raw `#`, `<`, `>`, `"` inside the `href`). Pick the mark character with the user if unsure; "读" or "E" are both fine.

**d) Tidy `<title>` (optional, low risk).** Current: `{title} - English Reading Trainer`. Optionally switch the separator to a middot and keep the page name first for tab legibility, e.g. `{title} · 阅读训练`. Keep `_escape(title)`. Skip if the user prefers the current English suffix.

These live in the single shared `_html_page`, so they cover every page at once.

## Tests (no untested merge)

`tests/web/views/test_styles.py`:
- Assert a filled primary rule exists: `_css()` contains `.button.primary` followed by `background: var(--accent)` and `color: #fff`, and a `.button.primary:hover` with `background: var(--accent-strong)`.
- Assert the filled rule appears **after** the shared `nav a.active, .button.primary` rule (compare `str.index` positions — guards Risk 1).
- Assert `.metric strong` contains `font-variant-numeric: tabular-nums`.

`tests/web/views/test_layout.py`:
- Assert the rendered page `<head>` contains `rel="icon"` and `data:image/svg+xml`, that it appears before `</head>`, and that the `href` contains no raw `#`/`<`/`>` (i.e. encoding survived — guards Risk 3).
- If (d) is done, update the existing `<title>` assertion to the new format; otherwise leave it.

## Verification

- `english-reading-trainer/.venv/bin/python -m pytest tests/` (full suite). Report the actual `sys.executable`.
- `english-reading-trainer/.venv/bin/python -m ruff check app/web`.
- Manual: Books / Import pages → primary CTA is a filled teal button, clearly dominant over secondary buttons, readable text, sensible hover. Dashboard → metric numbers align on a column. Browser tab → favicon shows. Toggle 护眼 → primary stays teal-on-warm and readable; nothing else regresses.
- Update `STATUS.md` after the work.

## Explicitly out of scope (deferred)

- A full button-hierarchy system (secondary/ghost/sizes variants) — only the existing `.primary` is being filled.
- Restyling toolbar / analysis-panel buttons (they have their own dark-surface design).
- Any new static-asset pipeline, web fonts, or `/static` favicon file.
- Dark/night mode, font-size controls (still §0-deferred).
