# UI 一致性与密度优化 (sepia 调浅 / 统一页头 / 表格精修) — Executable Plan

Status: planned (2026-06-18)

Next landing on top of the shipped [visual refresh](visual-refresh.md) and its
[follow-ups](visual-refresh-followups.md). Goal: lift the feel from "套了一层米黄色护眼滤镜的管理后台"
to a calm, consistent reading tool — **without** a layout rewrite, new components, or new dependencies.
Still pure CSS-variable + a small shared header helper + a few selector edits, on the same lever as the
sepia theme and visual refresh.

The work lands in **5 verifiable steps**, each shipping its own test additions, `ruff check app/web`,
and full `pytest`.

## 评估结论（对原始判断的校准）

方向正确，但有两处必须先纠正，否则会改错地方、回退已发版本：

1. **"整屏泛黄"是 sepia 护眼主题，不是默认主题。** 默认 `:root` 已经是冷调近白
   （`--bg:#f6f8f5` / `--surface:#fffefa` / `--surface-alt:#eef4f1`），只有
   `html[data-theme="sepia"]` 是重赭石色（`#f3ead6`/`#faf4e4`/`#efe3c8`）。所以"调浅"
   **只动 sepia 块**；碰 `:root` 会把刚发布的 visual-refresh 冷白调坏。
2. **页面骨架已经是 markup 级统一的。** 六个 router（dashboard / books / books 详情 / cards /
   review / profile / import / cards-sources）已经在用同一段
   `<section class="toolbar"><div><h1>+<p class="muted"></div>[右侧按钮]</section>`。
   所以"统一页头"不是重排，而是 (a) 把这段重复 markup 抽成一个 `_page_header()` helper 锁死一致性、
   防止后续漂移；(b) 真正的"每页在重新布局"感来自右侧操作按钮有无不一致 + 内容宽度一刀切。

其余判断（表格容器抢戏、Delete 太抢眼、Import 输入框廉价、Review 答案区拥挤、落地顺序）都成立，按其顺序执行。

## Risks to avoid（先列规避项）

1. **不要碰 `:root` 的中性色。** 泛黄问题在 sepia。只改 `html[data-theme="sepia"]` 的
   `--bg` / `--surface` / `--surface-alt` / `--line` / `--shadow` 的**取值**，不新增变量、不动 `--accent*`、
   不动 `--text*`。变量奇偶性合约（每个变量在两个块都存在）因此自动保持。
2. **不要全局加宽。** 当前 `main` 是 `min(1180px, …)`，且 reader 的
   `@media (min-width: 1180px)` 断点与 `padding-right: var(--analysis-panel-width)` 依赖这个宽度。
   **不要把全局宽度提到 1280px**（原判断里的数字）。Books/Cards/Review/Dashboard 维持现有 1180；
   只给 Import/Profile 加一个更窄的 `body.narrow` 修饰类。reader 页规则一律不动。
3. **表格阴影只从 `table` 摘掉，不要动 `.band`/`.metric`。** 卡片该"浮"，数据表该像"纸"。
   `--shadow` 仍然给卡片用；表格改成无阴影 + 细边框 + radius。
4. **Delete 弱化只作用于表格操作列。** `button.danger` 还被 books 删除、reader 选词 toolbar
   （`.selection-toolbar button.danger` 有自己的覆盖）复用。把默认 danger 改成全局静音会丢失别处的危险语义。
   只在表格单元格内 `td button.danger` / `td .button.danger` 静音，hover 才变红。
5. **Review 不重构。** 答案按钮已经是 flex 横排，拥挤来自列预算不是结构。只压缩按钮 padding + 给
   Review item 列留宽 + 保住 Reveal。不换组件、不改 `/review` 表结构。
6. **Cards 不过度美化。** 它本质是管理表格；本轮对它的唯一改动是表格密度/hover/Delete 权重，不加装饰。
7. **无测试不合入。** 每步同步改/加 `tests/web/views/test_styles.py`、`test_layout.py`，跑
   `ruff check app/web` + 全量 `pytest`。注意 Step 1/3 会**改到现有断言里的硬编码 hex 与 `th` 规则字符串**，必须同步更新（见各步）。

---

## Step 1 — 调浅 sepia 色板（仅 `html[data-theme="sepia"]` 块）

