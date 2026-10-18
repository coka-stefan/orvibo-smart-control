# ORVIBO Smart Control

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.2.6b18-2f6f4e.svg)](custom_components/orvibo_smart_control/manifest.json)

ORVIBO Smart Control is an independent custom integration for Home Assistant. It combines direct MixPad gateway LAN access and the ORVIBO cloud protocol in one device, state, and control path: actions that can be completed over LAN are preferred locally, while devices that cannot be controlled locally and failed requests are handled by the cloud.

This fork uses English throughout the repository. The only retained Chinese
input strings are documented compatibility keywords and protocol fixtures;
see [the language policy](LANGUAGE_POLICY.md). CI rejects unreviewed additions.

## Transport policy

The default `LAN + cloud` mode maintains both local and cloud capabilities, but each control action selects one initial path:

```text
Device request
  |
  +-- Pure cloud --------------------------------> Cloud TLS long connection
  |
  +-- Pure LAN + LAN-supported device + gateway reachable --> LAN TCP
  |      +-- Unsupported / unreachable / execution failed --> Fail; no cloud fallback
  |
  +-- Combined mode + cloud-only device ----------> Cloud TLS long connection
         +-- LAN-supported + gateway reachable ---> LAN TCP
         |      +-- LAN fails once --------------> Retry through cloud once
         +-- Other cases -------------------------> Cloud TLS long connection
```

State updates enter a field-level state store with this priority:

```text
LAN > cloud live push (SSL) > cloud snapshot (REST) > optimistic state > initial value
```

Lower-priority stale values cannot roll back a newly received LAN state during its protection window. Identical values are deduplicated. Locks `107/522` and clothes dryers `52` are cloud-only types; lock events, media, and temporary passwords always use the cloud. Keep the default combined mode or use pure cloud mode to keep these devices available.

Device availability is based on cloud snapshots and live reports. A light does not become “unavailable” merely because it has not reported a change for a long time. When there is no new report, the most recently known state is retained; an explicit cloud offline report is still shown as unavailable.

Pure LAN is a runtime transport restriction, not a fully offline installation: first startup and reload still log in to the ORVIBO cloud to confirm the account region, family, device inventory, gateway UID, and trusted address. After discovery, it does not establish the cloud TLS live connection or run periodic cloud snapshot polling.

For implementation details and failure boundaries, see [Runtime Architecture](FUSION_DESIGN.md).

## Installation

### HACS custom repository

