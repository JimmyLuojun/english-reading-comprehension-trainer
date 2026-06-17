# PDF 导入执行方案

`[新增 2026-06-17]`

实现状态：Phase 2B 已落地。`app/importers/pdf_importer.py` 支持可抽取文本 PDF 导入，`books.source_format` 已扩展为 `pdf`，Web `/import/file` 与 CLI `books import pdf` 已接入。Phase 2A 保留矢量图表区域：从 PDF lines/curves/rects/images 检测粗粒度 figure region，通过 `pdfplumber`/`pypdfium2` 渲染为 PNG，写入现有 `book_assets` 和 `chapter_blocks(kind='figure')`，并从正文 words 中排除图表区域内标签以避免重复。Phase 2B 进一步把数学公式和代码块等 non-prose 文本区域渲染为 figure，避免它们进入 sentences、AI analysis 和复习流水线。当前实现仍按本文排除项执行：不做 OCR、不嵌入 PDF viewer、不追求视觉版面 1:1 复刻。

目标：支持导入可抽取文本的 PDF，并让导入后的阅读和训练体验尽量等同于当前 EPUB：连续阅读、选句、选词、词卡/句卡、AI analysis、来源跳转、复习队列和阅读位置恢复都继续基于现有阅读页工作。

核心决策：PDF 不做独立 PDF viewer。PDF importer 必须把源 PDF 归一化为现有 `books / chapters / paragraphs / sentences / chapter_blocks` 数据模型，阅读页仍使用 `/read/{book_id}` 和 `sentence_id` DOM span。PDF 原版页面截图、OCR、复杂版面复刻都不作为第一版主路径。

## 1. 设计原则

- **可训练文本优先**：第一版目标是得到干净、可选择、可标记、可分析的英语正文，而不是还原 PDF 视觉版式。
- **复用 EPUB 阅读链路**：导入后必须复用现有 reader、selection toolbar、AI analysis、Cards、Review 和 source navigation。
- **保持稳定锚点**：每个可读句子必须进入 `sentences` 表并拥有稳定 `sentence_id`；词卡 `first_sentence_id`、句卡、review logs 都继续依赖这个锚点。
- **导入器隔离 PDF 复杂性**：PDF 的页眉页脚、断行、页码、章节推断等格式问题都在 `pdf_importer.py` 内解决，不把 PDF 特例扩散到阅读页 JS。
- **扫描版 PDF 明确失败**：第一版不做 OCR。没有可抽取文本时返回清晰错误，例如 `PDF contains no extractable text`。

## 2. Schema 与迁移

需要新增 migration，把 `books.source_format` 的 CHECK 约束从：

```sql
CHECK(source_format IN ('txt', 'epub'))
```

扩展为：

```sql
CHECK(source_format IN ('txt', 'epub', 'pdf'))
```

SQLite 不能直接 `ALTER COLUMN` 修改 CHECK 约束，必须重建 `books` 表：

1. `PRAGMA foreign_keys = OFF;`
2. `CREATE TABLE books_new (...)`，字段、默认值、`UNIQUE(file_hash)` 和新的 CHECK 约束必须完整保留。
3. `INSERT INTO books_new SELECT * FROM books;`
4. `DROP TABLE books;`
5. `ALTER TABLE books_new RENAME TO books;`
6. 重建 `books` 上需要的索引或约束。
7. `PRAGMA foreign_keys = ON;`

同时更新：

- `app/db_models.py`：`SourceFormat` 增加 `PDF = "pdf"`。
- `tests/test_db_models.py`：断言 `SourceFormat.PDF.value == "pdf"`。
- 数据库迁移测试必须使用真实 SQLite，不能 mock。

## 3. PDF importer

新增 `app/importers/pdf_importer.py`，按本项目 OOP/过程式标准顺序组织文件。

第一版依赖：

- `pdfplumber`：抽取文本和 word 坐标。
- `reportlab`：仅用于测试中生成 PDF fixture。

导入函数建议：

