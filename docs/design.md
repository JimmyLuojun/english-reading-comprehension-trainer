# 英语阅读理解专项训练系统 — 技术设计地图

> **状态：设计地图（2026-06-17）。**
> 本文件只保留项目范围、当前系统总览和文档入口。详细设计按主题拆到 `docs/architecture/`、`docs/features/`、`docs/decisions/` 和 `docs/state/`。

---

## 0. 范围与非范围

**MVP 范围（第一版必做）**

- TXT / EPUB 导入
- 自动拆分 Book → Chapter → Paragraph → Sentence
- CLI 标记难句 / 生词 / 短语
- AI 难句结构化分析（带响应缓存）
- 生词卡 + lemma / 标签 / 原词三种相似提醒
- SM-2 复习队列
- 每 N 张卡生成一次能力画像摘要

**初始排除（2026-06-14 记录，已实现项以当前系统总览为准）**

- Web UI（已在后续步骤实现，见当前系统总览）
- PDF / OCR
- 向量检索 / 语义聚类
- 多设备同步
- Kindle / 微信读书 / Apple Books 自动同步
- 多用户（单机单用户）

`[已确认 2026-06-14]`

**增补排除（2026-06-15）**

- 多标签页 / 多客户端实时同步
- 键盘快捷键（Cmd+M 标句等，第二版）
- 字号 / 行距 / 主题切换（夜间 / 高对比）；米黄 / sepia 护眼主题已实现，见 §3
- EPUB 中的复杂排版级图片 / 公式重建（第一版只按原书顺序展示图片、公式截图与图注）
- 可访问性 (a11y) / 屏幕阅读器适配
- 打印样式

`[新增 2026-06-15]`

---

## 1. 当前系统总览

- 本地 FastAPI Web UI + SQLite 单机存储。
- 已支持 TXT / EPUB 导入、阅读页选句选词、词卡/句卡、AI 分析缓存、SM-2 Review、Cards、Review Queue、能力画像和 EPUB 媒体展示。
- `app/web/fastapi_app.py` 已拆成薄 app factory；Web 代码按 `routers/`、`queries/`、`views/` 和共享 helper 管理。
- 当前产品化阶段仍是自用稳定化，不引入多用户、OAuth、桌面打包、云端同步或移动原生 App。

---

## 2. 架构文档

- [数据模型与核心实体](architecture/data-model.md)：SQLite 表、错误枚举、词卡类型、跨书去重。
- [导入器设计](architecture/importers.md)：EPUB 重复导入幂等性；PDF 计划见 feature 文档。
- [AI 分析、缓存与 Prompt](architecture/ai-analysis.md)：AI cache、输出 JSON schema、prompt 版本、用户译文诊断和词汇分析面板。
- [复习系统与能力画像](architecture/review-system.md)：SM-2、相似提醒、能力画像生成。
- [Web App 与阅读交互](architecture/web-app.md)：技术栈、阅读 toolbar、阅读视图、诊断面板、词卡提示和浮层状态机。
- [历史开工顺序](architecture/implementation-order.md)：早期实施顺序记录；当前状态以 `STATUS.md` 为准。

---

## 3. 功能设计

- [语音与发音](features/pronunciation.md)：浏览器 TTS MVP 与未来服务端音频缓存。
- [Cards 与 Review](features/cards-review.md)：Cards/Review 信息增强、Notes、Reveal、来源跳转和 EPUB 导入接入。
- [删除导入材料](features/book-deletion.md)：彻底删除书籍/文章、词卡 re-anchor、review log 保留规则。
- [Reader Analysis Panel](features/reader-analysis-panel.md)：AI 分析解释词汇回链、覆盖式面板、阅读位置保持。
- [PDF 导入执行方案](features/pdf-import.md)：计划中的 PDF 导入归一化方案。
- [推理错误层执行方案](features/inference-error-layer.md)：计划中的 `inference` 错误层（I01/I02），补全"词法语法全懂但没读懂意思"的诊断盲区。
- [阅读护眼主题执行方案](features/reading-eye-comfort-theme.md)：已实现的米黄/sepia 护眼主题与头部开关，纯 CSS 变量覆盖，反转 §0 的"主题切换"排除项。
- [审美升级执行方案](features/visual-refresh.md)：已实现的默认观感升级（衬线标题、青绿主色、三级文字层级、统一圆角与柔和表面），纯 CSS 变量层改动，不碰布局/不引外部字体，与 sepia 主题共存。
- [审美升级后续优化](features/visual-refresh-followups.md)：计划中的三项小优化——实心主按钮（视觉层级）、指标等宽数字、内联 SVG favicon 与标题整理，单选择器/`<head>` 改动，零新依赖。

