# Changelog

## [Unreleased]

## [0.2.6b17] - 2026-10-18

### Fixed

- Connect to MixPad gateways over LAN when the gateway rejects the account
  email at login (`status=9`): retry with the cloud user ID and use the accepted
  identity for LAN control. Previously such setups silently ran cloud-only.

## [0.2.6b16] - 2026-10-18

### Fixed

- Stop doubling the device name in entity friendly names (for example
  "Roller Blinds Roller Blinds"). Primary light, cover, switch, climate, and fan
  entities now use only the device name; feature entities keep their names.
- Show the translated "Transport path" and "Camera SDK hint" names for the
  diagnostic sensors instead of the bare device name. Unique IDs are unchanged.

## [0.2.6b15] - 2026-10-18

### Added

- Support multifunction relay curtain controllers (`deviceType=42`, `subDeviceType=-2`)
  as open/close/stop covers. Open and close follow the device's learned app keys.

### Fixed

- Use the running integration's device-discovery fallbacks during initial setup,
  including the alternate cloud region when the first region has no devices.
- Align card assertions with the English labels and validate fork repository metadata.

### Changed

- Translate UI labels, entity names, notifications, service descriptions, cards,
  product catalog descriptions, documentation, comments, logs, and developer tools into English.
- Keep vendor model identities, protocol commands, service names, and entity unique IDs unchanged.
- Preserve and document only the Chinese inputs required for vendor-name matching,
  incoming notification classification, and protocol-fixture coverage.
- Add an English-only CI check with exact, explained compatibility exceptions.

## [0.2.6b14] - 2026-10-16

### Fixed

- Fixed JavaScript resource URLs reverting to an older version after delayed loading during startup, which previously required users to remove and re-add the resource. After startup, the integration checks and updates the URL and global module in place, preserves the resource ID and card configuration, and retries if initial static registration fails.
- Fixed door-lock snapshots failing to load: media parsing now uses Home Assistant's required `media_content_id`, and images and recordings share the integration's authenticated media source. Existing archives under `config/media` remain readable without relying on the user's `media_dirs` setting.
- Fixed the `fetch_video` service and archived recording cache returning an old media reference; they now use the same media-source path as history queries.

### Verification

- Full Python 3.12 offline suite passed: 787 tests, 2 skipped. Coverage includes startup resource rollback and retries, strict media parsing parameters, existing snapshot directories, archive path boundaries, and cached recording references.
- Eight simulated Home Assistant browser-check groups passed with no browser errors. Call formats were checked against HA media-source and signed-URL interface source.

### Limitations

- Update to `v0.2.6b14` in HACS, restart Home Assistant, and force-refresh the page. Existing JavaScript resources, card configuration, and local snapshots can remain; 30 snapshots per lock are kept by default, configurable to 1–500.
- Local startup-race reproduction and simulated validation passed. Resource updates, authenticated media reads, and new cloud snapshots after an actual HA upgrade still need device confirmation.

## [0.2.6b13] - 2026-10-16

### Changed

- Improved the door-lock overview card: shows the main lock, door contact, deadbolt, and valid battery level together; highlights the most recent person, inside/outside direction, unlock method, and time. Unlocked state uses a warning color, unknown state is shown separately, and inside openings do not show the previous outside person's identity or credential.
- Added a preview of the newest door-view snapshot and horizontally scrollable history thumbnails. Supports keyboard use, previous/next in large view, Escape to close and restore focus; adapts to narrow phone cards, light/dark themes, and reduced-motion settings.

### Fixed

- Resolve up to four snapshot URLs concurrently while preserving order. Failed refreshes retain displayed images; a failed single-image lookup keeps that image's existing URL and shows a retry prompt. Results from old snapshot requests are discarded after changing config.
- Unrelated Home Assistant state updates no longer rebuild the door-lock card. Relevant refreshes preserve form drafts, input focus, cursor, and history-image scroll position. Temporary-password and authorization sections support keyboard interaction and indicate their expanded state.

### Verification

