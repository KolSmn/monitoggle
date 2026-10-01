# Development

Working on MoniToggle: tests, releases and CI. For using and building
it, see [README.md](README.md) (*How it works* and *Building from
source*).

Requirement: [uv](https://docs.astral.sh/uv/)

## Tests and code layout

```
uv run --extra gui pytest -q
```

Layout: `src/monitoggle/` with `core` (monitor discovery, status and all
commands, used by both front-ends), `cli` (argument parsing), `gui` (tray
app), `monitor_settings` (monitor and input names, shared by both),
`logs` and `backends` (platform-specific monitor discovery).

## Versions and releases

**Version:** the latest git tag, as `git describe --tags --dirty` reports
it (e.g. `v1.4.0`, or `v1.4.0-3-g72dbbd0-dirty` between releases).
`build.py` bakes it into the executables (via a generated, gitignored
`_build_version.py`; on Windows also into the file properties); from
source it is read from git at runtime. Shown by `--version`, in the first
log line of every run, and in the tray app. The package version in
`pyproject.toml` is dynamic too: hatch-vcs derives it from the same tag,
in Python's format (e.g. `1.0.1.dev2+gd091a50` two commits after
`v1.0.0`); there is no version number to update by hand.

**Releases:** pushing a `v*` tag runs CI, builds the Windows and Linux
executables and publishes them as a GitHub release, with the full
`CHANGELOG.md` as release notes. `download_latest_release.py` downloads
the files of the latest (or a given) release into `dist/`.

**Dev releases** (tags like `v1.2.0.dev3`) are cleaned up automatically
daily and after every release: per version only the newest dev release
is kept, and none once the final `v1.2.0` exists; their tags are deleted
too. To run it by hand: *Actions → Clean up dev releases → Run workflow*
(a dry run by default), or locally with the GitHub CLI:
`python cleanup_dev_releases.py --dry-run`.

## Security and license checks

CI checks on every push, pull request and weekly:

- **Dependencies:** `pip-audit` checks every locked package (incl. the GUI
  extra and the build tools) against the PyPI/OSV vulnerability data.
- **Code:** `bandit` scans for insecure patterns. Settings and the reasons
  for the few accepted exceptions are under `[tool.bandit]` in
  `pyproject.toml` and in `# nosec` comments.
- **Licenses:** every runtime dependency is checked against an allow-list
  of MIT-compatible licenses (permissive or LGPL), so a dependency under
  an incompatible license fails the build.

A finding fails CI and blocks release builds. Run the security checks
locally:

```
uv export --all-extras --all-groups --no-emit-project --format requirements-txt -o requirements-audit.txt
uvx pip-audit -r requirements-audit.txt --disable-pip --require-hashes
uvx bandit -c pyproject.toml -r src build.py download_latest_release.py cleanup_dev_releases.py
```

## Translations

The tray app is in English and German; the log file and the CLI output
stay English. Translations live in `src/monitoggle/gui/i18n/`: English
source strings in the code are wrapped in `tr()`, and each language is
one module mapping them to its translation. To add a language, copy
`de.py` to `<code>.py`, translate the values and register it in
`i18n/__init__.py`; the tests check that every language covers all
strings with matching placeholders.
