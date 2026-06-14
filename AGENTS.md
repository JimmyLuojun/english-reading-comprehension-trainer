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

## Shared Memory

**Always write new instructions, rules, and memory to `AGENTS.md` only.**

Never modify `CLAUDE.md` or `GEMINI.md` directly - they only import `AGENTS.md`.
This ensures Claude Code, Codex CLI, and Gemini CLI share the same context consistently.

## Project Structure

- `.claude/agents/` - Custom subagents for specialized tasks
- `.claude/skills/` - Claude Code skills (slash commands)
- `.claude/rules/` - Modular rules auto-loaded into context
- `.codex/skills/` - Codex CLI skills
- `.codex/prompts/` - Codex CLI custom slash commands
- `.gemini/skills/` - Gemini CLI skills
- `.gemini/commands/` - Gemini CLI custom slash commands (TOML)
- `.mcp.json` - MCP server configuration