- Full Python 3.12 offline suite passed: 775 tests, 2 skipped. New regressions cover valid battery levels, clearing identity for inside openings, concurrent image ordering, retaining images on failure, discarding stale requests, and unrelated state updates.
- Eight simulated Home Assistant browser-check groups passed with no browser errors, covering 320–1440px layouts, 44px action targets, input/focus retention, keyboard control in large view, image-failure recovery, empty gallery, and the standalone password card.

### Limitations

- Update to `v0.2.6b13` in HACS, restart Home Assistant, and force-refresh the browser to load the new card script; existing card configuration can remain.
- Browser validation used simulated state and images. The actual HA theme, phone display, cloud snapshots, and temporary-password operation still need device confirmation.

## [0.2.6b12] - 2026-10-16

### Fixed

- Fixed unknown dry-cell battery levels on legacy locks reporting only `properties.battery_power`, covering five-battery locks with `deviceType=300`, `subDeviceType=400`. The value comes from the actual percentage reported by the device; it is not inferred from the `value4` event code.
- Valid battery-manager data and an explicit not-installed marker still take precedence over legacy fields. 0% is valid, while missing/invalid partial updates preserve the latest reading. Lithium-battery entries without valid data remain hidden; existing entity IDs and user-hidden settings remain unchanged.
- Fixed whole-home diagnostics omitting devices after the 50th. Lock diagnostics now include raw inventory and latest-state properties and their numeric source, with per-device size limits and continued redaction of secrets and identifiers.

### Verification

- Replayed the user's lock inventory and six live pushes: dry-cell battery was 60% in each; door closed, main lock engaged, deadbolt not engaged, no lithium reading. The user's original diagnostic file was not committed.
- Full Python 3.12 offline suite passed: 769 tests, 2 skipped. New regressions cover the complete legacy battery path, boundary values, manager priority, entity restoration, and diagnostics/redaction for 86 devices. Independent review found no release blockers.

### Limitations

- After updating to `v0.2.6b12` in HACS, restart Home Assistant and wait for a cloud snapshot or live push. Diagnostic replay confirmed field parsing; entity display after upgrade still needs device confirmation.

## [0.2.6b11] - 2026-10-16

### Fixed

- Door-lock battery and state parsing now supports flat fields in the App property table such as `batteryManager_level`, `batteryManager1_level`, and `doorLock_lockState`, while continuing to support nested live-push fields. Fixes missed data that caused unknown battery levels or incorrect lock state.
- Parses the main lock and deadbolt separately: legacy `handle` represents the main lock and `reverse_lock` the independent deadbolt. “Not deadbolted” no longer overwrites an engaged main lock.
- Partial updates with missing or invalid battery levels preserve the latest valid reading; an explicit not-installed marker still clears that source, and 0% is valid for an installed battery. A partial cloud snapshot with missing lock state preserves the latest state.
- Automatically hides dry-cell or lithium battery entities without a valid reading and restores them when a valid reading arrives, preserving existing entity IDs and user-hidden settings.

### Verification

- Full Python 3.12 offline suite passed: 755 tests, 2 skipped. Coverage includes property-table initialization and periodic updates, a 60% dry-cell sample, main-lock/deadbolt combinations, partial battery updates, invalid values, and entity hide/restore lifecycle.

### Limitations

- This change was validated using static reverse engineering of HomeMate 5.2.6.307 and synthetic protocol regressions. Actual battery, door-contact, main-lock, and deadbolt display still need confirmation on the user's device.
- After updating, restart Home Assistant and wait for a valid cloud snapshot or live push. A closed door alone does not mean the main lock is engaged.

## [0.2.6b10] - 2026-10-16

### Changed

- Determine opening direction using four credential categories: password (including temporary password), fingerprint, key, and card mean outside; all other unlock methods and door-contact openings unmatched to these credentials mean inside. Inside openings do not reuse an outside user.

### Verification

- Full Python 3.12 offline suite passed: 747 tests, 2 skipped. Coverage includes the four outside credentials and temporary/duress credentials, inside openings by other methods or door contact without a credential, clearing identity for inside openings, duplicate/expired events, and three-line name mappings.

### Limitations

