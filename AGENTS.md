# dimsumstack — agent conventions

This repo is a library of reusable agent skills for trading data tooling, not
an application. Skills are consumed in place: agents that scan
`.agents/skills/` discover them automatically when the repo is open; nothing
is installed or imported.

## Layout

- Skills live in `.agents/skills/<name>/` — one self-contained folder per
  skill (`SKILL.md` required; optional `scripts/`, `references/`, `assets/`).
- A script at the repo root is upstream source; once a skill bundles its own
  copy under `scripts/`, the bundled copy is canonical.

## Conventions

- `SKILL.md` frontmatter uses `name` (kebab-case, matches the folder) and
  `description` only — the portable Agent Skills subset (agentskills.io).
  No host-specific frontmatter fields or body features.
- Descriptions are explicit-only triggers: fire on direct asks (e.g.
  "funding rates", "regenerate the funding CSV"), not adjacent phrasings.
  Don't broaden them when editing.
- Bundle working scripts under `scripts/` rather than re-deriving logic in
  conversation. Scripts must run standalone with CLI flags for every
  tunable (no editing constants to change behavior), and the SKILL.md must
  state runtime dependencies (e.g. Python 3 + `requests`).
- Bundled Python scripts carry an embedded PEP 723 dependency header
  (`# /// script` block declaring `requires-python` and `dependencies`) so
  `uv run scripts/<file>.py` works with zero setup. Keep the header in
  sync with the script's real imports.
- Keep `SKILL.md` bodies under ~500 lines; push detail into `references/`.

## Adding a skill

1. Create `.agents/skills/<name>/SKILL.md` (plus `scripts/` if it ships code).
2. Add a row to the Skills table in `README.md` — name, what it does, and
   when it triggers.
3. No install step: compatibility notes for non-`.agents` hosts (Claude Code)
   live in `README.md` under Compatibility.
