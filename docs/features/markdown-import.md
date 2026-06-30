# Markdown 导入执行方案

实现状态：已落地。Web `/import/file` 支持 `.md` / `.markdown` 上传，CLI 支持 `books import md`。Markdown 导入使用 `books.source_format='md'`，每个 Markdown 文件作为一个 Reader chapter 导入，正文归一化后复用现有 `books / chapters / paragraphs / sentences` 阅读模型，并额外写入 `chapter_blocks` 供 Reader 保留 Markdown 块级结构。

## 范围

- Markdown 标题（ATX `#` 和 Setext `===` / `---`）不作为 Reader chapter，也不进入句子流；文件本身对应一个 `Chapter 1`，标题以 `chapter_blocks(kind='heading')` 在 Reader 中渲染。
- 普通段落、blockquote 转为可训练 prose，并以 `chapter_blocks(kind='prose')` 保留块顺序。
- 列表项和 task list 项转为可训练句子，同时以 `chapter_blocks(kind='list_item')` 在 Reader 中渲染为 `<ol>` / `<ul>`。
- 链接保留可读文字，去掉 URL；强调、删除线、HTML 标签和转义符清理为普通文本。
- 内嵌 `data:image/...;base64,...` 图片会作为 `book_assets` 保存，并在 Reader 句子内渲染为 inline image，主要用于保留 Markdown 导出的公式/符号图片。
- YAML/TOML front matter、HTML comment、fenced code block、reference link definition、table separator、horizontal rule 不进入句子流。
- 重复检测使用原始 Markdown bytes 的 SHA-256，避免不同文件误合并。

## 非目标

- 不完整渲染 Markdown 版式；当前只保留标题、段落、列表和内嵌 data-image 公式。
- 不保留表格或代码块为 `chapter_blocks`。
- 不下载远程图片；只有文件内嵌 data-image 会被保存为本地资产。
- 不把远程 Markdown URL 作为 URL 导入的特殊格式；远程 URL 导入仍只抽 HTML/plain-text 并存为 `txt`。

## 验证

- `tests/importers/test_markdown_importer.py` 覆盖单 chapter 导入、块结构保存、清洗、内嵌 data-image 资产保存、空内容、缺文件和重复导入。
- `tests/test_db_connection.py` 覆盖 `books.source_format='md'` 的真实 SQLite migration。
- Web service/router/FastAPI 集成测试覆盖 `.md` 上传、重复上传、空文件和 Import 页面 accept 列表。
- CLI 测试覆盖 `books import md` 成功、覆盖标题、重复、缺文件和 code-only 错误。
