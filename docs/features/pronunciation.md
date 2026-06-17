# 语音与发音

本文件保存浏览器 TTS MVP 与未来服务端音频缓存设计。

## 21. 语音与发音：浏览器 TTS MVP 与服务端音频缓存

### 21.1 背景与目标

用户需要在词汇学习动线中听到单词、词组、习语的美式发音，首批覆盖以下三个位置：

1. **Cards 页**：`Word/Phrase` 列中的 word / phrase / collocation 可播放发音。
2. **Review Queue 页**：仅 `word` card 的 Prompt 可播放发音；`sentence` card 第一版不加，避免截断句子发音和复习泄题。
3. **Reader 的 Word Analysis 面板**：只给面板标题里的 word / phrase 一个发音按钮，不给 Meaning / Register / Why this word 等分析段落加按钮。

第一版不做阅读正文句子的 hover 发音按钮。正文句子播放属于独立交互，应后续单独设计。

### 21.2 Phase 1：浏览器 TTS MVP

Phase 1 使用浏览器 Web Speech API（`speechSynthesis`）播放发音，不改 SQLite schema，不新增音频文件，不引入外部服务成本。

实现范围：

- 在 `app/web/fastapi_app.py` 增加发音按钮渲染 helper，例如 `<button type="button" data-speak-text="ephemeral">▶</button>`。
- `_word_cards_table()`：在 `Word/Phrase` 单元格渲染发音按钮，播放 `surface_form`。
- `_due_table()`：只在 `item.card_type == CardType.WORD` 时给 Prompt 渲染发音按钮，播放完整 `item.prompt`；sentence card 仅展示文本。
- `_analysis_panel()` / `renderWordAnalysis(payload)`：Word Analysis 面板中的发音按钮播放 `payload.surface_form`，不要从分析段落内容推断发音文本。
- 全局 JS 用事件委托处理 `button[data-speak-text]`，避免每行单独绑定监听。

前端约束：

- 优先选择 `en-US` voice。`speechSynthesis.getVoices()` 首次可能返回空数组，必须监听 `voiceschanged` 后重新选择 voice。
- 每次播放前调用 `speechSynthesis.cancel()`，避免连续点击进入播放队列。
- 仅设置 `utterance.lang = "en-US"` 不足以保证 macOS Safari / Chrome 一定选到美式 voice，应显式按优先级挑选 voice：
  - `Samantha`（macOS）
  - `Google US English`（Chrome）
  - 任意 `lang === "en-US"` 的 voice
  - 最后回退到浏览器默认 voice
- 不承诺"纯正美式"。Phase 1 的 UI 文案只称为 `Play pronunciation` 或 `US pronunciation`。
- 如果浏览器不支持 `speechSynthesis`，按钮应禁用或静默标记不可用，页面不能报错。

### 21.3 Phase 1 测试要求

第一版只做 route-level 测试，不测试真实发音输出：

- Cards 页 HTML 包含 word / phrase / collocation 的 `data-speak-text` 发音入口。
- Review Queue 页只给 word card prompt 渲染 `data-speak-text`，不给 sentence card prompt 渲染。
- Reader Word Analysis 面板包含一个发音按钮入口，并在 `renderWordAnalysis(payload)` 时使用 `payload.surface_form` 设置播放文本。
- 前端 JS 包含 `voiceschanged` voice 选择逻辑和播放前 `speechSynthesis.cancel()`。

### 21.4 Phase 2：服务端音频缓存

如果后续需要稳定、可复现的高质量美式发音，再引入服务端 TTS 缓存。Phase 2 不阻塞 Phase 1。

建议新增 `pronunciation_audio_assets` 表，作为全局发音缓存，不挂 `word_cards` 外键。同一个词在多本书、多个卡片中共用缓存；删除卡片或删除书籍不自动删除音频。

建议字段：

- `id`
- `normalized_text`
- `accent`，例如 `en-US`
- `provider`
- `voice`
- `model`
- `mime_type`
- `duration_ms`
- `byte_size`
- `storage_path`
- `created_at`
- `last_accessed_at`

唯一键：

```sql
UNIQUE(normalized_text, accent, provider, voice, model)
```

音频文件路径不要只使用 `normalized_text` hash。应对完整缓存键计算 hash：

```text
sha256(accent|provider|voice|model|normalized_text)
```

存储路径采用 hash 分级目录，避免单目录文件过多：

```text
data/assets/audio/{hash[0:2]}/{hash}.mp3
```

Phase 2 的路由与服务：

- `app/audio/pronunciation_service.py`：负责文本规范化、查缓存、调用 TTS、写文件、写库。
- `GET /audio/pronunciation/{asset_hash}` 或等价路由：返回缓存音频，更新 `last_accessed_at`。
- UI 优先播放缓存音频；缓存不存在或生成失败时回退 Phase 1 浏览器 TTS。

Phase 2 测试要求：

- 测音频路由 200 / 404。
- 测 `pronunciation_service` 写库 + 写文件。
- 测文本 normalize 边界：大小写、前后标点、重复空格、词组和习语。
- 英式拼写 `colour` 与美式拼写 `color` 第一版不合并，除非后续新增词形归一化规则。
- GC 不自动跟随卡片删除；仅手动触发，或按 `last_accessed_at` 清理长期未访问且超过空间阈值的音频。

`[新增 2026-06-16]`

---
