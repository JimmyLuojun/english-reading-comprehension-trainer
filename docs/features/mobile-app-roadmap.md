# Mac 与 iPhone 三阶段移动阅读/App 化路线

> 状态：规划参考，尚未实施（2026-07-13）。
>
> 本文记录从当前本地 FastAPI + SQLite Reader，逐步演进到跨设备阅读、可安装 Web App，乃至原生离线 App 的推荐路线。实施前仍需根据当时的真实需求重新确认范围与 Apple/Tailscale 能力。

## 1. 目标与推荐结论

目标是在 MacBook Pro 和 iPhone 上使用同一套 Reader，连续使用以下数据与能力：

- 精确阅读位置；
- 翻译与句子结构练习；
- AI 分析与缓存；
- 句卡、词卡、Review 日志和 SM-2 调度；
- NotebookLM 手机端问答、Audio、Quiz 和跨章节复盘。

推荐顺序是：

1. 先把 SQLite 变成跨设备唯一事实源，并通过私人网络让手机访问同一后端；
2. 再把现有 Reader 做成 Mac/iPhone 可安装的 Web App；
3. 只有明确需要“Mac 关机后手机仍可离线阅读”时，才进入 SwiftUI + CloudKit/云后端阶段。

前两个阶段可以复用现有产品，难度中等；第三阶段需要重新设计离线数据库、书籍分发和冲突合并，难度显著提高。

## 2. 必须避免的风险

- 不把 FastAPI 监听到 `0.0.0.0`，也不直接暴露到局域网或公网。
- 不使用 Tailscale Funnel；只使用 tailnet 内可见的 Tailscale Serve。
- 不让 localStorage 和 SQLite 同时成为阅读进度的权威来源。
- 不信任电脑或手机的本地时间；冲突顺序由服务器时间和单调版本号决定。
- 不让后台旧标签页覆盖另一设备刚刚保存的新进度。
- 不同步像素滚动值；电脑与手机应以稳定的 chapter/sentence ID 恢复位置。
- 不在首次迁移时删除原 localStorage，必须保留回退窗口。
- 不把完整原生重写作为起点，否则会重复实现 Reader、EPUB、AI 和 SM-2。
- 不把“套一个 App 外壳”误认为离线同步；第一、第二阶段仍依赖 Mac 在线。
- 不建立 Mac App、iPhone App 和 Web 各自独立的训练数据库。

## 3. 总体演进图

### 第一、第二阶段

```text
Mac Web App / iPhone Web App
              │
       Tailscale 私网 HTTPS
              │
     FastAPI（只监听 localhost）
              │
           SQLite
              │
   进度 / 翻译 / AI / SM-2
```

这是“两个客户端访问同一个事实源”，不是两份数据库互相复制。

### 第三阶段

```text
Mac 原生 App ─┐
              ├─ CloudKit 或云端 API ─ 共享数据
iPhone 原生 App ┘
       │
  本地离线副本
```

这是“每台设备有本地副本，恢复联网后合并”，因此必须解决真正的离线冲突。

## 4. 第一阶段：SQLite 进度同步与私人远程访问

### 4.1 目标

让电脑和远程 iPhone 访问同一 FastAPI/SQLite。Mac 保持在线时，手机可以从同一句继续阅读，并直接复用现有翻译、练习、AI 和 SM-2 数据。

估计难度：`4/10`。这是后续所有阶段的基础，必须先完成。

### 4.2 阅读进度模型

新增单用户 `reading_progress` 表，建议包含：

```text
book_id
chapter_idx
top_sentence_id
selected_sentence_id
reader_state_json
revision
updated_at
updated_by
```

约束：

- `book_id` 是第一版主键；多用户不是当前范围。
- `top_sentence_id` 是主要恢复锚点，`chapter_idx` 是回退位置。
- `reader_state_json` 只保存经校验的少量界面字段，并限制大小。
- `updated_at` 由服务器生成 UTC 时间。
- 每次成功保存后 `revision` 单调递增。

### 4.3 进度 API 与冲突规则

新增：

```http
GET /api/books/{book_id}/progress
PUT /api/books/{book_id}/progress
```

客户端保存时携带自己最后读取到的 `base_revision`。服务器在单个 SQLite 事务内执行比较和更新：

1. 版本相同：保存新位置，增加 `revision`，生成新的 `updated_at`；
2. 版本过期：返回 `409 Conflict` 和当前服务器记录；
3. 客户端自动采用服务器最新记录，并给出非阻塞提示；
4. 后续真实用户动作基于新版本继续保存。

这相当于“服务器最新成功版本优先”，同时阻止休眠标签页的迟到写入破坏新进度。客户端时钟只用于诊断，不参与胜负判断。

### 4.4 Reader 保存策略

- 打开书籍时先读取服务器进度，再定位章节和句子。
- 切换章节时立即保存。
- 停止滚动约 1–2 秒后保存当前顶部句子。
- 选中句子后短暂防抖保存。
- 页面进入后台或关闭时，使用支持 keepalive 的请求尽力保存。
- 不在每个 scroll 事件上写 SQLite。
- localStorage 降级为临时缓存和迁移备份，不再是事实源。