```python
def calculate_pdf_file_hash(file_path: str | Path) -> str: ...

def import_pdf(
    db: DatabaseConnection,
    file_path: str | Path,
    title: str | None = None,
    author: str | None = None,
    language: str = "en",
) -> ImportResult: ...
```

插入策略：

- PDF importer 直接复用 EPUB importer 的 `_insert()`：

  ```python
  from app.importers.epub_importer import EpubAssetSource, TextBlock, _insert
  ```

- 文本块传入 `TextBlock(kind="prose")`。
- Phase 2A 图表块传入 `TextBlock(kind="figure", asset_href=...)`，并用同一个 `asset_href` 在 `asset_sources` 中提供 `EpubAssetSource(media_type="image/png", content=...)`。
- `_insert()` 负责把 prose 写入 `paragraphs/sentences/chapter_blocks`，把 figure 写入 `book_assets/chapter_blocks`。

- 暂不为“共享插入器”提前抽象 `base_importer.py`；等第三种复杂导入格式或 `_insert()` 出现 PDF 专用分支时再提取。

PDF importer 输出给 `_insert()` 的 `chapters_raw` 应保持和 EPUB importer 兼容：

```python
[
    {
        "title": "Pages 1-10",
        "section_kind": "chapter",
        "chapter_number": 1,
        "blocks": [
            {"kind": "prose", "text": "...", "payload_json": "{}"},
        ],
    },
]
```

## 4. 文本抽取与清洗

不要直接依赖 `page.extract_text()` 作为主路径，因为它无法稳定过滤页眉页脚。第一版使用 `page.extract_words()`，通过 word 坐标重组正文。

页眉页脚启发式：

```python
_HEADER_BAND_RATIO = 0.08
_FOOTER_BAND_RATIO = 0.08

page_height = page.height
header_cutoff = page_height * _HEADER_BAND_RATIO
footer_cutoff = page_height * (1 - _FOOTER_BAND_RATIO)
words = [
    word
    for word in page.extract_words()
    if header_cutoff < word["top"] < footer_cutoff
]
```

文本重组规则：

- 按 page number、`top`、`x0` 排序 words。
- 同一行 words 合并为一行；行高阈值用当前页字体高度的中位数或固定容差。
- 行之间判断段落：垂直间距明显大于普通行距时开启新段落。
- 处理英文断行连字符：`exam-\nple` 合并为 `example`。
- 普通换行合并为空格，段落之间保留空行。
- 去除孤立页码行和重复空白。
- 每个 prose block 交给现有 `segment_sentences()` 切句，保持句子哈希逻辑一致。

Phase 2A 图表保留规则：

- 从 `page.lines`、`page.curves`、`page.rects`、`page.images` 获取候选区域。
- 过滤页眉页脚区域和全宽细横线等装饰性噪声。
- 先合并相邻候选 bbox，再过滤过小区域，避免把框线图拆成多个零散图片。
- 只有包含可抽取标签文字或真实 image primitive 的区域才写入 figure，空白矩形不视为可导入内容。
- 图表区域内 words 不进入 `_words_to_lines()`，避免 `Hash / Block / Transaction` 等标签变成重复正文。
- 用 `page.crop(region).to_image(resolution=150)` 渲染 PNG；不引入 PyMuPDF，不使用 OCR。

Phase 2B non-prose 文本区域规则：

- 用 `page.extract_words(extra_attrs=["fontname", "size"])` 获取字体和字号。
- 识别 monospace 字体行作为代码块，例如 Courier/Mono/Consolas/Menlo。
- 识别数学区域：Symbol/Math 字体、数学符号密度高、字号变化明显、非字母比例高的行。
- 把连续 non-prose 行按垂直间距聚类成局部 region；公式和代码之间间距较大时拆成多个 figure。
- 把这些 region 走同一套 PNG 渲染和 `book_assets/chapter_blocks(kind='figure')` 写入路径。
- region 内 words 从正文抽取中排除；周围英文 prose 继续进入 `sentences`。
- Phase 2B 不尝试把公式线性化为文本，也不把代码块先做成 `pre`；以后如需可选择代码，再单独加 `TextBlock(kind="pre")` 路径。

