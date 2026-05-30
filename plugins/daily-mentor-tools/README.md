# Daily Mentor Tools

A Claude Code plugin bundling Daily Mentor's e-commerce mentorship skills. Install once; each skill appears under the **Daily Mentor Tools** group.

## Skills

| Skill | What it does |
|---|---|
| [`report-card`](skills/report-card/) | Generate a 12-tab e-commerce diagnostic Report Card (founder-facing HTML + mentor xlsx) from a standardised Shopify + Xero + ad-platform input pack. Brand- and currency-neutral; quarter-over-quarter NCCM; cohort LTV. |

More skills will be added here over time — each as its own self-contained directory under `skills/`.

## Install

```
/plugin marketplace add Daily-Mentor/daily-mentor-plugins-staging
/plugin install daily-mentor-tools@daily-mentor
```

## Layout

```
plugins/daily-mentor-tools/
  .claude-plugin/plugin.json   # plugin manifest (name: daily-mentor-tools)
  commands/                    # plugin-level slash commands (e.g. /report-card)
  skills/
    report-card/               # self-contained skill: SKILL.md + scripts/ + data/ + templates/ + tests/
```

Each skill owns its own code so skills never collide. See the skill's own README for inputs, usage, and architecture.
