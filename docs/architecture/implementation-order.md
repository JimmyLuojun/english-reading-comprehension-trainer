# 历史开工顺序

本文件保存项目早期的开工顺序记录。当前状态以 `STATUS.md` 为准。

## 13. 开工顺序（确认后开始写代码）

```text
1. 建 SQLite schema + migration（含 §1 全部表）
2. 写错因枚举 seed（§2）和 prompt v1（§10）
3. 实现 TXT 导入 + pysbd 切句
4. 实现 EPUB 导入（ebooklib + BeautifulSoup + pysbd）
5. CLI：列书、读章节、标记难句/生词
6. AI 分析器（含缓存 + JSON 校验）
7. 相似提醒第一层（原词 / lemma / 标签）
8. SM-2 复习队列 + 每日预算
9. 能力画像生成
10. （后续）Streamlit / FastAPI UI
```

---
