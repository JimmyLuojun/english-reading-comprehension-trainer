# 回到上次阅读：Books 导航续读 — Executable Plan

Status: implemented (2026-06-18)，取代本文件原先的 "Dashboard Continue 按钮 + 字号" 方案。

## 背景与决策

- 字号放大已实现（`.reader-para` 已是 `font-size: 20px; line-height: 1.8`，`styles.py:266`）。本次不再涉及字号。
- 上一轮把 `_continue_reading_script` 暴露为 `/books` 与 Dashboard 顶部的 "Continue reading" 按钮，机制本身可用（`reader:last-book-id` + `reader:progress:book:{id}` + `?chapter=X&restore=1`），但用户反馈：点 "Books" 落到的是**目录页**，还要再找右上角那个次要按钮点一下，不符合"回到 Books 就接着上次读"的心智。
- **用户选定的体验（2026-06-18）：** 顶部导航 **"Books" 直接续读**（有进度时跳回上次章节+滚动+面板）；新增 **"Library"** 入口看目录；**无阅读历史时 "Books" 仍指向目录**。

## Risks to avoid（先看会踩的坑）

1. **服务端渲染时读不到 localStorage。** 阅读历史只在浏览器里（`reader:last-book-id`），服务端无法在渲染 `<nav>` 时决定 "Books" 指向哪。**必须在客户端改写** `#nav-books` 的 `href`。脚本紧跟 `</nav>` 之后注入，保证 `#nav-books` 已在 DOM 里、改写早于用户点击；改写前有极短时间 href 仍是 `/books`，可接受。
2. **绝不把 `/books` 自动重定向到阅读器。** 那会摧毁目录页本身。目录原封不动保留在 `/books`，只是改名为 "Library" 入口；本次**只改 "Books" 导航链接的目标**，不动路由。
3. **active 高亮要分家。** 阅读器页 = `active="books"`（读书时高亮 Books）；目录页 / 书籍详情 = `active="library"`。不要让两者共用同一个 active key，否则高亮错乱。
4. **删除已冗余的工具栏按钮。** "Books" 导航续读后，Dashboard 与 `/books` 顶部的 "Continue reading" 按钮（`_continue_reading_script`）与导航重复，必须从**两个 router 的调用 + 导入 + `__init__` 导出**一并删除，否则机制重叠且 `ruff check app/web` 报未使用导入。其单测要同步迁移/替换（No untested merge）。
5. **chapter idx ≥ 1**（两个 importer 都是 `enumerate(..., start=1)`），所以 `if (chapter)` 真值判断安全；不要"顺手"改成会破坏"无进度回退到 `/read/{id}`"分支的写法。
6. 本次不动全局字号、布局、reader 宽度/断点；不动进度保存/恢复逻辑本身。

## Files to change

### 1. `english-reading-trainer/app/web/views/layout.py`

**(a) 用 `_resume_nav_script()` 替换 `_continue_reading_script(button_class=...)`**（改写 `#nav-books` 的 href，而非追加按钮）：

```python
def _resume_nav_script() -> str:
    return """
    <script>
      (() => {
        const link = document.getElementById("nav-books");
        if (!link) return;
        let bookId = "";
        try {
          bookId = window.localStorage.getItem("reader:last-book-id") || "";
        } catch (error) {
          return;
        }
        if (!bookId) return;
        let href = `/read/${encodeURIComponent(bookId)}`;
        try {
          const progress = JSON.parse(
            window.localStorage.getItem(`reader:progress:book:${bookId}`) || "null",
          );
          const chapter = Number.parseInt(progress?.chapter_idx, 10);
          if (chapter) href = `${href}?chapter=${chapter}&restore=1`;
        } catch (error) {
          href = `/read/${encodeURIComponent(bookId)}`;
        }
        link.href = href;
      })();
    </script>
    """
```

**(b) 改 `_html_page` 的 `<nav>`：**
- 给 Books 链接加 `id="nav-books"`：`<a id="nav-books" class="{_active(active, "books")}" href="/books">Books</a>`
- 在 Books 之后新增 Library：`<a class="{_active(active, "library")}" href="/books">Library</a>`
- 在 `</nav>` 之后注入 `{_resume_nav_script()}`。

导航顺序变为：`Dashboard | Books | Library | Import | Cards | Review | Profile | 护眼`。

### 2. `english-reading-trainer/app/web/routers/books.py`
- 删除 `_continue_reading_script` 的导入与 `body += _continue_reading_script()` 调用。
- `books()`：`_page_header("Library", "Imported reading material.")` + `_html_page("Library", body, active="library")`。
- `book_detail()`：`_html_page(book["title"], body, active="library")`。

### 3. `english-reading-trainer/app/web/routers/dashboard.py`
- 删除 `_continue_reading_script` 导入与 `{_continue_reading_script(button_class="button")}` 那一行。

### 4. `english-reading-trainer/app/web/views/__init__.py`
- 从 import 与 `__all__` 中删除 `_continue_reading_script`（nav 脚本只在 layout.py 内部调用，无需导出）。

### 5. `english-reading-trainer/app/web/routers/reader.py`
- 不改：保持 `active="books"`，读书时高亮 "Books"（坑 3）。

## Tests（No untested merge）

- **`tests/web/views/test_layout.py`**：
  - 删除 `_continue_reading_script` 导入及其两个测试。
  - 新增 `test_resume_nav_script_rewrites_books_nav`：断言脚本含 `getElementById("nav-books")`、`reader:last-book-id`、`reader:progress:book:${bookId}`、`?chapter=${chapter}&restore=1`、`link.href = href`。
  - 改 `test_html_page_escapes_title_and_marks_active_nav`：断言含 `<a id="nav-books" class="active" href="/books">Books</a>`、含 `href="/books">Library</a>`、含 `getElementById("nav-books")`；把原 `assert "reader:last-book-id" not in body` 翻转为 `in body`。
- **`tests/web/test_fastapi_app.py`**：
  - `test_dashboard_empty`：删除工具栏按钮断言（`"Continue reading"`、`link.className = "button"`），改为断言 `'id="nav-books"'`、`'>Library</a>'`、`"reader:last-book-id"`、`"?chapter=${chapter}&restore=1"` 均在 HTML 中。
  - `test_books_page_lists_imported_book`：删除 `"Continue reading"`、`link.className = "button primary"` 断言；保留 `"/books/1"`、`"reader:last-book-id"`（全局 nav 脚本每页都有）。
- 全局检索并清掉任何对已删除 `_continue_reading_script` 的引用。

## Verification

- `english-reading-trainer/.venv/bin/python -m pytest tests/`（全量），报告实际 `sys.executable`。
- `english-reading-trainer/.venv/bin/python -m ruff check app/web`（守坑 4）。
- 手动：读一本书 → 点任意导航（Cards/Review/…）→ 点 "Books" → 回到上次章节+滚动+analysis 面板；点 "Library" → 看到目录；清空 `reader:last-book-id`（或新浏览器）→ 点 "Books" → 落到目录。
- 更新 `STATUS.md`。

## Explicitly out of scope（不做）

- 不动字号（已是 20px/1.8）、全局 UI 字号、reader 宽度/断点。
- 不把 `/books` 自动重定向到阅读器（坑 2）。
- 不改进度保存/恢复逻辑本身，只改"回到阅读"的入口动线。