- Inside-opening classification is the direction-inference strategy requested by the user: face recognition, other/unknown methods, and door-contact openings unmatched to the four credentials are treated as inside. This does not mean firmware explicitly confirmed the direction; the person is shown as unknown.
- Real lock event timing, name authorization numbers, and snapshot behavior still need device validation.

## [0.2.6b9] - 2026-10-15

### Added

- Door-lock events and overview card now show inside/outside direction and unlocker identity; support old and new events, administrator number 0, and name mappings by device, credential method, and authorization number.
- Added “Door Lock Snapshot Retention Count”; keeps the latest 30 images per lock by default, configurable to 1–500. The card displays 30 by default and supports `history_limit`.
- `list_events` can filter images or recordings before applying the limit, so recordings do not take up the snapshot display count.

### Fixed

- Credential unlocks using password, fingerprint, key, or card are classified as outside; explicit inside openings never inherit the previous outside person's identity. Duplicate, expired, and out-of-order old events no longer corrupt current attribution, and one unlock is linked to only one opening.
- Snapshot downloads are attempted immediately and retried with a new signature on failure; pruning occurs only after atomic save succeeds. Different images from the same second are saved separately; a late old image is archived without replacing the latest image.
- The latest local snapshots are restored after restart, and camera updates refresh the card. Automatic 7-day recording cleanup no longer removes retained images; concurrent save, cleanup, and unload share a controlled lifecycle.

### Verification

- Full Python 3.12 offline suite passed: 744 tests, 2 skipped. Coverage includes opening attribution, administrator 0, name scoping, snapshot retry/concurrency/retention/restoration, and card interaction regressions.
- Independent pre-release review found no blockers.

### Limitations

- Implemented from static reverse-engineering evidence for HomeMate 5.2.6.307; not yet validated on a real lock. If firmware reports only the door contact without direction or user number, direction and person remain unknown.
- Configure “Lock User Mapping” for unlocker names; service-based temporary renaming lasts only for the current run, while persistent mappings belong in integration options. Door-view snapshots depend on cloud events and downloadable objects; live door-view video is not provided.

## [0.2.6b8] - 2026-10-15

### Added

- Added a separate “SD Card Playback” entity for selected, matched Meari XTS/p2p=2 IPC devices such as the Jumu 2K Smart Camera S1. Supports month/day SD/TF recording search, playback by time, and stop.
- The video worker accepts channel 0 storage-card search/playback for supported IPCs. Existing NVR entity unique IDs, channels, and playback commands remain unchanged; unverified device types are not enabled.
- The “ORVIBO Recording Playback” card lists both storage-card and hard-drive entities while retaining its custom type, compact layout, and service names; adds generic playback-entity associations and a storage-source attribute.

### Verification

- Added regressions for S1 entity creation, SD channel validation, month/day and start/stop bytes, simulated tunnel recording streams, and unload cleanup. Card tests cover switching from hard-drive to storage-card search, playback, and stop.
- Fixed playback tunnel tests depending on initialization performed by another test class; tests no longer depend on execution order.

### Limitations

- Implemented from static protocol analysis of the official App and offline simulation; actual S1 storage-card search and playback still need device validation. Playback in the official App proves only that recordings exist on the card, not that HA playback works.
- Supports ordinary time-based playback only; no cloud recordings, `record_id` mode, audio, pause, or variable speed. Initial connection may take about a minute.

## [0.2.6b7] - 2026-10-15

### Changed

- Playback card now uses a compact layout and automatic height, with channel/date side by side and month search/specified time under “More Options.”
- Recording clips appear in a scrollable list capped at 120px; clips and additional options collapse after playback starts. The player is above the list, maintains 16:9, and has a maximum width.
- Removed reserved height for empty-state hints and overly large default grid rows. Narrow screens use one column to avoid horizontal overflow; clip buttons retain accessible playback descriptions.
- Compared a real headless browser at 320/430/820px with 256 clips. Idle, result, and playback states are all shorter; search/play/stop interaction regressions passed.

### Limitations

- Browser-layout tests use simulated HA services and player area; they do not replace video validation in the user's HA or real hard-drive recording tests.

## [0.2.6b6] - 2026-10-15