---

## 4. 决策与机器可验证状态

- [PDF import ADR](decisions/2026-06-17-pdf-import.md)：PDF 归一化为句子锚点，不做 PDF viewer 主路径。
- [FastAPI web split ADR](decisions/2026-06-17-fastapi-web-split.md)：Web UI 按 routes / queries / views 拆分。
- [DeepSeek V4 model routing ADR](decisions/2026-06-17-deepseek-v4-model-routing.md)：普通分析默认 Flash，句子分析和手动 Pro 重分析使用 Pro。
- [Minimal recursive AI analysis ADR](decisions/2026-06-18-minimal-recursive-ai-analysis.md)：只用最少字段实现整句→拆解→回到整句→检查点，不新增第二套 Review。
- [Inference error layer ADR](decisions/2026-06-18-inference-error-layer.md)：新增 `inference` 错误层（I01/I02），其余分类缺口（宏观结构、否定/比较范围）暂缓，待真实数据决定。
- [不变量](state/invariants.md)：跨功能必须保持的业务规则。
- [当前 SQLite schema](state/schema.sql)：由真实数据库 `.schema` 生成；schema 迁移后必须更新。
- [产品化路线](productization-roadmap.md)：自用稳定化、后续分发和暂不投入清单。

---

## 评审清单

请对以下小节标 `yes` / `no` / 改：

- [x] §0 范围
- [x] §1 数据模型
- [x] §2 错误标签枚举
- [x] §3 词汇卡类型
- [x] §4 跨书去重
- [x] §5 AI 缓存失效
- [x] §6 EPUB 重导幂等
- [x] §7 SM-2 参数与队列预算
- [x] §8 相似提醒分层 + spaCy 模型选择
- [x] §9 AI JSON Schema
- [x] §10 Prompt 版本管理
- [x] §11 画像生成时机
- [x] §12 技术栈与目录
- [x] §13 开工顺序
- [x] §14 阅读交互：选中即操作（§14.7 Clear→Dismiss 重命名；§14.8 跨句批量取消标记）
- [x] §15 用户译文驱动 AI 诊断
- [x] §16 AI Provider 配置（DeepSeek 默认）
- [x] §17 阅读视图排版
- [x] §18 端到端动线与诊断面板
- [x] §19 词卡悬浮提示与备注编辑
- [x] §20 浮层状态机修复与词卡详情入口统一
- [x] §21 语音与发音：浏览器 TTS MVP 与服务端音频缓存
- [x] §22 词汇 AI 分析面板改进：原文高亮、错因展开、why_this_word、用户笔记区
- [x] §23 Cards 页与 Review Queue 信息增强：Notes/AI Meaning/Source 链接、复习答案 Reveal
- [x] §24 Cards Notes 内联编辑、Review Reveal AI 含义、EPUB 导入接入
- [x] §25 删除导入材料（彻底删除 + 词卡 re-anchor）
- [x] §26 AI 分析解释词汇回链
- [x] §27 AI 分析覆盖式面板
- [x] §28 阅读页操作后保持当前位置
- [x] §29 PDF 导入执行方案
- [x] §30 最小递归式 AI 分析：句子 blocking_point/takeaway_suggestion，词汇 role_in_sentence，复用现有 Review/Takeaway。
