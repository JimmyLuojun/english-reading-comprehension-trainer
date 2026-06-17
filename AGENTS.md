# Project Instructions

> 英语阅读理解专项训练系统

## Guidelines

### Testing

- **每个 Python 代码文件都要有对应的单元测试，覆盖尽可能完整。**
  - 测试文件镜像源码目录结构：`app/foo/bar.py` → `tests/foo/test_bar.py`。
  - 覆盖范围：正常路径、边界条件、异常路径、错误输入、空输入。
  - 不允许"无测试合入"。新增或修改函数时同步加/改测试，测试随代码一起 commit。
  - 外部依赖（LLM 调用、SQLite 写入、文件系统、网络）默认 mock，但**数据库迁移和 SQL schema 必须用真实 SQLite 集成测试**，不能 mock。
  - 测试框架：`pytest`。覆盖率工具：`pytest-cov`，目标 ≥ 90% 行覆盖、关键模块（`sm2_scheduler` / `ai_response_cache` / `json_output_validator`）100%。
  - 测试必须可独立运行（`pytest tests/`），不依赖外部网络或环境变量。
  - Web 代码变更后运行 `python -m ruff check app/web`，防止拆分后遗留未使用导入、缺失名称和不清晰依赖。

## Shared Memory

**Always write new instructions, rules, and memory to `AGENTS.md` only.**

Never modify `CLAUDE.md` or `GEMINI.md` directly - they only import `AGENTS.md`.
This ensures Claude Code, Codex CLI, and Gemini CLI share the same context consistently.

## AI-Managed Documentation

- Keep `docs/design.md` as the architecture map and document index. Do not keep adding long feature execution plans to it.
- Put evolving feature designs in `docs/features/`.
- Record non-trivial architecture decisions as ADRs in `docs/decisions/`; use them to avoid re-litigating settled choices.
- Keep machine-checkable project truth in `docs/state/`. `docs/state/schema.sql` must be generated from the real SQLite schema, not hand-maintained from prose.
- Update `STATUS.md` at the end of non-trivial project work with current state, in-flight work, next steps, known issues, and recent verification.
- One fact should have one source of truth. Prefer links from overview docs instead of copying the same detailed design into multiple files.

## Project Structure

- `.claude/agents/` - Custom subagents for specialized tasks
- `.claude/skills/` - Claude Code skills (slash commands)
- `.claude/rules/` - Modular rules auto-loaded into context
- `.codex/skills/` - Codex CLI skills
- `.codex/prompts/` - Codex CLI custom slash commands
- `.gemini/skills/` - Gemini CLI skills
- `.gemini/commands/` - Gemini CLI custom slash commands (TOML)
- `.mcp.json` - MCP server configuration
