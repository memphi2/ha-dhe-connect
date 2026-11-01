# Installation And Updates

The integration is listed as **Stiebel Eltron DHE Connect**. It is an unofficial
community integration for local devices, not a manufacturer or Home Assistant
Core integration. Its domain is `stiebel_dhe_connect`.

## Requirements

- Home Assistant `2026.11.0` or newer for this integration line. Older Home
  Assistant installations must stay on integration `v2.0.9`.
- The DHE web interface must be reachable from the Home Assistant network.
- Access to the DHE display to confirm pairing when requested.

Use a published stable release for normal operation. A development checkout or
manually copied test build is not a published Marketplace release. Preview HA
builds are used for development validation only, not as stable-release evidence.

## Home Assistant Marketplace

1. Open `Settings` -> `Marketplace`.
2. Search for `DHE Connect` and open **Stiebel Eltron DHE Connect**.
3. Install the integration and confirm the community-integration notice.
4. Open `Settings` -> `Devices & services` -> `Add integration` and select
   **Stiebel Eltron DHE Connect**.
5. Select a discovered device, scan the local subnet, or enter the host and port
   manually. Continue with the pairing flow and confirm on the DHE display.

A first Marketplace installation of an integration with a config flow does not
normally need a restart. Updates and removal of loaded integration code do;
follow Home Assistant's restart request. Installing or copying files does not
by itself prove that the running code has changed.

The repository is already in the shared catalog. Do not add a custom repository
for a normal installation. The Marketplace retains the metadata filename
`hacs.json`; it must not be renamed to `marketplace.json`.

See the official [Marketplace overview](https://contributors.home-assistant.io/marketplace/)
and [custom-integration guide](https://contributors.home-assistant.io/marketplace/guides/integrations/).

## Existing Installations

The longer display name and the manufacturer field `Stiebel Eltron` do not
change config entries, device identifiers, entity unique IDs, tokens or
user-assigned names. Do not delete working entries or pair again just because
the catalog name changed.

Existing HACS installations use the same repository and integration domain.
Keep the working installation and its config entries; use its available update
path. There is no project-specific reinstall or domain migration for the
Marketplace. Do not install a second copy alongside the existing integration.

For address changes, use `Reconfigure` on the existing entry. For an invalid
token, use [Repairs](troubleshooting.md#pairing-required--token-invalid--repairs).

## Updates

1. Back up Home Assistant before updating.
2. Open `Settings` -> `Updates` and read the integration's release notes.
3. Install the offered version and complete the requested Home Assistant restart.
4. Confirm that the DHE entry loads and its connection diagnostic reports
   `connected`.

The Marketplace checks the minimum HA version in each release's `hacs.json` and
does not offer a release that requires a newer HA version. Catalog propagation
can take several hours. Do not reinstall the integration to force an update to
appear. See [releases and updates](https://contributors.home-assistant.io/marketplace/guides/releases/).

## Manual Installation

Use this only for a deliberate manual or development installation. Download the
chosen version and copy the contents of `custom_components/stiebel_dhe_connect/`
to:

```text
/config/custom_components/stiebel_dhe_connect/
```

Keep one complete copy of that folder, including `translations/` and `brand/`.
Do not copy `hacs.json`, tests or the entire repository into it. Back up an
existing integration folder before replacing it, and remove obsolete files from
that folder without touching Home Assistant's `.storage` or config entries.

Restart Home Assistant after replacing code, then add the integration only if
no entry exists yet. Keep existing entries when updating. The maintainer's
HA-test copy procedure and live checks are described in [validation.md](validation.md).

## Removal

1. Open `Settings` -> `Devices & services` and select the integration.
2. Delete the DHE config entries you want to remove. This removes their entities
   and can affect dashboards and automations using them.
3. To remove the integration code too, uninstall its repository from the
   Marketplace. For an existing HACS-managed installation, use HACS instead.
4. For a manual installation, remove only
   `/config/custom_components/stiebel_dhe_connect/` after its entries are removed.
5. Complete the requested Home Assistant restart.

Removing the local entry or stored token is not device-side revocation. If a
token was disclosed, use the device's supported controls and then pair again;
see [SECURITY.md](../SECURITY.md).

## Help

- [Troubleshooting](troubleshooting.md): pairing, discovery and unavailable entities.
- [Entity reference](entities.md): controls, diagnostics and action inputs.
- [German quick guide](de.md): installation and setup in German.
