# Release Notes (next release)

## Scope
This draft covers the next version after `0.7.6`.
Current integration version in `manifest.json`: `0.7.6`.

## [Unreleased]

### Planned
- Bump integration version from `0.7.6` to `0.7.7`.
- Refresh release-facing docs so they match the shipped entity set and behavior:
  - `README.md`
  - `info.md`
  - `CHANGELOG.md`
- Verify installation and upgrade instructions for HACS and manual setup.

### QA checklist before publish
- Confirm `custom_components/stiebel_dhe_connect/manifest.json` contains the final target version.
- Confirm translated UI strings remain in sync in:
  - `custom_components/stiebel_dhe_connect/translations/en.json`
  - `custom_components/stiebel_dhe_connect/translations/de.json`
- Validate docs against currently exposed entities and remove stale references.
- Run a restart/reload smoke test in Home Assistant and verify entities load without warnings.

### Release text (candidate)
- Maintenance release with documentation and metadata alignment for the current integration behavior.

---

## [0.7.6] - 2026-05-07

### Included
- Bump integration version to `0.7.6`.
- Refresh and align repository docs with the current entity set and installation flow.
- Remove redundant release artifact notes from the repository root.
