# Cards 与 Review

本文件保存 Cards 页、Review Queue、Notes、Reveal、来源跳转和 EPUB 导入接入相关设计。

## 23. Cards 页与 Review Queue 信息增强

`[新增 2026-06-15]`

### 23.1 背景

Cards 页的 Word Cards 表目前只有 ID / Word / Type / State / Occ. 五列，用户填写的 Notes（`user_note`）不可见；AI 分析出的 `meaning_in_context` 也无处展示。Review Queue 页的 Answer 列只有 pass/partial/fail 按钮，复习时看不到自己的 note 作为自我核对依据。

### 23.2 Cards 页改动

**Word Cards 表新增三列：**

| 列              | 数据来源                                                                                      | 展示方式                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| **Notes**      | `word_cards.user_note`                                                                    | 明文；未填则显示 `—`；若历史数据中与 Definition/AI meaning 完全相同则视为空，避免自动内容伪装成用户笔记                             |
| **AI Meaning** | `ai_cache.response_json → $.meaning_in_context`（通过 `word_cards.ai_analysis_id` LEFT JOIN） | `▶ Reveal` 触发 hover/focus 浮层；无分析则显示 `—`，不撑开表格行高                                               |
| **Source**     | `word_cards.first_sentence_id → sentences / chapters / books`                             | 链接到该词卡第一次出现的正文句子：`/read/{book_id}?chapter={chapter_idx}#sentence-{sentence_id}`；旁边已有 Occ. 列计数 |

**`list_word_cards`**\*\* SQL 改动（无 schema 迁移）：\*\*

```sql
SELECT wc.*,
       b.title  AS first_book_title,
       s.id     AS source_sentence_id,
       s.book_id AS source_book_id,
       c.idx    AS source_chapter_idx,
       s.text   AS source_sentence_text,
       json_extract(ac.response_json, '$.meaning_in_context') AS ai_meaning
FROM word_cards wc
LEFT JOIN sentences s  ON s.id  = wc.first_sentence_id
LEFT JOIN chapters  c  ON c.id  = s.chapter_id
LEFT JOIN books     b  ON b.id  = s.book_id
LEFT JOIN ai_cache  ac ON ac.id = wc.ai_analysis_id
WHERE wc.archived_at IS NULL
ORDER BY wc.occurrence_count DESC, wc.created_at DESC
LIMIT ? OFFSET ?
```

**关于"所有出现书籍"的分期策略：**

- **本期（§23）**：Source 列显示 "first seen in《书名》"（`first_sentence_id` 路径），并可点击跳转到第一次出现的正文句子；Occ. 列继续显示总次数。
- **后期（留 §25+）**：新增 `word_card_occurrences(word_card_id, sentence_id)` junction 表，每次在阅读器高亮词汇时写入；Source 列升级为所有出现位置的书名 / 章节 / 句子列表。

### 23.3 Review Queue 页改动

**数据层：**

- `_word_due_sql()` 加 `wc.user_note AS answer`，并且当 `user_note` 与 Definition/AI meaning 完全相同时不显示，避免自动填充内容伪装成用户 note
- `_sentence_due_sql()` 加 `COALESCE(sc.user_translation, '') AS answer`
- `_word_due_sql()` 对 word / phrase / collocation 额外 join `sentences / chapters / books`，按 `wc.first_sentence_id` 取第一次出现来源
- `ReviewQueueItem` 加字段 `answer: str = ""`、`source_book_title: str = ""`、`source_href: str = ""`（冻结 dataclass 需设默认值，向后兼容）

**UI 层：**

- Answer 列改为：先 `▶ Reveal` hover/focus 浮层展示 Your note / AI meaning，再跟 pass/partial/fail 按钮；浮层绝对定位，不参与表格布局，不改变行高
- 若 `answer` 和 `ai_meaning` 都为空则只显示按钮（兼容尚未填写 Notes 且尚无 AI analysis 的卡片）
- word / phrase / collocation 的 Prompt 保留发音按钮，同时让词条文本可点击跳转到来源正文；sentence card prompt 不加词汇来源链接

无 schema 迁移，全部为查询与 UI 层改动。

### 23.4 Cards / Review 到来源正文跳转

`[增补 2026-06-16]`

**目标**：在 Cards 页和 Review Queue 页，点击需要掌握的陌生单词、词组或习语，应能返回到它所在来源的正文。第一版默认返回该词卡第一次出现的位置，即 `word_cards.first_sentence_id`。

