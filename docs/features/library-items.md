# Library Items

实现状态：已落地（2026-07-17）。Web UI 把现有 `books` 记录统一呈现为 Library Items，同时保留所有 `book_id`、路由、卡片、标注和本地阅读进度 key。

## 1. 产品模型与兼容层

- 内容类型只使用 `book / article / excerpt / unclassified`。
- `Paragraph` 是结构单元，不是内容类型；Notes 继续属于卡片/标注。
- 产品层级为 Item → Section → Paragraph → Sentence；数据库继续使用 `books → chapters → paragraphs → sentences`。
- 不重命名 `books`、`chapters` 或 `book_id`。迁移 `017_library_items.sql` 只在 `books` 增加元数据，并新增 item-level `book_tags`。
- 迁移前已有记录统一回填为 `content_kind='unclassified'`。无法恢复的历史 `import_method` 保持 `NULL`，`source_uri` 保持空字符串。

## 2. Library Item 元数据

`books` 新增：

- `content_kind`：`book / article / excerpt / unclassified`；
- `import_method`：`file / paste / url`，旧记录可为 `NULL`；
- `source_uri`：URL 或原上传文件名/CLI 文件路径；
- `library_status`：`inbox / reading / finished / archived`。

`library_status` 是手工整理状态，不是阅读位置。Reader 位置仍由当前 browser localStorage 负责，未引入第二个进度事实源。

Library 详情页可编辑 title、author、content type、library status 和逗号分隔的 item tags；Library 列表可按 type、status、tag 过滤。Tags 复用全局 `tags` 表，通过 `book_tags` 关联，不引入 Collections。

## 3. 导入规则

Import 的文件、粘贴和 URL 表单均提供 `Auto / Book / Article / Excerpt`：

- URL + Auto → `article`；
- paste + Auto → `excerpt`；
- EPUB file + Auto → `book`；
- TXT / Markdown / PDF file + Auto → `unclassified`，由用户在 Library 修正。

所有新 Web/CLI 导入记录 provenance。`source_format` 继续只描述解析格式（`txt / md / epub / pdf`），不再承担导入渠道或语义类型。

文本与 Markdown Web 导入还会删除末尾误复制的模型切换界面元数据通知（可带 bullet）；只有最后一个非空行精确匹配该类通知时才删除，正文中的普通句子不受影响。

## 4. 类型化显示

- Book：使用 `Chapter`，保留 frontmatter/appendix/backmatter 标签逻辑。
- Article：使用 `Section`；只有一个内部 `Chapter 1` 占位 section 时不显示 reader section heading。
- Excerpt：Reader 不显示 section heading，详情表只提供 `Read excerpt` 入口。
- Unclassified：使用中性的 `Section`。

内部仍允许每个 item 至少有一个 section；TXT/Markdown importer 的 `Chapter 1` 占位没有被删除。

## 5. 暂不实现

- 不把 Notes 变成可读 source type；
- 不新增 Collections；
- 不做完整 pre-save preview；
- 不迁移 localStorage 阅读位置；
- 不重命名数据库表或公开 `/books` 路由。
