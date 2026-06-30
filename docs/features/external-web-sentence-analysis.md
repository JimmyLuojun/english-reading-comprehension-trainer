# 外部网页选句分析方案

状态：方案稿，未实现。本文保存“在任意网页按 `s` 选中当前句子，并在网页右侧显示本项目 AI 分析”的第一版最小方案和后续升级路线。

## 1. 第一版最小可行方案

目标只做一个闭环：

```text
外部网页按 s
  → 选中鼠标悬停/最近点击位置所在英文句子
  → 发送到本地 FastAPI
  → 后端结合上下文分析
  → 网页右侧 Shadow DOM drawer 显示结果
```

第一版使用 Chrome Extension 加本地 FastAPI bridge，不直接复用 Reader 页面脚本。

### 1.1 Chrome Extension

Content script：

1. 监听 `keydown`。
2. 用户按裸键 `s` 时触发。
3. 如果焦点在 `input` / `textarea` / `select` / `contenteditable`，忽略。
4. 根据最近鼠标位置或最近点击位置定位文本节点。
5. 用英文句子边界算法扩展出当前句子。
6. 在网页原文上临时高亮/选中。
7. 弹出小 toolbar：`AI Analysis` / `Dismiss`。
8. 点击 `AI Analysis` 后发送：

```json
{
  "sentence": "...",
  "context": "...",
  "page_url": "...",
  "page_title": "..."
}
```

右侧分析面板：

- 用 Shadow DOM 渲染，隔离网站 CSS。
- 固定在网页右侧，不改变原网页 DOM 布局。
- 第一版只显示句子分析结果，不做词卡、复习和来源管理。
- `Esc` 关闭 toolbar/drawer 可以作为第一版小增强。

### 1.2 后端 endpoint

新增独立 endpoint：

```text
POST /external/web-sentence/analyze
```

请求体：

```json
{
  "sentence": "...",
  "context": "...",
  "page_url": "...",
  "page_title": "..."
}
```

第一版后端不要直接复用 `analyze_sentence_for_reader()` 作为最终分析入口，因为当前 Reader 在线分析路径没有显式传 `context`。应新增专用 service，例如：

```python
analyze_external_web_sentence(
    db,
    sentence: str,
    context: str,
    page_title: str,
    page_url: str,
)
```

内部调用底层：

```python
analyze_sentence(
    db,
    sentence_text=matched_sentence,
    context=context,
    chapter_title=page_title,
)
```

这样 AI 分析会结合网页上下文，且 `context` 会进入 cache hash。同一句话在不同网页上下文里不会误用同一缓存。

### 1.3 第一版存储策略

不改 schema，复用现有 `books / chapters / paragraphs / sentences`：

- 每个网页导入为一条 `books` 记录。
- `title = Web Clip - {page_title}`。
- `source_format = 'txt'`。
- `context` 作为导入正文。
- 在导入后的 sentences 中找到与 `sentence` 最匹配的一句，绑定分析到该 `sentence_id`。

这意味着 Web Clip 会出现在 Books 页面。第一版接受这个结果，后续再用来源管理升级解决。

### 1.4 第一版非目标

- 不做标词、短语、搭配。
- 不默认创建 active Review 句卡。
- 不做网页来源管理 UI。
- 不处理 iframe 内文本、PDF viewer、canvas 渲染、付费墙、登录态抓取。
- 不试图把现有 Reader toolbar 状态机注入任意网页。

### 1.5 安全底线

- 本地 endpoint 必须有 token。
- Chrome Extension background script 统一转发请求。
- FastAPI 不应开放给任意网页直接调用。
- CORS 只允许扩展来源或完全不开放浏览器跨站调用。

## 2. 后续升级方案

### 2.1 来源管理

- 增加 `books.source_url` 或独立 `web_sources` / `web_clips` 表。
- 可选新增 `source_format='web'`，需要 migration 和真实 SQLite 集成测试。
- Books 页面将 Web Clips 单独分组、折叠或默认隐藏。
- 分析 drawer 提供 `Open original page`。

### 2.2 去重与复用

- 使用 `page_url + sentence_hash` 或 `normalized_context_hash` 复用已有 web sentence。
- 同一页面同一句不重复导入。
- 同一句不同上下文保留不同 cache，因为 context 会影响分析。

### 2.3 更强上下文

- 扩展端发送当前段落、前一段、后一段。
- 后端 prompt 明确区分：

```text
Target sentence
Local paragraph
Previous paragraph
Next paragraph
Page title
```

- 必要时把 `context_before` / `context_after` 作为结构化字段保存到新表。

### 2.4 网页侧交互增强

- `s` 选句后可配置为直接打开 drawer。
- `t` 写自己的翻译后再分析。
- 支持拖拽调整 drawer 宽度。
- 支持固定/收起 drawer。
- 支持临时高亮多个分析过的句子。

### 2.5 词和短语分析

- 外部网页选中词、短语或搭配。
- 发送 `{surface_form, sentence, context}`。
- 复用底层 word analysis。
- 后续再决定是否创建词卡，避免临时网页查询污染复习队列。

### 2.6 Review 和卡片整合

- 分析结果里提供 `Save as sentence card`。
- 默认只做临时分析，不进 Review。
- 用户明确保存后才创建 active `sentence_cards`。
- Web Clip 删除时遵守现有 book deletion 语义，词卡尽量 re-anchor。

### 2.7 稳定性与兼容性

- 对 Shadow DOM、复杂嵌套文本、动态 DOM、站点快捷键冲突增加浏览器级测试。
- 对不可读页面给出明确提示，而不是静默失败。
- 逐步支持更多句子边界规则，但保持 first version 的简单算法可回退。

## 3. 推荐实施顺序

1. 后端 `/external/web-sentence/analyze`，用测试模拟请求，不依赖浏览器。
2. Chrome Extension content script：按 `s` 选中当前句子 + toolbar。
3. Shadow DOM drawer 渲染分析结果。
4. 增加 token 安全层和 extension background 转发。
5. 增加来源管理 schema 与 Books 分组。
6. 再做词/短语分析与 Review 保存。