### 4.5 现有 localStorage 迁移

上线顺序必须是：

1. 停止写入并备份当前 SQLite；
2. 执行带 checksum、可回退的 schema migration；
3. 仍通过原 `localhost` 来源打开已有阅读进度的书；
4. 数据库无记录而 localStorage 有记录时，执行一次性导入；
5. 写迁移标记并验证 SQLite 位置；
6. 暂时保留原 localStorage；
7. 最后才把正式入口切换到 Tailscale HTTPS。

必须先在 localhost 完成迁移，因为 `localhost` 与 `*.ts.net` 属于不同浏览器来源，不能直接共享 localStorage。

### 4.6 私人网络与认证

- FastAPI 继续只监听 `127.0.0.1`。
- Tailscale Serve 把 localhost 端口代理到 tailnet 内的 HTTPS 地址。
- 明确禁用公网 Funnel。
- Tailscale Grants 只允许本人的身份访问目标服务。
- 后端只接受准确的 Tailscale HTTPS Host/Origin。
- tailnet 请求校验 `Tailscale-User-Login`；localhost 保留现有维护令牌。
- Cookie 使用 `Secure`、`HttpOnly`、`SameSite=Lax`。
- 电脑与手机的正式入口统一为同一个 `https://<machine>.<tailnet>.ts.net` 地址。

### 4.7 完成标准

- 电脑读到某句，手机能恢复到同一句。
- 手机继续阅读后，电脑刷新能恢复手机的新位置。
- 旧标签页不能覆盖新设备进度。
- 手机产生的翻译、AI 分析和 SM-2 Review 可立即由电脑读取。
- 未授权设备、普通局域网地址和公网均不能访问。
- 项目重启后进度仍存在。

## 5. 第二阶段：Mac/iPhone 可安装 Web App

### 5.1 目标

在不重写 Reader 的前提下，让项目在 MacBook Pro 和 iPhone 上拥有 App 图标、独立窗口和更接近原生应用的体验。

估计难度：`3/10`（建立在第一阶段已经完成的前提下），粗略实施周期为 3–7 个专注工作日。

### 5.2 工作范围

- 增加 Web App Manifest、名称、图标、主题色和启动配置。
- 支持 iPhone 添加到主屏幕、Mac 添加到 Dock/独立窗口。
- 调整安全区、触摸目标、软键盘、旋转和小屏布局。
- 增加在线、离线、Mac 不可达和登录过期的明确状态。
- 只缓存安全的静态资源；第一版不缓存完整书籍和训练写操作。
- 保持所有数据写入第一阶段的 FastAPI/SQLite。
- NotebookLM 仍通过其独立 App 完成问答、Audio、Quiz 和跨章节复盘。

### 5.3 明确边界

- Web App 图标不等于完整离线 App。
- Mac 睡眠、关机、断网或 FastAPI 停止时，手机无法使用完整 Reader。
- iPhone 不保存第二份权威 SQLite。
- AI Key 始终留在 Mac 后端，不进入 Web App。

### 5.4 完成标准

- 两个平台均可从图标启动，不需要每次寻找浏览器标签页。
- Reader、翻译、结构练习、AI、Cards 和 Review 在手机尺寸下无阻塞操作。
- 断网或 Mac 不可达时显示可理解的错误，不误报为数据丢失。
- 重新联网后能读取 SQLite 最新进度。
- 第一阶段的冲突和安全测试继续全部通过。

## 6. 第三阶段：SwiftUI 原生离线 App 与云同步

### 6.1 进入条件

只有同时满足下列条件才值得启动：

- 实际使用证明手机 Reader 有稳定高频需求；
- 明确要求 Mac 关机或睡眠时仍可阅读；
- 明确需要离线书籍、系统通知、原生文件导入或 App Store/TestFlight 分发；
- 愿意承担云同步、签名、数据迁移和长期维护成本。

估计难度：`8/10`，完整 MVP 通常按 2–3 个月以上规划，而不是第一、第二阶段的小改动。

### 6.2 推荐架构

优先使用一个 SwiftUI 多平台项目覆盖 iOS 和 macOS：

```text
SwiftUI 多平台 App
├── 共享领域模型与同步层
├── Mac/iPhone 平台适配
├── 本地离线数据（SwiftData/Core Data）
├── CloudKit 或自建云 API
├── EPUB 本地文件/章节资源管理
└── 远端 AI 服务（密钥不进入客户端）
```

过渡期可以先用 WKWebView 复用 Reader 的 HTML/JavaScript，再逐步把真正需要系统能力的部分原生化；不建议一次性重写全部阅读和训练界面。

### 6.3 必须重新设计的部分