**统一跳转规则：**

```text
source_href = /read/{source_book_id}?chapter={source_chapter_idx}#sentence-{source_sentence_id}
```

- `source_book_id` 来自 `sentences.book_id`。
- `source_chapter_idx` 来自 `sentences.chapter_id → chapters.idx`，继续使用现有 reader URL key。
- `source_sentence_id` 使用 `word_cards.first_sentence_id`，与阅读页现有 `id="sentence-{id}"` 锚点一致。
- 若历史数据异常导致来源句子或章节缺失，UI 退化为纯文本书名或 `—`，不渲染坏链接。

**页面行为：**

- **Cards 页**：`Word/Phrase` 列或 `Source` 列均可作为入口；发音按钮必须仍是独立按钮，不能包进链接，避免点击播放时触发跳转。
- **Review Queue 页**：只对 `CardType.WORD` 的 prompt 渲染来源链接；sentence card prompt 保持纯文本，避免复习难句时产生额外导航干扰。
- 跳入 Reader 后由浏览器原生 hash 定位到 `#sentence-{id}`。阅读页给 `.reader-sentence` 设置 `scroll-margin-top`，并用 `:target` 或等价 class 高亮目标句子，帮助用户确认来源。

**不做项：**

- 本轮不追踪所有出现位置；`occurrence_count` 仍只表示累计次数。
- 本轮不新增 `word_card_occurrences` 表。等后续需要“查看所有出处”时再做 junction 表与多来源列表。

### 23.5 影响文件

| 文件                                                                                             | 改动类型                                |
| ---------------------------------------------------------------------------------------------- | ----------------------------------- |
| `app/cards/word_card_service.py` — `list_word_cards`                                           | 加来源句子、章节、书籍字段                       |
| `app/review/daily_review_queue.py` — `_word_due_sql` / `_sentence_due_sql` / `ReviewQueueItem` | 加 `answer` 与来源字段                    |
| `app/web/views/cards.py` / `app/web/views/review.py` / `app/web/views/styles.py`               | UI 渲染                               |
| `tests/cards/test_word_card_service.py`                                                        | 验证新列                                |
| `tests/review/test_daily_review_queue.py`                                                      | 验证 `answer` 与来源字段                   |
| `tests/web/test_fastapi_app.py`                                                                | 验证 Cards / Review 来源链接与 Reader 目标高亮 |

---
---

## §24 Cards Notes 内联编辑、Review Reveal AI 含义、EPUB 导入接入

### §24.1 Cards 页 Notes 内联编辑

**目标**：用户可在 Cards 表格中直接编辑 Notes 列。Notes 只写入 `word_cards.user_note`，不把 Definition（`current_meaning`）或 AI meaning 自动填进去。

**方案**：JavaScript 内联编辑 + 复用已有 `PATCH /mark/word/{card_id}` 端点

渲染变更（`_word_cards_table`）：

```html
<!-- 旧 -->
<td>处于原始且简单的状态的事物</td>

<!-- 新 -->
<td>
  <span class="note-text" data-card-id="7">我的笔记</span>
  <button class="note-edit-btn" aria-label="edit notes">✎</button>
  <input class="note-input hidden" data-card-id="7" data-current-meaning="..." value="我的笔记">
</td>
```

JS 行为（注入到页面 `<script>` 末尾）：

- 点击 `.note-text` 或 `.note-edit-btn` → 隐藏 span+button，显示 input 并 focus
- `blur` 或 Enter → `PATCH /mark/word/{card_id}` with `user_note=<value>` and existing `current_meaning` → 成功后更新 span 文本，恢复显示
- Escape → 放弃编辑，恢复原值

不需要新后端端点。

### §24.2 Review Queue Reveal 也展示 AI 含义

**目标**：复习时 Reveal 区域除用户 note 外，也显示 AI 分析出的 `meaning_in_context`；Reveal 和 Cards 页 AI Meaning 都使用 hover/focus 浮层，避免向下展开导致表格单元格位置变化。

**变更点**：

1. `ReviewQueueItem` 增加字段：

   ```python
   ai_meaning: str = ""
   ```

2. `_word_due_sql()` 增加 JOIN：

   ```sql
   LEFT JOIN ai_cache ac ON ac.id = wc.ai_analysis_id
   ```

   新增列：

   ```sql
   COALESCE(json_extract(ac.response_json, '$.meaning_in_context'), '') AS ai_meaning
   ```