### Fixed

- Completed automatic Lovelace module-resource registration for embedded cards and updated existing old resource URLs, avoiding reliance only on a global extra script while retaining YAML resource configuration.
- Refreshes resource cache using the script-content hash. Failure to register one frontend card no longer skips the other; retries after HA startup if the dashboard is not ready.
- Recording card now allows repeated loads on one page, avoiding top-level identifier conflicts when old and manually added resource URLs coexist.
- Added tests for static HTTP routes, JavaScript MIME, lazy resource collections, idempotent registration, and failure isolation. A standalone headless Edge test verified HTTP module loading, component registration, repeated imports, and clip display after search.

### Limitations

- The user's HA environment was not connected; this change fixes only the frontend resource entry point. Real-device hard-drive search and playback still await user feedback.

## [0.2.6b5] - 2026-10-15

### Added

- Added the ORVIBO NVR hard-drive recording card, separate playback camera entity, and bounded month/day clip search. Playback positions use the NVR calendar and do not automatically restart from the original time after ending.
- Implemented the App's hard-drive search and ordinary time-based playback protocol, matching tunnel replies by sequence and recognizing recording media/end markers. Playback does not reuse the live stream.
- Added `search_hdd_recordings`, `start_hdd_playback`, and `stop_hdd_playback` services and redacted connection diagnostics.
- Cleans up failed live prepared connections and applies bounded backoff warmup after live-video disconnects so HA's slow retry can reuse a connection being established.

### Verification

- Full Python 3.12 offline suite passed, 686 tests, including real FFmpeg/PyAV synthetic streams, P2P protocol, playback entity/service lifecycle, and card DOM interactions.
- The user confirmed that real NVR channel 1 is viewable; channel 3 loads slowly but recovers after waiting.

### Limitations

- Hard-drive search and recording playback have not been validated on a real device. `playback_selected` means only that a time was set; receipt of playback video still needs device testing. No audio, pause, or variable speed.
- Implements ordinary time-selected playback only; `record_id` mode is not implemented. Uses the NVR calendar without converting to the HA time zone. Reload the integration when new recording channels appear.

## [0.2.6b4] - 2026-10-15

### Added

- Created live camera entities for selected, precisely matched online channels on Meari XTS/p2p=2 IPCs and NVRs. Refreshes authorization and channels on each start using stable vendor IDs, so inventory order changes cannot switch to the wrong device.
- Continuous protocol worker emits Annex-B through a bounded J/V pipe; FFmpeg converts it to H.264 MPEG-TS, then HA Stream provides frontend playback. Thumbnails reuse HA's decoded keyframe, so HAOS needs no separate video service.
- Prepared connections bypass HA's shorter video-source startup deadline; unused preparations expire. Protocol/transcoding processes are reclaimed on disconnect, no frames, timeout, repeated cancellation, platform removal, and HA shutdown.
- Continuous streaming adds TURN renewal and encrypted I/P-frame regressions; CI installs FFmpeg/PyAV for actual video validation.

### Verification

- The user's real NVR channel 1 delivered HEVC parameter sets and a 153,474-byte keyframe over 144 packets; this does not establish decoding or continuous playback.
- Full Python 3.12 offline suite passed, 647 tests with 55 new tests, including real HEVC → H.264 MPEG-TS → decoding and PyAV decoding of continuous 10-fps video.

### Limitations

- Continuous video on a real device, channel 3, simultaneous multi-channel playback, and timing under network jitter still need user validation. No audio; hard-drive history search/playback/seeking are not available. Supports default hostKey authentication only.
- New devices/channels are discovered when the platform loads; reload after cloud channel changes. Connection requires cloud authorization. GitHub publishes `bN` versions as ordinary Releases / Latest.

## [0.2.6b3] - 2026-10-15

### Added

- Added `probe_video_stream`: obtains a fresh session and inventory, then actually attempts MsgSvr/TURN/ICE/KCP/VVP through the encoded first frame for a specified channel. Returns fixed stages and bounded media statistics without saving video.
- Allows one probe per config entry. Stops and reclaims the subprocess on completion, timeout, cancellation, unload, and HA shutdown, including blocked DNS work.
- Reuses the pinned MIT protocol implementation with attribution preserved; corrected authentication, final VVP header, and NVR channel passing based on native App evidence; supports HA dependency directories.

