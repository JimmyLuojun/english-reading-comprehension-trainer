# Visual Refresh (审美升级) — Executable Plan

Status: implemented (2026-06-18)

Lift the default look from "generic SaaS admin panel" to a calmer, editorial feel, **without** a layout rewrite or new dependencies. Reference: the `editorial` theme on https://jimmyluo.pages.dev/ (serif display headings, a distinctive low-saturation accent, a 3-level text scale, softly tinted surfaces, a unified radius scale). All changes ride the existing CSS-variable layer in `app/web/views/styles.py` — the same lever that delivered the sepia theme — so the surface area stays small.

Implementation note (2026-06-18): Tier 1 and Tier 2 are implemented, plus the low-risk Tier 3 nav translucency / selection-color polish. The implementation keeps semantic reading highlights unchanged, mirrors new variables into `:root` and `html[data-theme="sepia"]`, and does not add external fonts, layout changes, or a new theme toggle.

This is an **upgrade of the default theme** (edit `:root`), not a new theme. The existing `html[data-theme="sepia"]` 护眼 theme must keep working unchanged.

## Scope decision (vs `docs/design.md` §0)

§0 defers "字号 / 行距 / 主题切换（夜间 / 高对比）". This plan touches **none** of those: no font-size/line-height user controls, no dark/night mode, no new theme toggle. It only re-tunes the existing default palette/typography. No §0 edit required.

## Risks to avoid

1. **Don't break the sepia theme.** Every new variable introduced in `:root` (`--text-dim`, `--radius`, `--radius-sm`, `--radius-pill`, `--shadow`, etc.) must **also** be defined in the `html[data-theme="sepia"]` block, or sepia will fall back to wrong/undefined values. Treat the two blocks as one contract: any var added to one is added to both.
2. **Don't put serif everywhere.** Serif headings read as "editorial"; serif in dense tables, forms, the selection toolbar, and the analysis panel body hurts scanning. Scope `--font-display` to `h1`, `h2`, `.reader-title` only. Body / tables / panel text stay sans.
3. **No external font dependency.** This is a local, single-user app (productization-roadmap: 自用先行). Do **not** add a Google Fonts `<link>` — it adds a network dependency, slows offline/weak-network first paint, and can flash. Use system serifs already available: `Georgia, "Noto Serif SC", "Songti SC", serif` (the same family `.reader-para` already uses). Zero new deps.
4. **Don't touch semantic colors.** Marked-sentence yellow (`#ffe58a`), selection/target blue (`#bfdbfe`, `#2563eb` on `.translated`/`.analyzed`), word-card amber, error red (`--danger*`), ok green (`--ok`) all carry meaning. Re-skin only `--accent` / `--accent-strong` and the neutral surface/text/line/shadow vars. Leave the highlight literals alone.
5. **One variable layer at a time.** Land Tier 1 (vars: text scale + accent + radius + display font), verify sepia still renders and the full suite passes, *then* Tier 2 (surfaces/shadow/spacing). Don't batch all tiers into one commit.
6. **No untested merge.** Update/extend `tests/web/views/test_styles.py` and run `ruff check app/web` (project rule for web changes).

## Files to change

### `english-reading-trainer/app/web/views/styles.py` — the only source file

All edits are inside `_css()`. Mirror every new var into both the `:root` block and the `html[data-theme="sepia"]` block.

#### Tier 1 — variables (highest payoff, smallest change)

**a) 3-level text scale.** Add `--text-dim` between `--text` and `--muted`.

```css
/* :root */
--text: #1f2937;
--text-dim: #4b5563;   /* new: secondary body text */
--muted: #667085;      /* keep: weakest level */

/* html[data-theme="sepia"] */
--text: #463a28;
--text-dim: #6b5c40;   /* new */
--muted: #8a7a5c;
```

Then promote lede/description text currently using `var(--muted)` to `var(--text-dim)` where it is *secondary body* (not a faint label) — e.g. `.reader-chapter`, `.analysis-text` captions. Leave true labels (`.panel-kicker`, `.metric span`, form labels) on `--muted`.

**b) Distinctive accent.** Replace the generic blue with the editorial teal (one accent threaded through the whole UI):

```css
/* :root — applies to sepia too, since sepia does not override accent */
--accent: #0f8f83;
--accent-strong: #0c7268;
```

Note: `--accent` drives nav-active, primary buttons, links, focus rings, `.analysis-codes`, etc. Changing only these two vars re-skins all of them. The teal reads fine on both the light and the warm sepia background. (If teal is not wanted, any single low-saturation hue works — pick one and apply both vars.)