3. `_sentence_due_sql()` 补占位列：

   ```sql
   '' AS ai_meaning
   ```

4. `_item_from_row()` 填入：

   ```python
   ai_meaning=row.get("ai_meaning") or "",
   ```

5. `_review_answer_cell()` Reveal 浮层显示两段（各有内容才显示）：

   ```
   ▶ Reveal
     Your note:       我的易混备注
     AI meaning:      existing in or relating to an early stage of development
   ```

6. `_ai_meaning_cell()` 在 Cards 页渲染 `▶ Reveal` hover/focus 浮层，显示 `ai_meaning`，不使用 `<details>`，与 Review 的入口文案保持一致。

### §24.3 EPUB 导入完整性修复与 Web 层接入

**目标**：Import 页面支持 `.epub` 上传；CLI 和 Web 导入都能完整解析真实 EPUB，尤其是 iBooks 展开的 `.epub` 目录包，并避免丢失列表、代码块、术语表、表格等非 `<p>` 内容。

**已确认问题**：

- iBooks 本地书库中的 `Mastering Bitcoin.epub` 是目录包，内部包含 `META-INF/`、`mimetype`、`OEBPS/`，不是普通 ZIP 文件。当前 `import_epub()` 先调用 `Path.read_bytes()` 计算 hash，再调用 `ebooklib.epub.read_epub()`，两者都不能直接处理目录包。
- `_extract_paragraphs()` 当前逻辑是 `p_tags if p_tags else soup.find_all(_BLOCK_TAGS)`。只要某个 HTML 文件存在 `<p>`，同文件内的 `<li>`、`<dt>`、`<dd>`、`<pre>`、表格、图注等可见文本都会被跳过。
- `_MIN_PARA_LEN = 20` 会过滤短 `<dt>` 术语标题；如果不与对应 `<dd>` 合并，术语表会缺项。
- Web 层当前对 TXT 和 EPUB 共用 10 MB 上限，并使用 `await file.read()` 一次性读入内存。若提高 EPUB 上限，必须同时改成流式写临时文件。

#### §24.3.1 EPUB 源文件归一化

**决策**：支持 iBooks 目录包时，不手写 OPF/spine 解析层；检测到目录包后先打包成 deterministic 临时 EPUB ZIP，再复用现有 ebooklib 解析路径。

原因：

- 继续让 ebooklib 负责 EPUB metadata、manifest、spine、TOC 等标准解析，降低自写 OPF 解析的边界风险。
- 目录包只是存储形态不同，正文结构仍是 EPUB；归一化为 ZIP 后可以复用现有测试和导入流程。

实现要求：

- 新增源文件准备函数，例如 `_prepare_epub_source(file_path) -> PreparedEpubSource`：
  - 普通文件：直接使用原路径，`file_hash = sha256(file_bytes)`。
  - 目录包：校验存在 `META-INF/container.xml` 和 `mimetype`，打 deterministic 临时 ZIP，后续传给 `ebooklib.epub.read_epub()`。
- deterministic ZIP 规则：
  - `mimetype` 必须作为第一项写入，并使用 `ZIP_STORED`。
  - 其他文件按相对路径字典序写入。
  - 固定 `ZipInfo.date_time`、权限位、压缩方式，避免同一目录包每次生成不同 hash。
  - `file_hash` 使用 deterministic ZIP 字节 hash，或使用等价的稳定目录 hash（按相对路径排序，hash `path + bytes`）；二者必须在重复导入时稳定。
- `DuplicateBookError` 和 `_lookup_book_id_by_hash()` 必须使用同一套 hash 规则，避免目录包和上传 ZIP 的重复识别不一致。
- 临时 ZIP 在 import 结束后清理。

#### §24.3.2 正文块抽取策略

**决策**：把 `_extract_paragraphs()` 从“优先 `<p>`”改为“按 DOM 阅读顺序抽取可见文本块”。

抽取范围：

- prose：`p`、`blockquote`
- lists：`li`
- definition lists：`dt + 后续一个或多个 dd` 合并成一个块
- code：`pre` / 代码块，整块保留
- tables：优先按 `<tr>` 行级拼接单元格；必要时整表作为一个块，避免按 `td/th` 产生大量短碎片
- captions：`figcaption`、`caption`

