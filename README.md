# Daily Mentor Plugins

A [Claude Code](https://claude.com/claude-code) plugin marketplace for the Daily Mentor ecosystem.

## Install

```
/plugin marketplace add paulcrossland/daily-mentor-plugins
/plugin install report-card@daily-mentor
```

## Layout

```
.
├── .claude-plugin/
│   └── marketplace.json          # marketplace manifest
└── plugins/
    └── report-card/
        ├── .claude-plugin/
        │   └── plugin.json       # plugin manifest
        ├── commands/             # slash commands (.md)
        ├── skills/               # skills (SKILL.md per dir)
        ├── scripts/              # Python pipeline
        ├── templates/            # Jinja2 + assets
        ├── data/                 # benchmarks, defaults, COA, FX cache
        └── tests/                # pytest
```

## Plugins

### report-card

Generate a 12-tab e-commerce diagnostic Report Card (HTML + xlsx) from a standardised 7-file input pack (Shopify CSVs + Xero exports + Meta/Google/TikTok ad spend CSVs). See `plugins/report-card/README.md`.

## Add a plugin

1. Create `plugins/<name>/.claude-plugin/plugin.json`.
2. Drop assets into `commands/`, `agents/`, `skills/`, or `hooks/`.
3. Register it under `plugins[]` in `.claude-plugin/marketplace.json`.
4. Bump the plugin's `version` (semver) on each change.

## Versioning

- Each plugin tracks its own `version` in `plugin.json` and `marketplace.json`.
- Tag releases on `main` (e.g. `report-card-v0.1.0`) so users can pin refs.