章节策略：

- 如果 PDF 有 outline/bookmarks，优先用 outline 切章节。
- 没有 outline 时按固定页数生成虚拟章节，例如每 10 页一章：`Pages 1-10`、`Pages 11-20`。
- 不允许整本 PDF 作为单一巨大章节，避免阅读页过长、进度恢复不稳和 DOM 过重。

错误处理：

- 文件不存在：`FileNotFoundError`。
- hash 已存在：复用 `DuplicateBookError`。
- 没有可抽取正文：`ValueError("PDF contains no extractable text: ...")`。
- 加密或损坏 PDF：返回清晰 `ValueError`，Web 层显示 400。

## 5. Web 与 CLI 接入

Web：

- import 表单文案改为 `TXT, EPUB, or PDF file`。
- 文件输入 `accept` 增加 `.pdf,application/pdf`。
- `/import/file` 根据文件名 `.pdf` 进入 PDF 分支。
- PDF 和 EPUB 一样使用 `_save_upload_to_temp()` 流式落盘，不用 `await file.read()` 一次性读入内存。
- 新增 `_MAX_PDF_IMPORT_BYTES`，第一版可设为 `100 * 1024 * 1024`。
- 重复导入时用 `calculate_pdf_file_hash()` 查找已有 book，并返回现有 duplicate 页面。
- 成功后 redirect 到 `/read/{book_id}`。

CLI：

- 新增命令：

  ```bash
  python -m app.cli_entry books import pdf /path/to/book.pdf
  ```

- 参数保持与 EPUB 一致：`--title`、`--author`、`--language`。

- 输出保持与 EPUB 一致：书名、作者、book id、章节数、句子数。

依赖：

- `pyproject.toml` runtime dependencies 增加 `pdfplumber`。
- dev dependencies 增加 `reportlab`，用于测试生成 PDF。

## 6. 测试要求

必须覆盖：

1. **SourceFormat**：`SourceFormat.PDF.value == "pdf"`。
2. **真实 SQLite migration**：在旧 schema 下插入 TXT/EPUB book 及其 chapters/paragraphs/sentences/book_assets/chapter_blocks，应用新 migration 后验证行数、外键关系、`file_hash` 唯一约束和可读数据全部保持。
3. **PDF source_format**：migration 后可以插入 `source_format='pdf'`，非法值仍失败。
4. **PDF importer 正常路径**：用 `reportlab` 生成两页英文 PDF，导入后得到 book、章节、段落、句子，`source_format='pdf'`。
5. **页眉页脚过滤**：测试 PDF 每页有相同 header/footer，导入后正文句子不包含这些噪音。
6. **断行合并**：`exam-` + 下一行 `ple` 导入后变成 `example`。
7. **重复导入**：同一 PDF 第二次导入抛出 `DuplicateBookError`。
8. **空文本/扫描版**：只有图片或没有可抽取 words 的 PDF 返回 `ValueError`。
9. **Web 上传成功**：`.pdf` 上传成功后 303 到 `/read/{book_id}`。
10. **Web 上传超限**：PDF 超过 `_MAX_PDF_IMPORT_BYTES` 返回 413，临时文件被清理。
11. **Web 重复上传**：重复 PDF 返回 409 duplicate 页面，并链接到已有 book。
12. **CLI 导入**：`books import pdf` 成功、重复、文件不存在、空文本 PDF 都有对应结果。

## 7. 排除项

- 不做 OCR。
- 不嵌入 PDF viewer 作为主阅读体验。
- 不追求 PDF 视觉版面 1:1 复刻。
- 不把整本 PDF 导成一个章节。
- 不默认渲染每页截图到阅读流，避免资产目录暴涨和阅读重复。
- 不把页眉、页脚、页码写入正文句子、AI analysis 或复习卡。
- 不为了 PDF importer 提前重构 EPUB importer 的 `_insert()` 到共享模块。