去重规则：

- 遍历 DOM 时避免同时抽父块和子块。典型例子：`<div><p>...</p></div>` 只能产生一个段落。
- 已抽取节点的后代不再重复抽取；父节点只有在没有可抽取子块时才作为 fallback。
- 移除 `script`、`style`、`nav`、`aside`、`head` 等非正文区域。

切句规则：

- 普通 prose 块继续走 `segment_sentences()`。
- `pre`、代码块、表格块不走句子切分，作为一个完整块插入，避免代码和表格被 pysbd 切碎。
- 可用内部数据结构表达块类型，例如 `TextBlock(kind="prose" | "pre" | "table", text=...)`；数据库 schema 可以暂不变，仍写入 `sentences` 表，但插入逻辑按 `kind` 决定是否切句。

#### §24.3.3 Web 上传路径

**决策**：TXT 和 EPUB 使用不同上限，并把文件上传改成流式落盘。

建议：

- pasted text：继续使用 10 MB 上限。
- TXT 文件：可继续使用 10 MB 或单独设置更高上限。
- EPUB 文件：提高到 100 MB 或 200 MB；这是压缩包总大小，不代表正文大小。

实现要求：

- 不再对 EPUB 使用 `await file.read()` 一次性读入内存。
- `UploadFile` 分块读取并写入 `tempfile.NamedTemporaryFile` 或 `SpooledTemporaryFile`，边读边统计字节数，超过上限立即停止并返回 413。
- EPUB 上传完成后调用 `import_epub(db, tmp_path, ...)`；重复导入时用 importer 计算出的稳定 hash 查找已有书。
- Import 表单保留 `accept=".txt,.epub"`，说明文字使用 “TXT or EPUB”。

#### §24.3.4 既有导入数据修复

修复 importer 后，旧书不会自动补全内容，需要重导。

重导 `Mastering Bitcoin` 之前必须先确认没有引用：

```sql
SELECT COUNT(*)
FROM sentence_cards sc
JOIN sentences s ON s.id = sc.sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM word_cards wc
JOIN sentences s ON s.id = wc.first_sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM review_logs rl
JOIN sentence_cards sc ON sc.id = rl.card_id AND rl.card_type = 'sentence'
JOIN sentences s ON s.id = sc.sentence_id
WHERE s.book_id = :book_id;

SELECT COUNT(*)
FROM review_logs rl
JOIN word_cards wc ON wc.id = rl.card_id AND rl.card_type = 'word'
JOIN sentences s ON s.id = wc.first_sentence_id
WHERE s.book_id = :book_id;
```

- 四项均为 0：可删除旧 book 及其章节/段落/句子后重导。
- 任一项不为 0：不能直接删除；应按 §6 的重导幂等策略，通过 `text_hash` 迁移或重新绑定卡片与复习记录。

#### §24.3.5 EPUB 章节编号与阅读顺序

**决策**：把 EPUB spine 的阅读顺序和正文 “Chapter N” 编号拆开保存，避免 frontmatter/backmatter 消耗正文章节号。

原因：

- iBooks 会把 `Praise for Mastering Bitcoin`、`Preface`、`Quick Glossary` 等放在阅读顺序中，但不会把它们算作 Chapter 1。
- 当前 schema 只有 `chapters.idx`，同时承担阅读顺序和显示编号，导致 `Praise for Mastering Bitcoin` 被渲染成 `Chapter 1`。
- EPUB 顶层 TOC 和正文 HTML 通常带有足够语义：`epub:type="preface"`、`epub:type="chapter"`、`epub:type="appendix"`、`epub:type="index"` 等。

实现要求：

- `chapters.idx` 保持阅读顺序和 URL 键，不改成正文编号。
- 新增 `chapters.section_kind`：`frontmatter | chapter | appendix | backmatter`。
- 新增 `chapters.chapter_number`：仅对 `section_kind='chapter'` 写入正文编号；frontmatter、appendix、backmatter 为 `NULL`。
- `books.total_chapters` 表示正文 `chapter` 数量，不再表示 spine 文档总数。
- 默认打开 `/read/<book_id>` 或书籍详情页主按钮时跳到第一条 `section_kind='chapter'`；frontmatter 仍可从目录表点击阅读。
- TOC 标题映射只能使用文件级/顶层 TOC 项，不能让同一 HTML 文件里的 fragment 子目录项覆盖章节标题。例如 `ch01.html#sending_receiving` 不应覆盖 `ch01.html` 的 `1. Introduction`。

