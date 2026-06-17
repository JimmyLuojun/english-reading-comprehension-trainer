# 删除导入材料

本文件保存彻底删除书籍/文章以及词卡 re-anchor 的设计。相关不变量也记录在 `docs/state/invariants.md`。

## §25 删除导入材料（彻底删除 + 词卡 re-anchor）

### §25.1 背景

`books` 表同时承载 TXT 文章和 EPUB 书籍。当前没有任何删除入口，用户误导入或不再需要的材料只能用脚本手工清理，会留下 `chapters/paragraphs/sentences/sentence_cards/word_cards/review_logs/book_assets/chapter_blocks` 以及磁盘上的 EPUB 图片资源。

本节定义"从 Books 页删除一本书"的语义为**彻底删除**，而不是从列表隐藏。

### §25.2 设计原则

1. **句卡跟着书走**：`sentence_cards` 与某本书的具体句子强绑定，书没了卡就没了，复习历史一并清空。
2. **词卡尽量保留**：`word_cards` 按 `lemma` UNIQUE，可能在多本书中复习过。删书时优先把 `first_sentence_id` 迁移到剩余书中包含同一 lemma/短语的句子，**仅当再也找不到锚点时才删除**。
3. **可迁移词卡的 SM-2 状态与 ****`review_logs`**** 必须保留**，不允许在 re-anchor 之前粗暴删 `review_logs`。
4. **AI 缓存不动**：`ai_cache` 按 `content_hash` 跨书共享，删书时保持原状，`sentence_cards.ai_analysis_id` 已经是 `ON DELETE SET NULL`，自然无悬挂。
5. **磁盘资源跟在 DB 之后**：先在事务内完成 DB 删除，commit 之后再 `shutil.rmtree(..., ignore_errors=True)` 删 EPUB asset 目录。文件清理失败不回滚 DB。

### §25.3 UI

Books 列表表 (`/books`) 增加 `Actions` 列，每行一个 Delete 表单：

```html
<form method="post" action="/books/{book_id}/delete" class="inline">
  <button class="danger"
          onclick="return confirm('Delete this book and all related sentence cards? Word cards that also appear in other books will be kept and re-anchored.')">
    Delete
  </button>
</form>
```

- 仅在列表页提供 Delete，详情页 `/books/{book_id}` **不**加二级入口，避免误点。
- 删除成功后 `302 → /books`；book 不存在返回 404 错误页。

### §25.4 后端路由

```python
@web_app.post("/books/{book_id}/delete")
def delete_book(book_id: int) -> Any:
    db = db_factory()
    result = _delete_book(db, book_id)
    if result is None:
        return _error_page("Book not found", status_code=404)
    _purge_book_assets_dir(db, book_id)  # commit 之后，错误吞掉
    return _redirect("/books")
```

返回值 `result` 暴露统计信息用于日志：`sentence_cards_deleted`、`word_cards_reanchored`、`word_cards_deleted`、`review_logs_deleted`。

### §25.5 删除流程（单事务）

外键 `word_cards.first_sentence_id ON DELETE RESTRICT` 决定了不能直接 `DELETE FROM books`，必须先处理词卡。流程严格按下列顺序：

1. **确认存在**：`SELECT id FROM books WHERE id = ?`，不存在直接返回。

2. **删句卡复习日志**：

   ```sql
   DELETE FROM review_logs
   WHERE card_type = 'sentence'
     AND card_id IN (
       SELECT sc.id FROM sentence_cards sc
       JOIN sentences s ON s.id = sc.sentence_id
       WHERE s.book_id = ?);
   ```

   `sentence_cards / sentence_card_tags / sentence_card_errors` 不需要显式删，会随 `sentences` → `sentence_cards` 的 cascade 自动消失。

3. **查出该书锚定的所有词卡**：

   ```sql
   SELECT wc.id, wc.lemma, wc.surface_form, wc.lexical_type
   FROM word_cards wc
   JOIN sentences s ON s.id = wc.first_sentence_id
   WHERE s.book_id = ?;
   ```

