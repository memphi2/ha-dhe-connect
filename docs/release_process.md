# Release Process

This checklist describes the repository release flow.

## 1) Preparation

- Update version references (`manifest`, `README`, `CHANGELOG`)
- Move release items out of `Unreleased`
- Keep `Unreleased` with `- No changes yet.`

## 2) Validation Gate

Run:

```bash
python scripts/check_coverage.py
python scripts/check_integration.py
python scripts/check_deprecations.py
python scripts/check_typing.py
python -m ruff check custom_components/stiebel_dhe_connect tests scripts
python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent
```

Optional lab checks (network dependent):

- `scripts/zeroconf_smoke.py`
- `scripts/ha_test_smoke.py`
- `scripts/ha_test_api.py`

## 3) PR Phase

- Open PR
- Wait for CI (HACS, Hassfest, repository checks)
- Trigger Codex review
- Fix all findings
- Re-run review until no open findings remain

## 4) Merge And Publish

- Merge PR
- Create tag/release
- Run post-release verification:

```bash
python scripts/release_check.py --expect-tag present --expect-github-release present --require-current-tag
```

## 5) HACS Default Update

- Update existing `hacs/default` PR (or open one if missing)
- Refresh release link and successful action links

## 6) Hygiene

- Prune stale branches
- Ensure clean local worktree
- Confirm no secrets/private infra details in release notes or PR text
