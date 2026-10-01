# Project guidelines

## Changelog (CHANGELOG.md)

- Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Newest
  entry first, directly under `## [Unreleased]`.
- Version headings look like `## [v1.2.3] - YYYY-MM-DD`.
- **Never edit the entry of a version that has already been tagged/released.**
  Changelog entries for released versions are historical record, not drafts.
  Before editing any existing version section, run `git tag -l` and check
  whether a matching tag (e.g. `v1.1.0`) already exists — don't assume based
  on conversation history, which can be stale.
- For new changes:
  - Default: add them under `## [Unreleased]`.
  - If the target version for this change is already decided, ask the user
    to confirm the version number, then add a new `## [vX.Y.Z] - YYYY-MM-DD`
    section for it (do not retroactively modify an existing section).