### Verification

- The user confirmed that b2 cloud channel lookup succeeded: 8 NVR channels, with channel 1 and 3 state=1, p2p=2. This is a cloud snapshot, not evidence of media playback.
- Full Python 3.12 offline suite passed, 592 tests, including 49 new protocol vectors, simulated signaling through first frame, slow TCP, unrelated STUN packets, HEVC IRAP, empty-NAL filtering, actual subprocess timeout, and repeated-cancellation cleanup.

### Limitations

- Encoded first-frame detection checks only basic structure of required parameter sets and key NALs; it has not been validated by a decoder or real-device media. Live playback output and hard-drive history search/playback/seeking are not implemented yet.
- The Android client version suffix and reference discovery-protocol version still need real-environment validation. Only default hostKey authentication is tried; separate video-password combinations are not guessed.

## [0.2.6b2] - 2026-10-15

### Added

- Added the `inspect_video_channels` action: after obtaining the ORVIBO external session and vendor device list, queries NVR channel snapshots through the App's HTTPS batch API and returns channel number, raw state/type, and bounded capability codes.
- Distinguishes maximum channel count, returned channel count, missing state, invalid rows, and output truncation. Does not return account, token, SN, device name, key, address, or raw response.

### Fixed

- Extracted vendor signing into a generic builder; NVR batch GET re-signs the path and `snIdentifier`, preserving the verified device-inventory request format.
- Retained `bN` diagnostic versions and published them as ordinary GitHub Releases / Latest. Fixed existing versions' Pre-release flags and installation instructions without moving existing tags or replacing uploaded packages.

### Limitations

- Channel data comes from vendor cloud snapshots and may be missing or stale. Results of this batch API have not yet been verified on a real device. Live streaming and NVR hard-drive clip search, playback, and seeking are not implemented.

### Verification

- Full Python 3.12 offline unit suite passed, 543 tests, including 22 new NVR channel request/parsing, independent signature-vector, redaction, and full action-chain regressions. Real-channel and media playback validation has not been done.

## [0.2.6b1] - 2026-10-15

### Added

- Added `inspect_video_devices`, which obtains an ORVIBO external session, signs the request body and headers as the App does, and queries the Meari device list at the HTTPS API provided by the session.
- Returns fixed category counts, connection-parameter presence, and bounded raw capability codes. Filters accounts, tokens, device identifiers, keys, addresses, and raw responses. Bounds response size, request duration, and output count; redirects are not followed.

### Limitations

- Device-list diagnostics still need validation with a real account. NVR channel-parameter lookup, live video, and hard-drive history playback are not implemented. Capability codes do not verify video support.

### Verification

- Full Python 3.11 and 3.12 offline unit suites passed, 520 tests each, including 21 vendor device-request, independent signature-vector, response-redaction, and error-boundary tests.

## [0.2.6b0] - 2026-10-14

### Added

- Added `inspect_video_session` to check Meari external authorization over the existing ORVIBO cloud session. Returns field presence and request stage; omits account, token, API address, and raw authorization response.
- Added timeout, concurrency isolation, cancellation cleanup, and response-correlation checks for NVR session requests, with HACS beta installation and redacted diagnostic instructions.
- Release workflow supports `bN` versions, packages the tagged commit, and retains the GitHub prerelease marker.

### Limitations

- This version is for diagnostics only and does not implement live video or NVR hard-drive history playback. Vendor session and video protocols have not been validated with a real account/device.

### Verification

- Full offline unit suite passed, 499 tests, including NVR-session and beta-release recovery regressions.

## [0.2.5] - 2026-10-14

### Fixed