4. **尝试 re-anchor**（在 Python 里逐张做，不在 SQL 里用 `instr` 模糊匹配）：

   - 拉出**其他书**的候选句子集合（懒加载，按需 `SELECT id, text FROM sentences WHERE book_id != ?`）。
   - 匹配规则：
     - `lexical_type='word'`：在候选句子上做 token 切分，命中 `surface_form` 或 `lemma`（大小写不敏感，词边界严格），返回第一个匹配的 `sentence_id`。
     - `lexical_type='phrase' / 'collocation'`：把候选句子和 `surface_form` 各自 `re.sub(r'\s+', ' ', s.strip().lower())` 规范化后做包含匹配。
   - 命中：`UPDATE word_cards SET first_sentence_id = ? WHERE id = ?`，归入"保留集合"。
   - 未命中：归入"待删除集合"。

   > 注：不使用 `instr(lower(text), lemma)`，因为 `cat` 会误中 `education`、`concatenate`；短语也需要规范化空白后做包含匹配。

5. **仅对"待删除集合"删 ****`review_logs`**：

   ```sql
   DELETE FROM review_logs
   WHERE card_type = 'word'
     AND card_id IN (...待删除 word_card_ids...);
   ```

   保留集合的 `review_logs` 一律不动。

6. **删"待删除集合"的词卡**：

   ```sql
   DELETE FROM word_cards WHERE id IN (...);
   ```

   `word_card_tags / word_card_errors` 随 `word_cards` cascade。

7. **删 book**：

   ```sql
   DELETE FROM books WHERE id = ?;
   ```

   `chapters / paragraphs / sentences / book_assets / chapter_blocks` 全部走 cascade。

8. **commit**。

9. **清理磁盘**（事务外）：

   ```python
   shutil.rmtree(data_dir / "assets" / "books" / str(book_id), ignore_errors=True)
   ```

   失败仅记录日志，不回滚。

### §25.6 不变量

- `ai_cache` 行数前后不变。
- 其他书的 `sentences / sentence_cards / word_cards / review_logs` 不受影响。
- 可迁移词卡删书前后 `ef / interval_days / repetitions / review_count / due_at / archived_at / user_note / current_meaning` 完全一致，仅 `first_sentence_id` 变化。
- 可迁移词卡对应的 `review_logs` 一行不少。
- 待删除词卡的 `review_logs` 全部清空，其他书的同类 `review_logs` 不受影响。

### §25.7 测试要求（`tests/web/test_fastapi_app.py` 等）

外键约束依赖 `PRAGMA foreign_keys = ON`，测试必须走真实 `db_factory()`，不允许 mock DB。

必须覆盖：

1. **404**：删不存在的 book 返回 404。
2. **UI**：Books 列表渲染 `Delete` 按钮和 `POST /books/{id}/delete` 表单；删除后 302 到 `/books`。
3. **TXT 完整链**：删 TXT book 后，`books / chapters / paragraphs / sentences / sentence_cards / sentence_card_tags / sentence_card_errors` 涉及该书的行清零。
4. **EPUB 资源**：删 EPUB book 后，`book_assets / chapter_blocks` 清零；`data/assets/books/{book_id}/` 目录被删；目录不存在或权限错时 DB 已提交不回滚。
5. **review\_logs 隔离**：删 book A 不影响 book B 的句卡/词卡 `review_logs`。
6. **ai\_cache 保留**：删 book 前后 `SELECT COUNT(*) FROM ai_cache` 不变。
7. **多书隔离**：两本书各有句卡词卡，删其一不影响另一本任何表的数据。
8. **词卡 re-anchor 成功**：词卡 anchor 在 book A，lemma 在 book B 中以 surface 形式出现 → 删 A 后词卡仍在，`first_sentence_id` 指向 B 的句子；`review_logs` 一行不少；SM-2 字段不变。
9. **词卡 re-anchor 失败 → 删除**：词卡 anchor 在 book A，其他书无此 lemma → 删 A 后词卡和它的 `review_logs` 全部清空，但其他书的 `review_logs` 不受影响。
10. **短语 re-anchor**：`lexical_type='phrase'` 的卡，其他书句子中以不同空白形式出现同一短语 → 能命中并迁移。
11. **词边界严格性**：`lemma='cat'`，其他书只出现 `education` / `concatenate` → 不命中，按未命中处理。

### §25.8 排除项

- 不做"软删除/回收站"。删除就是物理删除。
- 不导出书的备份。用户应在删除前自行 `cp data/reading_trainer.db` 或走现有 `data/reading_trainer.before-*.db` 备份机制。
- 不引入新迁移文件，不改任何 schema。本节只新增路由、删除流程函数、测试和模板片段。
- 不在详情页 `/books/{id}` 加 Delete 入口（一处入口足够，避免误操作面）。

---
