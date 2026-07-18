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

Library 详情页只编辑 title、author 和 content type；library status 与 item tags 不在详情页重复显示，统一在 Library 列表维护。Library 列表的 item title 通过统一 open 入口进入阅读流，独立的 Details 操作进入详情页。列表可按 type、status、tag 过滤；每一行可直接修改 content type、library status 和逗号分隔的 tags，并通过该行的 Save 单独保存，保存后保留当前筛选条件。行内编辑不修改 title、author、内容结构、卡片、标注或阅读位置。详情页保存 title/author/type 时会原样保留已有 status 和 tags。Tags 复用全局 `tags` 表，通过 `book_tags` 关联，不引入 Collections。行内 Save 后重定向回列表并携带 `saved` 参数，列表顶部渲染一次性 `Saved ‹title›.` 提示。`Manage tags` 折叠区列出全部 library tag（含未被任何 item 使用的 orphan）及其 item 数；`POST /tags/{tag_id}/delete` 从所有 item 移除该 tag，随后列表提示受影响的 item 并链接到对应行锚点（`#library-item-{id}`），用户可直接修改这些 item 的 tags。tag 仍通过行内 Tags 输入创建（首次保存自动写入 `tags` 表）；若 tag 仍被 word/sentence 卡片引用，删除时只解除 `book_tags` 关联，保留共享 `tags` 行。

### 2.1 阅读入口与 Contents

- `/books/{book_id}/open` 是 Library title 的统一入口。它只读取现有 `reader:progress:book:{book_id}` localStorage key，不写入新进度。
- 有有效进度时，进入 `/read/{book_id}?restore=1`，由 Reader 恢复已保存的 section 和 top sentence。每个 item 的 key 独立，因此来回切换 item 不会互相覆盖位置。Reader 在跨 section 恢复跳转期间会暂停 `pagehide` 进度写入，避免离开的旧 section 覆盖正在恢复的新 section 并引起循环跳转。
- 没有进度且有两个或以上可读 section 时，先进入独立 `/books/{book_id}/contents` 页；只有一个可读 section 时直接从起点阅读。Excerpt 不显示人为 Contents。
- Contents 页本身不加载 Reader script，因此只查看目录不会被判定为已阅读。选择 section 或 Start from beginning 后才由 Reader 正常保存进度。
- Reader 对有意义的多 section item 始终提供 Contents 入口；单 section item 和 excerpt 保留 Item details 入口。句卡等显式 deep link 仍以 URL 指定位置为准，不被自动 resume 覆盖。
- 阅读历史不从 `library_status`、卡片或标注推断。当前进度仍只对同一 browser origin 有效；跨设备同步仍属于后续 SQLite progress 迁移。

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