- Unified array/dictionary readtable inventory and homepage fallback parsing, retaining room, state-value, and control-location fields while filtering deleted statuses and empty parent switches. Gateway IP extraction now handles string device types and malformed rows.
- Added parsing for the separate `devicePropertyStatus` table based on APK `5.2.6.307`, associating properties by business device ID and property. Supports compound JSON, numeric timestamp comparison, and deletion markers within a snapshot.
- Partial LAN/SSL pushes update source protection only for fields assigned in the current update, so a switch-only push does not block cloud brightness/color-temperature data. Missing switch, ordinary state, and dryer fields retain their latest values.
- Removed duplicate homepage method definitions from the HTTPS client, preventing later definitions from overriding inventory parsing.

### Verification

- Full Python 3.11 offline unit suite passed, 477 tests, including 16 new loading/state regressions. Added reverse-engineering basis documentation. Devices and firmware were not tested on real hardware in this round.

## [0.2.4] - 2026-10-14

### Added

- Cameras with `deviceType=14` and NVRs with `deviceType=162` can now be selected in the “Cameras” group and expose Transport Path and vendor SDK recognition diagnostic sensors. Inventory information remains available offline; SDK hints update after cloud refresh.
- Displays Danale, Meari, EZVIZ, or unknown hints based on the camera supplementary-table type, with English/Chinese translations and diagnostic export. Supports read-only recognition only; no live video or SDK control.

### Fixed

- Camera supplementary data is joined by hardware UID to avoid confusion with business device ID, device type, or product type. The table does not create extra devices; camera classification takes precedence over name keywords, and deleted devices do not reappear from dictionary-format inventory.
- Discards SDK credentials from camera supplementary data. Diagnostics now redact `tokenSecret` and fingerprint the `extAddr` identifier.

### Verification

- Full Python 3.12 unit suite passed, 461 tests.
- Python compilation, door-lock card JavaScript syntax, and Git patch-format checks passed. Cameras/NVRs have not yet been verified on real devices.

## [0.2.3] - 2026-10-10

### Fixed

- Fixed lights displaying −1% brightness: ignores negative/malformed values and retains the last valid reading. Cloud light snapshots reuse live-state parsing so old fields do not overwrite correct property brightness. Added validity checks for entity output and brightness reused when turning on/changing color temperature.

### Verification

- Full unit suite passed, 443 tests.
- Covers invalid brightness, cloud refresh, partial state pushes, entity percentage display, and control-command regressions.
- Python compilation, door-lock card JavaScript syntax, and Git patch-format checks passed.

## [0.2.2] - 2026-10-10

### Fixed

- Fixed lights being incorrectly marked “unavailable” when state was read or a switch was controlled after a long period without live pushes. No longer infers offline from 10 minutes without a push; retains availability determined by cloud snapshots and live reports.

### Verification

- Full unit suite passed, 428 tests.
- Python compilation, door-lock card JavaScript syntax, and Git patch-format checks passed.

## [0.2.1] - 2026-10-09

### Fixed

- Unified the HACS release entry point: after each validated push to `main`, creates a missing tag from the manifest version and retries missing Releases/ZIPs. Supports annotated tags, packages the tagged commit, and makes a new Release public only after upload finishes.
- Removed duplicate declarations of Home Assistant built-in dependencies `aiohttp` and `cryptography` from the manifest, fixing hassfest requirements validation.
- Fixed cloud TLS disconnects remaining marked as connected and stopped listeners failing to log in again. Missing readers and temporary login failures now continue recovery within the retry limit.
- Fixed cloud commands reporting success after a send failure or missing writer. Send waits are limited to 10 seconds; failures release pending requests and close the failed connection. Commands with an unknown result are not replayed automatically.

### Verification

- Full unit suite: 409 tests, 1 skipped.
- Release-workflow regressions: 18 passed, covering tag creation, retry after failure, annotated tags, and ZIP upload recovery.
- Workflow YAML, Python compilation, JavaScript syntax, and Git patch-format checks passed.

## [0.2.0] - 2026-08-24

### Fixed

- Fixed light strips and other active-low dimmable lights incorrectly showing as on after reload or live-state push while off. Initialization and cloud/LAN/SSL state updates now consistently use the correct switch polarity.

### Verification

- Full unit suite: 382 tests passed, 1 skipped.
- Python compilation and Git patch-format checks passed.