**c) Unified radius scale.** Add a radius scale and replace scattered literals:

```css
--radius: 8px;
--radius-sm: 6px;
--radius-pill: 999px;
```

Replace `border-radius` literals across the file: the common `6px` → `var(--radius-sm)`, card/panel `8px`/larger → `var(--radius)`, `999px` → `var(--radius-pill)`. Skip tiny functional radii (`2px`/`3px` on highlight chips) — leave as-is.

**d) Serif display font (system fonts only).** Add and apply narrowly:

```css
--font-display: Georgia, "Noto Serif SC", "Songti SC", serif;
```

Apply to `h1`, `h2`, `.reader-title` only:
```css
h1, h2, .reader-title { font-family: var(--font-display); }
```
Bump sizes slightly for editorial weight: `h1` 26px → 30px. Keep `font-weight` modest (500–600) so serif headings look set, not bold-shouty.

#### Tier 2 — surfaces, shadow, spacing (do after Tier 1 is verified)

**e) Soft shadow + lighter borders.** Add a shadow var (both blocks) and apply to elevated containers:

```css
/* :root */
--shadow: 0 18px 50px rgba(20, 30, 40, 0.08);
/* sepia */
--shadow: 0 18px 50px rgba(70, 55, 25, 0.10);
```

Apply `box-shadow: var(--shadow)` to `.band`, `.metric`, `table`, and keep the existing panel shadows. Optionally soften `--line` one notch (e.g. `#e3e8ef`) so cards float on the shadow rather than being boxed by a hard border.

**f) More breathing room.** Increase vertical rhythm: `h2` top margin 24px → 32px; `main` bottom margin / section gaps +~25%. Whitespace is most of the "premium" feel — change spacing, not structure.

**g) Kicker polish.** `.panel-kicker` already uppercases; add `letter-spacing: .12em` and confirm it uses `--muted`. Gives the editorial mono-subtitle texture without a mono font.

#### Tier 3 — micro-interactions (optional, lowest priority)

**h)** `::selection { background: var(--accent); color: #fff; }` globally.
**i)** Unify `transition` on buttons/cards; add a subtle hover lift (`transform: translateY(-1px)`) or border brighten on `.metric`/`.band`.
**j)** Extend the reader-nav `backdrop-filter: blur` treatment to the global `nav` (translucent `--nav-surface` already exists) so every page gets the frosted sticky bar.

## Tests (no untested merge)

Extend `english-reading-trainer/tests/web/views/test_styles.py`:

- Assert `_css()` defines `--text-dim`, `--radius`, `--radius-sm`, `--radius-pill`, and `--font-display` in **both** the `:root` and `html[data-theme="sepia"]` blocks (guards Risk 1 — the var-parity contract). A small helper that slices each block and checks each new var appears in both is the cleanest assertion.
- Assert the new accent value(s) are present and the old `#2563eb`/`#1d4ed8` no longer appear **as the `--accent`/`--accent-strong` definitions** (they may still legitimately appear in semantic highlight rules like `.translated` — scope the assertion to the var definitions, not a global substring ban).
- Assert serif `--font-display` is applied to `h1`/`.reader-title` and that body/`table` font is unchanged (guards Risk 2).
- Keep the existing sepia assertions (`html[data-theme="sepia"]` block, `--bg: #f3ead6`, etc.) passing.

`tests/web/views/test_layout.py` needs no change unless Tier 3 (j) alters nav markup.

## Verification

- `english-reading-trainer/.venv/bin/python -m pytest tests/` (full suite). Report the actual `sys.executable`.
- `english-reading-trainer/.venv/bin/python -m ruff check app/web`.
- Manual: load Dashboard / Cards / Reader → headings render serif, accent is the new hue everywhere (nav-active, primary buttons, links, focus), cards look softer. Toggle 护眼 → sepia still correct, new vars resolved, no white glare spots, highlights still legible. Reload → sepia persists with no FOUC.
- Land per Tier (separate commits): Tier 1 → verify → Tier 2 → verify → Tier 3 optional. Update `STATUS.md` after the work.

## Explicitly out of scope (deferred)

- Dark / night mode and high-contrast theme (still excluded by §0; needs a full hard-coded-color audit).
- User-adjustable font size / line-height controls (§0).
- Web fonts via external CDN / self-hosted woff2 bundling (only revisit if system serifs prove insufficient).
- Any layout / DOM-structure change, new components, or JS framework. This plan is CSS-variable + a few selector edits only.
