# dimsumstack

A library of reusable agent skills for trading data tooling. Skills live in
`.agents/skills/`, one self-contained folder per skill.

## Skills

| Skill | What it does | Triggers on |
|-------|--------------|-------------|
| [`hl-funding`](.agents/skills/hl-funding/) | Fetch and analyze hourly funding rates for Hyperliquid perps of any asset class — crypto (main dex) plus equity/commodity/FX (trade.xyz dex) — selected via `--asset-class`. | Explicit asks for Hyperliquid funding rates/history (crypto or xyz perps), regenerating a funding master CSV, or analyzing one. |

## Compatibility

Skills use the portable [Agent Skills](https://agentskills.io) format
(`SKILL.md` with `name` + `description` frontmatter). Agents that scan
`.agents/skills/` — ZCode, Codex, Cursor, OpenCode — discover them
automatically when this repo is open; nothing to install.

**Claude Code** does not scan `.agents/skills/` (it uses `.claude/skills/`).
To use these skills there, copy or link the skill folder, e.g. from the repo
root:

```bash
mkdir -p .claude/skills
cp -r .agents/skills/hl-funding .claude/skills/
# or, on macOS/Linux: ln -s ../.agents/skills/hl-funding .claude/skills/
```