## [0.1.10] - 2026-08-24

### Fixed

- Fixed some reverse-protocol dimmable lights incorrectly showing as on after reloading the integration while off. Device initialization now retains and uses the subtype, so the off state restores correctly.

### Verification

- Full unit suite: 380 tests passed, 1 skipped.
- Python compilation and Git patch-format checks passed.

## [0.1.9] - 2026-08-19

### Fixed

- Fixed dry-cell/lithium battery, lock-state, and unlock-event sensors being incorrectly shown as unavailable. These entities now display the latest data whenever the coordinator has lock state, even if the device list has no reliable online flag.

### Verification

- Full unit suite: 379 tests passed, 1 skipped.
- Door-lock card JavaScript syntax and Git patch-format checks passed.

## [0.1.8] - 2026-08-19

### Added

- Door-lock event snapshots are now saved automatically to the Home Assistant media directory. The lock card adds snapshot history, refresh, configurable `history_limit`, and clickable thumbnails for a large view.

### Changed

- Door-lock card shows actual lock state and dry-cell or lithium battery level according to the installed battery type.
- P20 `deviceType=107` devices now create lock-state, unlock-event, and battery sensors.
- Removed the version text at the bottom of the door-lock card to reduce visual clutter.

### Fixed

- Door-lock event snapshots continue to be saved to the history directory even when the camera entity is not loaded.

### Verification

- Full unit suite: 378 tests passed, 1 skipped.
- Python compilation, door-lock card JavaScript syntax, and Git patch-format checks passed.

## [0.1.7] - 2026-08-19

### Added

- Added `custom:orvibo-smart-control-temp-password-card` for independently creating, viewing, and revoking temporary door-lock passwords, with copy, loading, error, and revocation-confirmation states.

### Fixed

- Temporary-password authorization lists no longer rely on the server returning plaintext passwords; authorization names and types remain after list refresh.
- Door-lock card forms no longer lose unsubmitted content when Home Assistant state refreshes.

### Verification

- Full unit suite: 376 tests passed, 1 skipped.
- Door-lock card JavaScript syntax and custom-card registration smoke tests passed.

## [0.1.6] - 2026-08-14

### Fixed

- Doorbell live pushes now support the newer `doorbell_ring` / `picture_url` packet, correctly updating Home Assistant for ringing, answering, and hanging up while retaining support for older doorbell packets.
- Cloud live events retain the device-reported time, so doorbell history no longer displays incorrect times when the timestamp was lost during SSL forwarding.

### Verification

- Full unit suite passed, 388 tests.
- Ruff fatal-error checks and Git patch-format checks passed.

## [0.1.5] - 2026-08-13

### Fixed

- P20 locks missing `deviceType/classId` in some cloud inventories can still be recognized by official model and selected in the config flow; read-only door-contact, lock-state, battery, and unlock-event entities can be created.

### Verification

- Door-lock classification, config flow, state parsing, and inventory tests: 112 passed.

## [0.1.4] - 2026-08-13

### Added

- The initial login flow can configure devices to ignore by name and separate MixPad LAN credentials; the separate password is stored only as a protocol digest.

### Fixed

- Name hiding and device selection now synchronize cleanup of Home Assistant entity and device registry records, keeping the registry consistent with the current selection. Entities can be recreated after selecting the device again.

### Verification

- Initial setup, name filtering, and registry synchronization unit tests: 25 passed.
- Python syntax, JSON format, and version-consistency checks passed.

## [0.1.3] - 2026-08-12

### Fixed

- Added a P20 lock profile supporting `deviceType=107`, `deviceType=522` without a subtype, and `subDeviceType=462/463`, exposing door-contact, lock-state, battery, and media entities in Home Assistant.
- P20 remains on the cloud read-only device channel; door-contact switch state can update live from cloud pushes.

### Verification

- Full unit suite passed, 375 tests.
- Python syntax and Ruff fatal-error checks passed.

## [0.1.2] - 2026-08-11

### Changed

- Device selection now uses a checkbox list, allowing multiple devices of the same type to be selected consecutively without reopening the list after each one. The “All” option remains available for groups with multiple devices.