目标"温暖白纸"，不是"整页羊皮纸"。**护眼优先**的取标原则（不是单纯调浅）：
①保留暖调（少蓝光，护眼主因）；②适度亮度，**不**调到接近纯白以免眩光；
③纸面 `--surface` 比桌面 `--bg` 亮一档，让纸张浮起、正文对比清晰（羊皮纸最差的就是对比度）；
④`--surface-alt`（表头/hover）大幅降饱和，强黄本身易疲劳。`styles.py` 的 sepia 块改取值：

```css
/* html[data-theme="sepia"] */
--bg: #efe6d3;          /* was #f3ead6 — 暖"桌面"，比纸面暗一档 */
--surface: #faf5ea;     /* was #faf4e4 — 暖白"纸面"，不接近纯白（避免眩光） */
--surface-alt: #f1e9d7; /* was #efe3c8 — 表头/hover 底色大幅降饱和 */
--line: #e6dcc6;        /* was #e2d8be — 更柔 */
--shadow: 0 16px 40px rgba(70, 55, 25, 0.07);  /* was 0 18px 50px …0.1 — 更轻 */
```

（`--text*` / `--accent*` / `--accent-line` / `--accent-soft` / radius / font 不变。
正文仍是深暖棕 `--text: #463a28`，在 `#faf5ea` 上对比度仍达 AAA，辨认不费力。）

**测试更新（必改，否则红）**：`test_css_contains_sepia_theme_variables_and_surface_bindings`
里硬编码了 `--bg: #f3ead6` / `--surface: #faf4e4` / `--surface-alt: #efe3c8`（约 L50-52），改成新值。
其余 `background: var(--nav-surface)` / `background: #ffffff not in css` 等断言不受影响。

**验收**：切到护眼 → 背景是暖白纸而非羊皮纸，表头不再发黄发重；默认主题视觉无变化。

---

## Step 2 — 统一页头 + 内容宽度 + 节奏

**a) 抽 `_page_header` helper（纯重构，输出逐字节一致）。** 在 `layout.py` 新增：

```python
def _page_header(title: str, subtitle: str = "", actions: str = "") -> str:
    sub = f'<p class="muted">{_escape(subtitle)}</p>' if subtitle else ""
    right = actions  # 已是 HTML（按钮/链接），调用方负责转义
    return (
        '<section class="toolbar"><div>'
        f"<h1>{_escape(title)}</h1>{sub}</div>"
        f"{right}</section>"
    )
```

把 6 个 router（dashboard / books 列表 / books 详情 / cards / review / profile / imports `_import_forms`+`_duplicate_page` / cards `_word_card_sources_page`）里手写的 `<section class="toolbar">…` 全部换成 `_page_header(...)`。
注意 dashboard 标题保留 `Reading Trainer`，books 详情标题是动态书名。这是 churn-free 重构，渲染结果不变 → 现有页面快照/字符串断言应继续通过；若某处空格不同导致断言失败，以 helper 输出为准更新断言。

**b) Import/Profile 收窄。** `_html_page` 已支持 `page_class`；给这两页传 `page_class="narrow"`
（import.py 的 `_html_page("Import", …)`、profile router 的两处）。`styles.py` 加：

```css
body.narrow main { width: min(760px, calc(100vw - 32px)); }
```

（默认 `main` 与 reader 规则都不动；`.reader-page main { width:100% }` 仍在后面胜出。）

**c) 节奏锁定。** 所有页头现在走同一 helper，`.toolbar { margin-bottom: 18px }` 统一。
可选编辑：给页头加一条细分隔线增强编辑感——`.toolbar { padding-bottom: 14px; border-bottom: 1px solid var(--line); }`（低风险，先做也行不做也行）。

**测试**：`test_layout.py` 加 `_page_header` 输出断言（含/不含 subtitle、含 actions 三种）；`test_styles.py` 加 `body.narrow main` 宽度规则断言。

---

## Step 3 — 表格密度 / 行 hover / 数字列 / 操作列 / Delete 权重

`styles.py`：

