# Legal And Asset Hygiene

This repository is an unofficial community project for local Home Assistant
interoperability with compatible DHE Connect devices.

It is not affiliated with, endorsed by, sponsored by or otherwise approved by
any device manufacturer, Home Assistant, HACS or their respective owners.
Product and project names are used only to describe compatibility.

## Trademark Notice

Names such as STIEBEL ELTRON, DHE Connect, Home Assistant, HACS, and Nabu Casa
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