### Verification

- Full unit suite passed, 373 tests.
- JSON, Python syntax, door-lock card JavaScript syntax, and version-format checks passed.

## [0.1.1] - 2026-08-11

### Added

- Devices can be hidden by name keyword or wildcard. Matching devices do not get entities and do not appear on the device-selection page. They reappear when the rule is removed; saved device selection is not permanently deleted.

### Changed

- Device categories now use one expandable list. Groups with multiple devices have an “All” option; a single device can be checked directly.
- Unrecognized device types are grouped under “Other Devices” rather than showing the raw English type name as the category heading.

### Verification

- Full unit suite passed, 372 tests.
- JSON, Python syntax, and version-format checks passed.

## [0.1.0] - 2026-08-10

This is the first independent release of ORVIBO Smart Control. It uses a new Home Assistant integration domain and repository identity and does not promise shared config or entities with other ORVIBO custom integrations.

### Added

- MixPad gateway LAN discovery, authentication, TCP sessions, live state pushes, and local control.
- ORVIBO cloud REST and TLS long connection as fallback when LAN is unsupported, the gateway is unreachable, or control fails.
- Three transport modes: `LAN + cloud` (default, LAN preferred), `Pure LAN`, and `Pure cloud`.
- Optional separate MixPad LAN username and password digest for households with different gateway and cloud accounts.
- General options menu for device selection, account/password updates, cloud name sync, local media cleanup, polling interval, device online/offline notifications, and stable-version update checks.
- Initial setup and later device changes dynamically group devices by actual name and type; select all in a group or expand and select individually, with single-instance types kept separate.
- A “Transport Path” diagnostic entity for each configured device, showing LAN, cloud, default fallback policy, gateway status, and the path used for the latest successful control, without changing existing device/entity names.
- Field-level state merging: `LAN > SSL > CLOUD > OPTIMISTIC > INITIAL`, with short-term protection against out-of-order snapshots.
- Device classification and Home Assistant entities for lights, switches, curtains, HVAC, fresh air, environmental sensors, locks, and clothes dryers.
- Registration protection for unknown or unverified devices; no speculative control commands based on similar fields.
- Door-lock events, snapshots, recording archives, media-browser references, temporary passwords, and built-in Lovelace lock card.
- Services for `refresh_devices`, lock-user mappings, media history, and temporary authorization management.
- Independent brand assets, HACS metadata, and CI validation workflow.
- Separate device support matrix, services/events reference, migration guide, runtime architecture, and security policy.

### Changed

- Locks `107/522` and clothes dryers `52` use cloud-only policy; LAN does not take over lock state, events, media, or temporary passwords.
- LAN control failure retries through cloud only once, with LAN/SSL response correlation isolated to prevent concurrent controls from using the wrong channel.
- Pure LAN does not establish a cloud live connection or perform periodic cloud polling, and does not fall back when LAN is unsupported or fails; initial family/device/gateway-topology discovery still uses cloud.
- Pure cloud does not initialize MixPad LAN; default combined mode continues to route locks and clothes dryers through cloud automatically.
- Public service responses do not return absolute paths on the HA host or stored temporary passwords.
- Logs and diagnostics mask linked family/device/UID/IP identifiers; independent project documentation no longer reuses the source project's structure and positioning.

### Security

- Gateway handshake validates expected UID, session identity, and request correlation; malformed frames, wrong gateways, and out-of-range state values are rejected.
- Cloud and separate MixPad passwords are converted only to the uppercase MD5 digest required by the protocol; plaintext is not saved, and the digest is still protected like a password.
- Local cleanup operates only on `media/orvibo_smart_control/`; it does not delete Home Assistant `.storage`, entity registry, accounts, families, device selection, or lock-user mappings.
- Temporary passwords are returned only in the current response from their creation service; the event bus and list service never contain plaintext passwords.
- Door-lock media object keys reject full URLs, query strings, path traversal, and backslashes; history is cleaned on the default 7-day schedule.

### Verification

- Full unit suite passed, 364 tests.
- JSON/YAML, Python syntax, and door-lock card JavaScript syntax checks passed.