#### §24.3.6 测试要求

新增或更新 `tests/importers/test_epub_importer.py`：

- 普通 ZIP EPUB 仍可导入。
- iBooks 风格展开目录包可导入，并且复用 ebooklib 路径。
- 混合块 HTML：`p + li + dt/dd + pre + table + figcaption` 按阅读顺序入库。
- 父子嵌套去重：`<div><p>...</p></div>` 不重复生成段落。
- `dt + 多 dd` 合并正确。
- `pre`/代码块不被切句。
- 表格按行级或整表保留，不产生无意义短碎片。
- frontmatter 不消耗正文 Chapter 1 编号。
- 同一 HTML 文件里的 nested TOC fragment 不覆盖顶层章节标题。

新增或更新 Web 测试：

- `.epub` 上传走流式临时文件路径。
- EPUB 和 pasted text 的大小上限分别生效。
- 超限 EPUB 返回 413，不留下临时文件。
- 书籍详情页主按钮和 `/read/<book_id>` 默认进入第一正文章，而不是 frontmatter。

#### §24.3.7 EPUB 图片与阅读块保留

**目标**：EPUB 导入不仅保留文本，还要把书中原有图片、公式截图、图表截图和图注按 DOM 阅读顺序呈现在阅读页，帮助理解正文；同时不污染句子级哈希、SM-2 调度和复习队列。

**第一版边界**：

- 支持 `<img>`、`<figure>`、`<figcaption>` 和图片类 manifest 资源。
- 现有 `prose` / `pre` / `table` 文本块继续写入 `paragraphs` / `sentences`；同时映射为 `chapter_blocks`，用于阅读页按原顺序插入媒体。
- 第一版不追求 EPUB CSS 级 1:1 表格/图片布局；表格仍按现有文本块处理，复杂表格版式留到后续迭代。
- 公式图先按普通图片保存；若有 `alt`，写入资产元数据和 block payload，便于后续迁移到 MathML/KaTeX。

**Schema**：

```sql
book_assets(
  id, book_id, source_href, media_type, storage_path,
  sha256, byte_size, alt_text, is_missing
)

chapter_blocks(
  id, book_id, chapter_id, idx, kind,
  paragraph_id, asset_id, text, payload_json
)
```

- `kind` 第一版取值：`prose | pre | table | image | figure | missing_asset`。
- `paragraph_id` 对 `prose` / `pre` / `table` 可非空，因为它们仍对应句子流；`image` / `figure` / `missing_asset` 为 `NULL`。
- `asset_id` 对真实图片或缺失图片引用非空；纯文本块为 `NULL`。
- `text` 存图注、alt 或缺失资源提示；`payload_json` 存轻量结构化信息，例如 `source_href`、`alt`、`caption`。

**导入规则**：

- `_extract_text_blocks()` 升级为块抽取模型，继续复用 DOM 顺序遍历和 consumed 去重。
- `<figure>` 作为一个整体 block：提取第一张 `<img>`、`figcaption`、`alt`，并 consume 整个 figure，避免图注再作为独立 prose 段重复导入。
- 独立 `<img>` 作为 `image` block；无图注时使用 `alt` 作为辅助文本。
- EPUB href 解析必须相对当前 XHTML 文件目录，去除 fragment 并 URL decode，禁止路径穿越。
- iBooks 目录包中由缺失 manifest 资源生成的 stub，导入时要写 `book_assets.is_missing=1` 和 `missing_asset` block，不把 0 字节文件复制进最终 assets 目录。
- 真实图片写入临时 staging 目录；DB transaction 成功后再移动到 `data/assets/books/<book_id>/`。导入失败或 DB rollback 时清理 staging，避免半成品文件。

**阅读页规则**：

- 阅读页优先读取 `chapter_blocks`；如果旧书没有 block 数据，fallback 到当前按 `sentences -> paragraphs` 渲染。
- 文本块仍渲染为带 `data-sentence-id` 的句子 span，保持选中标句、标词、AI 诊断逻辑不变。
- `image` / `figure` 渲染为 `<figure>` + `<img>` + `<figcaption>`；图片最大宽度 100%，保持原比例。
- `missing_asset` 渲染为轻量占位提示，明确资源在源 EPUB 中缺失，而不是导入器漏抽。

---
