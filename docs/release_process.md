# Release Process

This checklist is for maintainers publishing Marketplace updates. User-facing
installation and update steps are in [installation.md](installation.md).

## 1) Preparation

- Update version references (`manifest`, `README`, `CHANGELOG`)
- Move release items out of `Unreleased`
- Keep `Unreleased` with `- No changes yet.`
- Keep the minimum Home Assistant version aligned in `hacs.json`, README and
  validation policy. The integration manifest version must match the release tag.
- Keep `hacs.json`: the Marketplace still reads that filename.
- Use stable Home Assistant and matching official test helpers in
  `requirements-ha.txt` before publication. A preview-only validation run is not
  a stable release gate; follow [validation.md](validation.md).
- Retain the HA 2026.10 compatibility path and minimum `2026.10.4` when moving
  the HA 2026.11 baseline to stable. Replace only the two primary baseline pins,
  validate a clean environment, then move the prepared changelog items into the
  current version section and set its publication date.

## 2) Validation Gate

Use the canonical command set from [validation.md](validation.md).

For release-prep gating, run at minimum:

```bash
python scripts/release_check.py --run-local-checks --expect-tag absent --expect-github-release absent
```

Optional lab checks are listed in [validation.md](validation.md) and remain
network/infrastructure dependent.

## 3) PR Phase

- Open PR
- Wait for CI: the check named `HACS` validates the shared catalog metadata;
  Hassfest, repository checks, HA 2026.10 compatibility and CodeQL must pass too.
- Request Code Review with `@codex review` and Security Review with
  `@codex security review`, unless both already cover the current head.
- Fix actionable findings, rerun checks and request review of the new head.
- Before merging, verify mergeability, checks, unresolved comments and the
  completed Code Review and Security Review results against the exact current
  commit. Confirm the Security Review completion/report, not just an empty
  comments list. Resolve addressed threads after checking the fix.
- Inspect open code-scanning alerts separately from the CodeQL workflow result.

## 4) Merge And Publish

- Merge PR
- Check out the exact release commit with a clean tracked worktree and build
  the supplemental installation archive and its verification assets:

  ```bash
  python scripts/build_release.py
  python scripts/build_release.py --verify .release
  ```

- Attach `.release/ha-dhe-connect.zip`, `SHA256SUMS`, `build-metadata.json` and
  `sbom.spdx.json` to the release. The ZIP contains component files at its root
  plus the project LICENSE; extract it into `custom_components/stiebel_dhe_connect/`.
  Only committed Git blobs are packaged. Untracked files are never included;
  tracked changes, symlinks and generated component files fail the build.
  Fixed ZIP metadata, uncompressed entries and the commit timestamp make all
  four assets byte-for-byte reproducible. The SPDX inventory describes this
  integration archive only, not Home Assistant's dependency environment.
- Publish a GitHub release with the matching version tag. A tag alone is not a
  published Marketplace update.
- Verify that the released `custom_components/stiebel_dhe_connect/` includes
  the manifest, Python modules, translations and local brand images.
- Run post-release verification:

```bash
python scripts/release_check.py --expect-tag present --expect-github-release present --require-current-tag
```

Download the four attached assets into a temporary directory and compare them
with the checked-out release commit using
`python scripts/build_release.py --verify /path/to/downloaded-assets`.
This rebuild comparison detects changed content even if its checksums were
replaced too. It is not a cryptographic publisher signature. Marketplace
delivery still uses the repository source; `hacs.json` does not opt into ZIP
delivery. These additional assets do not change existing update behavior.

## 5) Catalog Delivery

The repository is already listed in the shared catalog. No catalog PR is needed
for routine releases. Do not open or refresh a `hacs/default` submission for
every version.

The catalog discovers the published release, then the Marketplace offers it
under `Settings` -> `Updates`. Allow time for catalog refresh; do not promise
immediate availability. Each release's `hacs.json` controls its HA minimum.
See the official [release delivery guide](https://contributors.home-assistant.io/marketplace/guides/releases/).

## 6) Hygiene

- Prune stale branches
- Ensure clean local worktree
- Confirm no secrets/private infra details in release notes or PR text