[![Open repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=maycode0-0&repository=orvibo-smart-control&category=integration)

1. In HACS, open “Integrations” and choose “Custom repositories.”
2. Add `https://github.com/maycode0-0/orvibo-smart-control` and select the “Integration” category.
3. Install **ORVIBO Smart Control** and restart Home Assistant.
4. Go to “Settings → Devices & Services → Add Integration” and search for the project name.

### Live camera and NVR video

`0.2.6b5` creates `camera` entities for matching Meari XTS/p2p=2 cameras and online NVR channels.
Update to `v0.2.6b18` in HACS and restart Home Assistant, then open the NVR device page and select a camera entity such as “Channel 1” or “Channel 3.” You can also add the entity to a picture glance card and set `camera_view: live`.
HAOS includes FFmpeg; no separate video service is needed. The first connection needs authorization and device setup and may take tens of seconds. If the first thumbnail request times out, open it again to reuse the connection being established.

A real HEVC keyframe was received on the user's channel 1; local synthetic HEVC-to-H.264 transcoding and decoding tests passed. The user confirmed that live channel 1 is viewable; channel 3 becomes viewable after waiting for it to load. The “ORVIBO Recording Playback” dashboard card searches hard-drive or SD/TF card clips by the date on the device and plays them. `0.2.6b8` added an “SD Card Playback” entity for matching Meari XTS/p2p=2 cameras such as the Jumu 2K Smart Camera S1; after updating, make sure the device is selected in the integration.
**Hard-drive and SD card search and playback still need validation on real devices.** There is currently no audio.
To add the manual card, use `type: custom:orvibo-smart-control-nvr-card`; see [Recording Playback Instructions](docs/meari-hdd-playback.md).
Reload the integration if the online channel list changes. Pure LAN mode cannot obtain the required cloud authorization.
By default, publish temporary diagnostic versions such as `v0.x.ybN`. Use a stable version such as `v0.x.y` only when explicitly asked to “publish a stable release.” Both version types are published as ordinary GitHub Releases / Latest, not marked as Pre-release, so HACS can detect updates.
For details and troubleshooting, see [Live Video](docs/meari-live-video.md) and the [NVR Diagnostics Guide](docs/nvr-video-diagnostics.md).

### Manual installation

Place the `custom_components/orvibo_smart_control` directory under Home Assistant's configuration directory in `custom_components/`, confirm the final path below, then restart:

```text
<ha-config>/custom_components/orvibo_smart_control/manifest.json
```

For upgrades, replace the entire component directory to avoid leaving old modules behind.

## Initial setup

The setup flow validates the account, detects its cloud region, selects a family, then selects devices. China and international regions are stored separately per config entry and do not overwrite one another. The account password is used only at submission time to generate the uppercase MD5 digest required by the protocol. The config entry does not store plaintext, but the digest can still be used directly for authentication and must be protected like a password.

After loading the device list, the integration automatically groups devices by their actual names and protocol types. Unrecognized devices are grouped under “Other Devices.” Devices of the same type appear in a checkbox list and can be selected consecutively without repeatedly expanding the group; groups with multiple devices include an “All” option. Initial setup and “Add or Remove Devices” use the same rules.

After installation, the integration's “Configure” menu provides:

| Option | Purpose |
| --- | --- |
| Configure LAN / cloud transport mode | Choose pure LAN, pure cloud, or the default combined mode |
| Configure separate MixPad LAN credentials | Store a separate LAN username and password digest if the MixPad account differs from the cloud account |
| Add or remove devices | Select all devices by dynamic category or adjust them individually for this config entry |
| Hide devices by name | Hide devices by name keyword or wildcard; do not create their entities |
| Update ORVIBO account password | Update cloud authentication without deleting entities or device selection |
| Sync cloud device names | Update names supplied by the integration without overwriting user-customized names |
| Clear local configuration files | Delete this integration's local door-lock media and optionally reset general options |
| Configure polling interval | Set cloud snapshot polling to 5–1440 minutes |
| Configure device online/offline notifications | Control online and offline notifications separately; specify `domain.service` |
| Configure integration update checks | Check GitHub stable releases every 6–168 hours |
| Lock user mapping | Map names by device, unlock method, and authorization number |
| Door-lock snapshot retention count | Keep the most recent 30 per lock by default; configure 1–500 |

The separate MixPad password is stored as a protocol digest, like the cloud password; plaintext is not saved. Cleanup does not delete accounts, families, device selection, lock-user mappings, entity registry entries, or Home Assistant `.storage`. The UI requires confirmation before cleanup.
After options are saved, Home Assistant reloads the config entry so transport and scheduled tasks are rebuilt immediately with the new settings.

“Hide devices by name” accepts one rule per line. Plain text matches anywhere in the device name, such as `test`; a rule containing a wildcard matches the complete device name, such as `*controller*` or `bedroom?light`. Matching is case-insensitive for English letters. Matching devices are excluded from both entity platforms and the device-selection page. Rules do not rewrite saved device IDs; a device reappears when its rule is removed.

### Device transport indicator

Each configured device with a Home Assistant platform gets a “Transport Path” diagnostic entity. It does not change the device name, business-entity names, or unique IDs. Entity states mean:

| State | Meaning |
| --- | --- |
| `LAN` | In pure LAN mode, device state or control uses MixPad |
| `Cloud` | Pure cloud mode, or a device that the capability table assigns to cloud |
| `LAN preferred, cloud fallback` | In default combined mode, prefer LAN and use cloud when needed |
| `Unavailable in current mode` | In pure LAN mode, the device has no LAN path, such as a lock, clothes dryer, or cloud-controlled floor heating |

Entity attributes also show the configured mode, LAN/cloud control capabilities, gateway connection state, and the actual `lan` or `cloud` transport used by the most recent successful control during the current Home Assistant run.

## Supported scope

Current platforms include `light`, `switch`, `cover`, `climate`, `fan`, `sensor`, `binary_sensor`, and `camera`. Main capabilities:

| Category | Implemented capabilities | Typical control path |
| --- | --- | --- |
| Lights and wall switches | On/off, brightness, color temperature | LAN preferred, cloud fallback |
| Curtains and tubular motors | Open/close, position, stop; Dream Curtain blade angle | LAN or cloud, depending on model |
| Fan-coil, floor heating, fresh air | Mode, temperature, fan speed, or preset mode | LAN or cloud, depending on model |
| Security and environmental sensors | Motion, doors/windows, smoke, gas, water leak, temperature/humidity | Read-only state |
| Smart locks | Lock/door contact, battery, events, snapshots, recordings, temporary passwords | Cloud-only |
| Smart clothes dryers | Light, sterilization, air-dry, heat-dry, raise/lower | Cloud-only |
| Camera / NVR `14/162` | Live Meari XTS channel video; diagnostics only for other protocols | Cloud authorization + P2P/relay |

See the [Device Support Matrix](docs/DEVICE_SUPPORT.md) for verified models, `deviceType`, limitations, and transport markings. Unlisted models may be recognized and displayed, but their control commands are not inferred. This safety constraint prevents sending incorrect actions to unknown devices.

## Door-lock features

Each supported lock gets state, battery, event, and snapshot entities according to its actual capabilities. Event snapshots are not a live door-view video stream; the private protocol for live video is currently outside the supported scope.

The integration also provides:

- `orvibo_smart_control_lock_event` events for automations involving unlocks, doorbells, picking attempts, doors left open, and similar events;
- Signed door-lock event images, H.264 recording archives, and Home Assistant media-browser indexing;
- Temporary-password creation, listing, revocation, and expiration cleanup every 6 hours;
- A built-in door-lock overview card and a separate temporary-password management card.

`0.2.6b13` improved the overview card: it shows the main lock, door contact, and deadbolt separately, with a valid battery level at the top. Recent openings emphasize the person, inside/outside direction, method, and time; an inside opening does not display the old outside-opening person or credential. Door-view snapshots add a large preview of the newest image, horizontally scrollable history thumbnails, and keyboard navigation in the large view; failed refreshes retain existing images. Related state updates preserve text being entered and input focus. The card adapts to narrow phone columns and light/dark themes.

`0.2.6b14` fixed resource URLs reverting after upgrade and requiring users to delete and re-add JavaScript resources. After Home Assistant starts, it checks the URL again and updates it in place, preserving the resource entry and card configuration. It also corrected snapshot parsing parameters and media references, using the integration's authenticated media source to read existing images and recordings without configuring `media_dirs` or moving saved files.
See the [0.2.6b14 release notes](docs/releases/0.2.6b14.md).

`0.2.6b15` adds multifunction relay curtain controllers (`deviceType=42`, `subDeviceType=-2`) as open/close/stop covers. The controller reports no position, so the cover has an assumed state; open and close follow the controller's learned keys in the ORVIBO app. Earlier "recognized; not yet supported" roller blinds on this controller become controllable after the update.
Local regression passed; open, close, and stop direction on a real controller still need device confirmation.
See the [0.2.6b15 release notes](docs/releases/0.2.6b15.md).

`0.2.6b16` fixes doubled entity names such as "Roller Blinds Roller Blinds" or "Kitchen pendant Kitchen pendant". The main entity of each light, cover, switch, climate, and fan device now shows only the device name; feature entities such as "Battery" or "Drying rack" keep their names, and the "Transport path" and "Camera SDK hint" diagnostic sensors show their own names. Entity IDs and unique IDs do not change.
Update to **v0.2.6b16** in HACS and **restart Home Assistant**. Names you changed yourself in Home Assistant are kept.
See the [0.2.6b16 release notes](docs/releases/0.2.6b16.md).

`0.2.6b17` fixes the MixPad LAN connection for accounts whose gateway rejects the login email or phone number (LAN login `status=9`). The integration now retries with the account's cloud user ID and keeps using whichever identity the gateway accepts, so state pushes and control go over LAN instead of falling back to the cloud. Separate LAN credentials, when configured, are used as before.
Update to **v0.2.6b17** in HACS and **restart Home Assistant**.
See the [0.2.6b17 release notes](docs/releases/0.2.6b17.md).

`0.2.6b18` stops the integration from undoing your area changes. ORVIBO rooms are still mapped to Home Assistant areas, but only for devices that have no area yet; devices you moved, and areas you renamed or merged, are left alone instead of being recreated from the ORVIBO room names on every restart or reload. Area mappings set in the integration options still apply.
Update to **v0.2.6b18** in HACS and **restart Home Assistant**.
See the [release notes](docs/releases/0.2.6b18.md).

`0.2.6b12` added the `battery_power` field for older locks with five dry-cell batteries, covering `deviceType=300`, `subDeviceType=400`. The user's inventory and six live-push replays all reported 60%. The integration continues to support flat and nested fields for dry cells and lithium-battery managers, preferring valid manager data. It shows only sources with valid readings; entries without a value are hidden and restored when a valid reading arrives, preserving user-hidden settings.
Partial pushes without battery data do not clear the latest valid reading; 0% is valid. The main lock, door contact, and deadbolt are parsed independently, so “not deadbolted” does not overwrite an engaged main lock. Restart Home Assistant after updating; the actual entity display still needs device confirmation.

Whole-home diagnostics now retain all devices, fixing truncation of locks when there are more than 50. Lock diagnostics also include inventory and latest-state properties, with redaction retained. See [Legacy Lock Battery Compatibility](docs/releases/0.2.6b12.md).

Since `0.2.6b10`, opening direction follows four credential categories: password (including temporary password), fingerprint, key, and card count as opening from outside. Other unlock methods and door-contact openings not matched to one of these four credential types count as opening from inside; an inside opening does not inherit the previous outside person's identity. This is the integration's classification rule; an inside opening with no confirmed identity displays “Person unknown.”
In the “Lock User Mapping” integration option, use `deviceID/method/userID=name`, for example `deviceID/fingerprint/7=John Doe`; `deviceID/7=John Doe` and `7=John Doe` also work.

Door-view snapshot retention defaults to **30 images** per lock; set **1–500** in the “Door Lock Snapshot Retention Count” integration option. Failed downloads are retried; images captured in the same second are saved separately; restart restores the latest image and a delayed old image does not overwrite a new one.
The overview card displays 30 images by default; use `history_limit` to change its display count. Restart Home Assistant after updating; if the card still shows old content, force-refresh the browser. See [Door Lock Direction, Unlocker Identity, and Snapshots](docs/lock-opening-and-snapshots.md).

To manage temporary passwords only, add this Lovelace card:

```yaml
type: custom:orvibo-smart-control-temp-password-card
device_id: w-example-door-lock-id
```

To view lock state, events, and temporary passwords together, use the overview card:

```yaml
type: custom:orvibo-smart-control-door-lock-card
device_id: w-example-door-lock-id
```

Service fields, responses, event payloads, and automation examples are documented in the [Services and Events Reference](docs/SERVICES_AND_EVENTS.md).

## Troubleshooting

| Symptom | Check first |
| --- | --- |
| Login succeeds but no devices appear | Account cloud region, selected family, and device-filter options; then run `refresh_devices` |
| Control always uses cloud | Whether mode is “Pure cloud,” whether the device is in the LAN capability table, and whether gateway authentication completed |
| Gateway cannot connect | Whether HA and MixPad are on mutually reachable networks, and whether VLAN/firewall blocks UDP discovery or TCP `8088` |
| State updates are slow after LAN control fails | Whether the cloud long connection is online; a LAN failure retries through cloud once only |
| Locks/clothes dryers unavailable in pure LAN | Expected limitation; use default combined mode so Wi-Fi devices without LAN support use cloud |
| Separate MixPad credentials still fail to log in | Confirm LAN username/password belong to that MixPad; leaving the password empty preserves only a previously configured digest |
| Lock images or recordings are missing | Check cloud credentials and HA `media` directory permissions; MP4 remuxing also needs working ffmpeg |
| Duplicate entities appear | Check whether another ORVIBO integration is still loaded and use the migration guide to identify entity ownership |

When submitting an issue, include the Home Assistant and integration versions, public device model, connection method, relevant logs, and reproduction steps. Do not include accounts, password digests, tokens, family/device identifiers, IPs, MACs, signed media URLs, or unredacted diagnostics. See the [Security Policy](SECURITY.md) for complete rules.

## Upgrades and migration

This project uses a new Home Assistant integration domain, so config entries from other ORVIBO integrations do not transfer automatically. First validate the new integration in parallel, then handle old entities and history. See the [Migration Guide](docs/MIGRATION.md) for operation order, rollback, and the distinction from internal config-version migration.

## Development and validation

Code is organized by runtime responsibility:

```text
custom_components/orvibo_smart_control/
  capabilities.py       Device categories, platforms, and available transports
  device_selection.py   Dynamic name/type grouping and selection merging in config flow
  coordinator.py        Home Assistant lifecycle and dual-channel orchestration
  lan/                  Gateway discovery, authentication, TCP sessions, and control adapter
  https_client.py       Cloud REST login and device snapshots
  ssl_client.py         Cloud TLS live pushes and control
  parsers/              Shared LAN/SSL state normalization
  state_store.py        Field-level source priority and deduplication
  control_router.py     Transport-independent device-action routing
  control_executor.py   Channel selection, execution, and one cloud fallback
  runtime_options.py    Online/offline notifications and optional update checks
  lock_* / temp_*       Lock events, media, and temporary passwords
  www/                  Built-in door-lock cards
```

The project uses the standard-library `unittest` to run tests that do not require a full Home Assistant installation. CI runs syntax, identity, HACS, and hassfest checks. Read the [Contribution Guide](CONTRIBUTING.md) before contributing.

## Documentation index

| Document | Audience | Contents |
| --- | --- | --- |
| [Device Support Matrix](docs/DEVICE_SUPPORT.md) | Users and device contributors | Verified models, transports, and limitations |
| [Services and Events Reference](docs/SERVICES_AND_EVENTS.md) | Automation authors | Service fields, responses, and event payloads |
| [Migration Guide](docs/MIGRATION.md) | Users of existing integrations | Separate-domain migration, deduplication, and rollback |
| [Runtime Architecture](FUSION_DESIGN.md) | Maintainers | Data flow, routing, state merging, and ADRs |
| [Contribution Guide](CONTRIBUTING.md) | Contributors | Development workflow, tests, real-device evidence, and PR requirements |
| [Security Policy](SECURITY.md) | Everyone | Vulnerability reports, secret handling, and media risks |
| [Changelog](CHANGELOG.md) | Everyone | Version history and unreleased changes |
| [MIT License](LICENSE) | Everyone | Use and redistribution terms |

## License and acknowledgements

The project is released under the [MIT License](LICENSE). Protocol research and early device support benefited from ORVIBO community contributors and real-device testers.

ORVIBO, HomeMate, and Smart Home 365 are trademarks of their respective owners. This is community-maintained software and is not officially supported by the vendor.
