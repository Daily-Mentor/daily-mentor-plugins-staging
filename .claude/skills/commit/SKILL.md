---
name: commit
description: Commit and push changes in this repo, following the plugin versioning and release-tagging conventions.
---

Commit the current changes and push to GitHub. Follow these steps:

1. Run `git status` and `git diff` to review what changed. If there are no changes, say so and stop. If `git config user.email` is unset, warn the user and stop — otherwise git guesses a bogus identity from the hostname.

2. If any files under `plugins/<name>/` changed (plugin content, not just repo docs):
   - Bump that plugin's `version` (semver) in `plugins/<name>/.claude-plugin/plugin.json`, in `.claude-plugin/marketplace.json`, and in any affected skill's `SKILL.md` frontmatter — all three must match.
   - Patch bump for fixes, minor bump for new features or skills.
   - If the version was already bumped in this change, don't bump again.

3. Stage the relevant files and commit directly to `main`. Write the message as one plain sentence describing the change, ending with a period (see `git log` for style). Mention the version in the message when one was bumped, e.g. "... (v0.5.3)".

4. Push to origin.

5. If a plugin version was bumped, also tag and release:
   - `git tag vX.Y.Z && git push --tags`
   - `gh release create vX.Y.Z --title "<plugin-name> vX.Y.Z" --notes "<one-line summary>"`
   - If the release step fails, the tag is already pushed — tell the user the exact `gh release create` command to run once the issue is fixed, so tag and release don't drift.

Report the commit hash and, if released, the tag.
