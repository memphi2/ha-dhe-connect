# Legal And Asset Hygiene

This repository is an unofficial community project for local Home Assistant
interoperability with compatible DHE Connect devices.

It is not affiliated with, endorsed by, sponsored by or otherwise approved by
any device manufacturer, Home Assistant, the Marketplace, HACS or their respective owners.
Product and project names are used only to describe compatibility.

## Trademark Notice

Names such as Stiebel Eltron, DHE Connect, Home Assistant, HACS, and Nabu Casa
are used strictly for compatibility reference. All trademarks and product names
belong to their respective owners. This project does not claim any trademark
rights or brand affiliation.

The project must not contain vendor JavaScript, CSS, HTML, firmware,
screenshots, product artwork, logos or copied web-interface templates. The
bundled files under `custom_components/stiebel_dhe_connect/brand/` are original
project artwork and intentionally avoid vendor logos and copied product marks.

Protocol documentation in this repository records observed interoperability
behavior only. It is not a copy of, or a substitute for, any vendor software,
vendor documentation or vendor specification.

Release validation scans tracked files for common secret material, generated
artifacts, proprietary DHE web assets and known proprietary license/copyright
markers. It also runs a repository-owned deprecation guard across code,
workflow and documentation files so warning suppression is not used as a
substitute for fixing owned deprecated APIs. If a future change needs
additional third-party material, document the license before committing it.

## Asset Inventory

The repository's [MIT license](../LICENSE) covers project contributions.
The following inventory records the assets supplied with this project and their
repository provenance; it does not grant rights to third-party trademarks or UI
elements shown in a screenshot.

| File | Size | Source and license scope |
|---|---|---|
| `custom_components/stiebel_dhe_connect/brand/icon.png` | 256 x 256 | Original project artwork, included in commit `166ed1b`; project MIT license. Not a manufacturer logo. |
| `custom_components/stiebel_dhe_connect/brand/icon@2x.png` | 512 x 512 | Same project artwork; originally `brand/logo.png` in `166ed1b`, renamed in `a29fa0c`; project MIT license. |
| `assets/dhe-connect-card.png` | 610 x 568 | Project-provided dashboard screenshot illustrating [ha-dhe-connect-card](https://github.com/memphi2/ha-dhe-connect-card), included in `166ed1b`. Project contributions are MIT; depicted third-party UI elements and marks retain their owners' rights. Not a DHE vendor-interface capture. |

No external logo is fetched at runtime. Replacements must record their actual
source and applicable license here before being added. A repository commit alone
is not evidence of permission for externally sourced artwork. Do not introduce a
manufacturer logo merely because its URL is publicly accessible.

## Maintainer Provenance Gate

`scripts/check_legal_audit.py` compares every tracked image with
[asset_provenance.json](asset_provenance.json), including its SHA256, recorded
origin and rights scope. Replacing artwork requires reviewing and updating both
inventories. The hashes freeze the currently documented files; they do not prove
authorship, ownership or permission for a new asset.

The replay files under `tests/fixtures/firmware_*/` are synthetic test vectors,
not device traffic captures. Their explicit `provenance` object records
`docs/protocol.md` as the interoperability reference, artificial data and the
project MIT license. Firmware profile labels are test scenarios, not proof that
a particular manufacturer firmware was tested. Raw HAR/PCAP dumps, firmware
images and vendor software must not be committed as fixtures.

The same gate checks the exact committed bytes used by `build_release.py`:
component code/metadata, translations, the two documented brand images and
LICENSE. Undocumented package paths, changed artwork and known secret/vendor
content markers fail preparation. CI and the local release checks run the gate.
This is a consistency and content check, not legal clearance or a substitute for
reviewing rights when new third-party material is proposed.
