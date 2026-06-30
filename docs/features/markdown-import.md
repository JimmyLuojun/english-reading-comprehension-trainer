# Markdown 导入执行方案

实现状态：已落地。Web `/import/file` 支持 `.md` / `.markdown` 上传，CLI 支持 `books import md`。Markdown 导入使用 `books.source_format='md'`，正文归一化后复用现有 `books / chapters / paragraphs / sentences` 阅读模型。

## 范围

- Markdown 标题（ATX `#` 和 Setext `===` / `---`）作为章节标题。
- 普通段落、blockquote、列表项、task list 项转为可训练 prose。
- 链接保留可读文字，去掉 URL；强调、删除线、HTML 标签和转义符清理为普通文本。
- YAML/TOML front matter、HTML comment、fenced code block、reference link definition、table separator、horizontal rule 不进入句子流。
- 重复检测使用原始 Markdown bytes 的 SHA-256，避免不同文件误合并。

## 非目标

- 不渲染 Markdown 版式。
- 不保留图片、表格或代码块为 `chapter_blocks`。
- 不把远程 Markdown URL 作为 URL 导入的特殊格式；远程 URL 导入仍只抽 HTML/plain-text 并存为 `txt`。

## 验证

- `tests/importers/test_markdown_importer.py` 覆盖章节识别、清洗、空内容、缺文件和重复导入。
- `tests/test_db_connection.py` 覆盖 `books.source_format='md'` 的真实 SQLite migration。
- Web service/router/FastAPI 集成测试覆盖 `.md` 上传、重复上传、空文件和 Import 页面 accept 列表。
- CLI 测试覆盖 `books import md` 成功、覆盖标题、重复、缺文件和 code-only 错误。