- EPUB 如何安全进入两台设备，以及书籍版本如何识别。
- 章节和 sentence ID 如何跨设备保持稳定。
- 本地离线数据库与云端记录的映射。
- 离线修改后的冲突合并，不再只是单服务器 `revision`。
- 翻译、AI 缓存、Cards、Review 日志和 SM-2 的同步边界。
- CloudKit 对唯一约束、关系和 production schema 演进的限制。
- iCloud 未登录、容量不足、同步延迟和账号切换。
- AI 后端托管、认证、限流、成本和密钥保护。
- 现有 SQLite 数据到新模型的一次性可验证迁移。

### 6.4 完成标准

- Mac 关机时，iPhone 仍可打开已下载书籍并记录进度。
- 两端离线修改后重新联网，数据能按明确规则合并。
- 不重复创建 Cards/Review 日志，不倒退 SM-2 状态。
- EPUB、章节与句子锚点在双端一致。
- 云端不可用时不丢本地数据，恢复后可重试。
- AI Key 不存在客户端包、日志或同步记录中。

## 7. 锁屏、熄屏与睡眠条件

第一、第二阶段由 Mac 充当服务器，因此距离不是限制，Mac 的电源状态才是限制。

| Mac 状态 | 手机是否可继续阅读 |
| --- | --- |
| 显示器熄灭、要求密码解锁 | 可以，前提是系统未睡眠 |
| 屏幕保护程序运行、用户会话仍登录 | 可以 |
| Mac 整机睡眠 | 不可以 |
| MacBook 合盖 | 通常不可以，会进入睡眠 |
| 用户退出登录 | 不可以 |
| 重启后停在首次登录/FileVault 解锁界面 | 通常不可以 |
| 关机、断网、FastAPI 或 Tailscale 停止 | 不可以 |

建议运行条件：

- Mac 接通电源；
- 打开“显示器关闭时，防止在接入电源适配器时自动进入睡眠”；
- 继续保持显示器关闭后立即要求密码；
- Tailscale 和 FastAPI 通过受控的登录启动项/LaunchAgent 自动运行；
- 不依赖 Power Nap 或 Wake for network access 保证自定义 Python 服务在线；
- 明确记录：重启并启用 FileVault 后，通常需要先在本机完成一次登录。

锁屏验收：启动项目后锁屏，等待 20–30 分钟；手机关闭 Wi-Fi，使用蜂窝网络完成阅读、翻译或 Review，再解锁 Mac 核对 SQLite 记录。

## 8. 推荐执行顺序与决策门

```text
第一阶段：SQLite + API + Tailscale
        │ 通过跨设备、安全、冲突验收
        ▼
第二阶段：可安装 Web App
        │ 连续实际使用 2–4 周
        ▼
是否必须在 Mac 关机时离线阅读？
        ├─ 否：停留在第二阶段，继续稳定化
        └─ 是：进入第三阶段原生/云同步设计
```

第三阶段开始前，要用真实使用数据回答：

- 手机阅读是否足够高频；
- Tailscale + 常开 Mac 是否已经满足需求；
- 离线时真正需要同步哪些数据；
- 是否愿意把书籍和训练数据交给 iCloud/云后端；
- 原生能力带来的收益是否覆盖长期维护成本。

## 9. NotebookLM 的固定职责

无论进入哪一阶段，NotebookLM 都不承担本项目的精确进度或 SM-2 同步，只负责：

- 手机端针对来源的问答；
- Audio Overview；
- Quiz 和即时检索练习；
- 跨章节人物、事件、论证与主题复盘；
- 对本项目导出的学习证据做引用核查和口试。

详细闭环见 [NotebookLM 协同学习方案](notebooklm-integration.md)。

## 10. 实施时的工程与文档要求

- 新增/修改 Python 文件时同步新增镜像单元测试。
- schema/migration 使用真实 SQLite 集成测试，不 mock。
- 覆盖正常、空数据、错误 book/sentence、过期 revision 和并发保存。
- 使用 `english-reading-trainer/.venv/bin/python` 运行针对性测试、全量 pytest 和 Ruff。
- Web 改动运行 Playwright Reader 回归；移动端增加真实 iPhone/Safari 验收。
- schema 变更后重新生成 `docs/state/schema.sql`。
- 第一阶段落地前新增“服务器进度与私人移动访问”ADR。
- 每个非平凡阶段结束时更新架构文档、产品化路线和 `STATUS.md`。
- 每个阶段必须具有关闭入口、保留数据和恢复备份的回退步骤。

## 11. 外部能力参考

- [Tailscale Serve：tailnet 内代理 localhost 服务](https://tailscale.com/docs/features/tailscale-serve)
- [Tailscale Access Control / Grants](https://tailscale.com/docs/features/access-control)
- [Apple：SwiftUI 多平台 App](https://developer.apple.com/documentation/technologyoverviews/swiftui)
- [Apple：配置多平台 App Target](https://developer.apple.com/documentation/Xcode/configuring-a-multiplatform-app-target)
- [Apple：SwiftData 与 CloudKit 跨设备同步](https://developer.apple.com/documentation/swiftdata/syncing-model-data-across-a-persons-devices)
- [Apple：Mac 睡眠与唤醒设置](https://support.apple.com/guide/mac-help/set-sleep-and-wake-settings-mchle41a6ccd/mac)
