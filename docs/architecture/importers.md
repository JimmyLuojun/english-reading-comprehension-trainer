# 导入器设计

本文件保存已实现导入链路的通用设计。Markdown 导入的执行细节见 `docs/features/markdown-import.md`，PDF 导入的详细计划见 `docs/features/pdf-import.md`，URL 导入的执行细节见 `docs/features/url-import.md`。

## 1. 当前导入入口

- TXT：文件上传、粘贴文本和 URL 抽取正文后都复用 `import_text()`，最终写入 `books / chapters / paragraphs / sentences`，`books.source_format='txt'`。
- Markdown：文件上传和 CLI 走 `import_markdown()` / `import_markdown_bytes()`，清理 front matter、代码块、链接、强调、HTML 标签等常见 Markdown 语法；一个 Markdown 文件导入为一个 Reader chapter，标题/段落/列表写入 `chapter_blocks` 供 Reader 保留块级结构，内嵌 data-image 公式保存为 `book_assets` 并在 Reader 句内渲染，最终写入标准句子流，`books.source_format='md'`。
- EPUB：文件上传走 `import_epub()`，保留可展示媒体资源和 `chapter_blocks`。EPUB 2 的 `toc.ncx` 与 EPUB 3 navigation document 都参与标题解析；当目录包含明确编号章节时，首个正文 chapter 之前的未编号 spine 文档归为 frontmatter，出版商序号 + ISBN + `FM` 这类技术文件名也会还原为 Front Matter；罗马数字附录、家族树以及最后一个正文 chapter 之后的常见注释、参考资料、索引和封底均不消耗正文章号。
- PDF：文件上传走 `import_pdf()`，归一化为现有阅读模型；图表、公式/代码、编号逻辑证明或规则示例等非 prose 视觉块以 figure/asset 形式保留，避免污染句子训练流。
- URL：`POST /import/url` 下载远程 HTML/plain-text，抽取可读正文后作为 UTF-8 TXT 字节进入 `import_text_bytes()`，不新增 schema 字段。

## 2. URL 导入边界

- 只接受 `http` / `https` URL。
- 下载限制：10 MB、10 秒超时、最多 5 次重定向。
- 重定向后的最终 URL 也必须重新校验，避免公开 URL 跳到本地或私网地址。
- 拒绝 `localhost`、loopback、private、link-local、multicast、unspecified IP。
- 只接受 `text/html`、`application/xhtml+xml`、`text/plain`；PDF/EPUB 远程下载不走 URL 导入 MVP。
- HTML 通过 BeautifulSoup 清理 `script/style/nav/header/footer/aside/form` 等页面 chrome，优先抽 `article` / `main`，退回到 `body`。
- 第一版不保存 `source_url`，因此 URL 导入结果在数据模型里仍表现为普通 TXT book。

## 6. EPUB 重复导入的幂等性

**默认：按 ****************************************************************`file_hash`**************************************************************** 识别同一本书，更新元数据与章节结构，但不动卡片和复习记录。**

- 若 `file_hash` 命中：报告"已存在，是否更新结构？"；用户选更新则重新解析章节并尝试重新绑定 `sentences.text_hash`，绑不上的句子标记为 `orphaned`。
- 若 `file_hash` 不同但 `title + author` 命中：视为新版本，提示用户手动合并。
- 卡片和复习状态**永不因重导丢失**。

`[已确认 2026-06-14]`

---