```css
/* 表格像纸，不浮 */
table { box-shadow: none; }

/* 行 hover 便于扫读（sepia surface-alt 已调浅，hover 很克制） */
tbody tr:hover { background: var(--surface-alt); }

/* 数字列对齐（tabular-nums 只影响数字，对文本无害） */
td, th { font-variant-numeric: tabular-nums; }

/* 表头更精致：小号大写 + 字距 */
th {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

/* Delete 等危险按钮只在表格操作列里弱化，hover 才变红 */
td button.danger, td .button.danger {
  border-color: var(--line);
  color: var(--muted);
}
td button.danger:hover, td .button.danger:hover {
  border-color: var(--danger);
  color: var(--danger);
  background: var(--danger-bg);
}
```

注意：`th` 已有 `color: var(--muted); font-weight: 600; background: var(--surface-alt);`——
新增的 `font-size/transform/letter-spacing` 与之合并即可（不要重复声明已有属性）。

**测试更新（必改）**：`test_css_contains_sepia_theme_variables_and_surface_bindings` 里精确断言了
`"th { color: var(--muted); font-weight: 600; background: var(--surface-alt); }"`（L54）——
改 `th` 规则后该字符串失配，需更新为新规则文本或拆成多个 `in css` 子串断言。
新增断言：`table { … box-shadow: none`、`tbody tr:hover`、`td button.danger` 静音 + hover 变红。

**验收**：Books/Cards 表格不再"浮"在大阴影上；Delete 默认静音、hover 变红；数字列对齐；表头精致。

---

## Step 4 — Review 行布局（不重构）

`styles.py`，只压缩 + 留宽：

```css
.answer-form { gap: 6px; flex-wrap: nowrap; }
.answer-form button { padding: 4px 10px; }
```

`review.py` 的表格给 Review item 列留宽：`<th>` 上加 `class="review-item-col"`，CSS
`.review-item-col { width: 40%; }`（或给答案列 `white-space: nowrap` 让三个按钮锁定一行，让 item 列吃掉剩余宽度）。保住 `▶ Reveal` 弹层。

**测试**：`test_styles.py` 断言 `.answer-form button { padding: 4px 10px` 与列宽规则；`review.py` 若加 class，`test` 中相应渲染断言更新。

---

## Step 5 — Import 两个任务卡片

`imports.py` 的 `_import_forms`：两个 `.band` 保留为上下两张清晰任务卡，去掉"廉价"感——
按钮不再铺满整行、输入不再全宽贴边：

```css
.stack-form { gap: 8px; }                 /* 已有，保持 */
.stack-form input:not([type=file]) { max-width: 420px; }
.stack-form textarea { max-width: 640px; }
.stack-form button { justify-self: start; }   /* grid 下按钮左对齐、按内容宽 */
```

页面本身走 Step 2 的 `body.narrow`，两张卡片在窄列里成为明确的两个任务。
标题/副标题保持现有文案（"Upload file" / "Paste text"）。

**测试**：`test_styles.py` 断言 `.stack-form button { justify-self: start` 与 input `max-width`。

---

## Verification（每步都跑）

- `english-reading-trainer/.venv/bin/python -m pytest tests/`（全量）。报告实际 `sys.executable`。
- `english-reading-trainer/.venv/bin/python -m ruff check app/web`（防止 helper 抽取后的未用导入/缺名）。
- 手动：切护眼 → 暖白纸不泛黄；各页页头同构；表格像纸不浮、Delete hover 才红、数字对齐；
  Review 三个答案按钮一行、item 列够宽；Import 两张任务卡、按钮按内容宽。
- 完成后更新 `STATUS.md`；在 `docs/design.md` §3 把本文件状态从 planned 改 implemented。

## 落地顺序（与原判断一致，逐步验证）

1. 调浅 sepia 色板（Step 1）→ 验证 → 2. 统一页头 + 收窄 Import/Profile（Step 2）→ 验证 →
3. 表格密度/hover/数字/Delete（Step 3）→ 验证 → 4. Review 行（Step 4）→ 5. Import 任务卡（Step 5）。
每步独立 commit，便于回看审美增量。

## Explicitly out of scope（本轮不做）

- 默认 `:root` 中性色/强调色再设计（默认已是冷白，无需动）。
- Review/Cards 的组件级重构、新表结构、新 Review 流程。
- 夜间/高对比主题、字号/行距控件（仍由 §0 排除）。
- 新静态资源管线、Web 字体、`/static`。
- 全局加宽到 1280px（会撞 reader 断点）。
