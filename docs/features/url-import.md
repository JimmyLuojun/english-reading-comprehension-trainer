# URL 导入执行方案

实现状态：已落地。Import 页面新增 "Import from URL"，提交到 `POST /import/url`。后端下载远程 HTML/plain-text 页面，抽取可读正文后复用现有 TXT 导入链路；`source_format='txt'`，并独立记录 `import_method='url'` / 原 URL `source_uri`，Auto 内容类型为 `article`。

## 1. 目标

让用户可以从普通网页 URL 导入英文文章，导入后立刻进入现有 Reader，继续使用选句、选词、AI analysis、Cards 和 Review。

## 2. 当前行为

输入字段：

- URL：必填，只允许 `http://` / `https://`。
- Title：可选；留空时优先使用页面 `<title>`，再退回到既有自动标题逻辑。
- Author：可选；按普通 TXT 导入的 author 写入。

下载限制：

- 最大 10 MB。
- 请求超时 10 秒。
- 最多 5 次重定向。
- 校验最终重定向 URL。
- 拒绝本地与私网 host：`localhost`、loopback、private、link-local、multicast、unspecified IP。
- 只接受 `text/html`、`application/xhtml+xml`、`text/plain`。

正文抽取：

- `text/plain` 直接按纯文本归一化空行和空白。
- HTML 使用 BeautifulSoup。
- 删除 `script/style/nav/header/footer/aside/form/iframe/svg` 等页面 chrome。
- 优先抽 `article`，其次 `main`，最后 `body`。
- 提取 `h1-h4 / p / li / blockquote / pre` 文本块，块之间以空行连接。
- 如果没有块级元素，退回到容器全文。

导入：

- 抽出的正文编码为 UTF-8 bytes。
- 调用 `import_text_bytes()`。
- 重复检测复用 TXT 的 `file_hash` 逻辑。
- 成功后跳转 `/read/{book_id}`。

## 3. 当前非目标

- 不远程下载 PDF/EPUB；远程 PDF/EPUB 仍需用户先下载再上传。
- 不跟踪最终 redirect URL 或网页版本历史；`source_uri` 保存用户提交的原 URL。
- 不新增 `source_format='url'` 或 `source_format='web'`。
- 不做登录页、付费墙、动态 JS 渲染页面的浏览器级抓取。
- 不做正文抽取质量的复杂启发式或 readability 算法。

## 4. 测试与覆盖

- `app.web.services.imports`、`app.web.routers.imports`、`app.web.views.imports`、`app.web.config` 的 URL 导入相关覆盖已拉到 100%。
- 网络测试使用 `httpx.MockTransport`，不访问外网。
- 全量测试仍离线可跑。

## 5. 后续升级

- 如需要 provenance 历史，再增加独立 `web_sources` 表记录最终 URL、抓取时间和版本。
- Library 已可按 content type/status/tag 过滤；如需单独管理 Web source，再增 source filter。
- 引入更强的正文抽取策略，但必须保持测试可离线、可控。
- 如果要做外部网页选句分析，另起 `docs/features/external-web-sentence-analysis.md`，不要把浏览器扩展职责混进 URL 导入器。
