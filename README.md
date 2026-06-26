# Daily Mentor Plugins

A [Claude Code](https://claude.com/claude-code) plugin marketplace for the Daily Mentor ecosystem.

## Install

```
/plugin marketplace add Daily-Mentor/daily-mentor-plugins-staging
/plugin install daily-mentor-tools@daily-mentor
```

## Layout

```
.
├── .claude-plugin/
│   └── marketplace.json              # marketplace manifest
└── plugins/
    └── daily-mentor-tools/
        ├── .claude-plugin/
        │   └── plugin.json           # plugin manifest (name: daily-mentor-tools)
        ├── commands/                 # slash commands (e.g. /report-card)
        ├── skills/
        │   └── report-card/          # Report Card skill: SKILL.md, scripts/, data/, templates/, tests/
        └── README.md
```

## Plugins

### daily-mentor-tools

Daily Mentor toolkit for Claude Code — a suite of e-commerce mentorship skills.

| Skill | What it does |
|---|---|
| [`report-card`](plugins/daily-mentor-tools/skills/report-card/) | Generate a 12-tab e-commerce diagnostic Report Card (founder-facing HTML + mentor xlsx) from a standardised Shopify + Xero + ad-platform input pack. Brand- and currency-neutral; quarter-over-quarter NCCM; cohort LTV. |

See [`plugins/daily-mentor-tools/skills/report-card/README.md`](plugins/daily-mentor-tools/skills/report-card/README.md) for required inputs, export steps, and usage.

## Add a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json`.
2. Drop assets into `commands/`, `agents/`, `skills/`, or `hooks/`.
3. Register it under `plugins[]` in `.claude-plugin/marketplace.json`.
4. Bump the plugin's `version` (semver) on each change.

## Versioning

- Each plugin tracks its own `version` in `plugin.json`, `marketplace.json`, and any skill `SKILL.md` frontmatter.
- Tag releases on `main` (e.g. `daily-mentor-tools-v0.5.2`) so users can pin refs.
