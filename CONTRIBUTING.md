# Contributing to ORVIBO Smart Control

This project accepts contributions to device profiles, protocol fixes, Home Assistant entities, LAN reliability, door-lock features, tests, and documentation. Keep each change focused and explain its behavior with automated tests or reviewable real-device evidence.

## Identify the type of change first

| Change | Minimum evidence | Typical files |
| --- | --- | --- |
| New product model in an existing category | Official model fields, initial state, real-device regression | `device_types.py`, model catalog, device matrix, tests |
| New device category | Discovery records, all state pushes, request/response for each control | Classification, capabilities, parsers, control, platforms, tests |
| LAN connection or protocol issue | Redacted frame shape, gateway model, failure stage | `lan/`, protocol/connection tests |
| Cloud login or push issue | Cloud region, error code, redacted response shape | `https_client.py`, `ssl_client.py`, related tests |
| Door-lock event/media/authorization | Event category, object-key shape, expected public fields | `lock_*`, `temp_*`, services and security tests |
| Home Assistant platform or config issue | Entity platform, setup steps, state/service calls, reproduction steps | Platform files, coordinator, config flow, translations, tests |
| Documentation or project metadata | Relevant code facts and affected links | Docs, manifest, HACS/CI |

Do not combine a protocol refactor, whole-repository formatting, and a new model in one PR. Control for devices that can take dangerous actions must require stronger evidence than read-only recognition. If evidence is incomplete, contribute a diagnostic fixture or register the device for recognition without enabling speculative commands.

## Development environment

Python 3.11 is recommended. Most project tests load modules using lightweight stubs and do not require a full Home Assistant installation.

Use `uv` to run tests in an isolated environment consistent with current validation:

```powershell
uv run --isolated --python 3.11 `
  --with "aiohttp>=3.9,<4" `
  --with "cryptography>=41,<46" `
  --with "voluptuous>=0.13,<1" `
  python -B -m unittest discover -s tests -q
```

Alternatively, install the minimum dependencies in a dedicated virtual environment:

```bash
python -m pip install "aiohttp>=3.9,<4" "cryptography>=41,<46" "voluptuous>=0.13,<1"
python -B -m unittest discover -s tests -q
```

Create a topic branch from the remote default branch. Branch names should use a prefix such as `feat/`, `fix/`, `docs/`, or `test/`.
Do not commit real account data, audit output, IDE caches, or a Home Assistant config directory.

## Understand the call flow

Read [Runtime Architecture](FUSION_DESIGN.md) before making changes. The main paths are:

```text
REST inventory -> normalize -> classify -> capability -> HA platform
LAN/SSL push -> device match -> parser -> StateStore -> entity update
HA action -> control route -> transport selection -> LAN or SSL -> state reconciliation
cloud lock packet -> event/media/password managers -> HA event/service/media
```

When the repository contains a `.codegraph/` index, prefer `codegraph explore` or `codegraph node` to find symbols and callers. After structural changes, run:

```bash
codegraph sync .
```

Do not manually edit generated `.codegraph` content.

## Code boundaries

### Classification and platform registration

Device support has two related but distinct layers:

1. `device_types.py` produces a `DeviceProfile` from raw type, subtype, classId, status type, and model.
2. `capabilities.py` uses the profile and type to determine HA platforms, available control channels, `status_only`, and `cloud_only`.

When adding a device, also check `const.py`, `protocol.py`, and compatibility mappings for the relevant platforms. Correct classification with a missing platform mapping leaves a device “recognized but without an entity”; an overly broad mapping can incorrectly register an unknown device as controllable.

`hardware_verified` is category-level evidence. Adding a model to an existing category does not automatically prove that the new hardware has been verified. A match in the official catalog means only that the product name can be recognized.

### State parsing

Parsers are under `parsers/` and should be pure conversion functions that can be tested independently. Implementations must:

- Accept missing fields, numeric strings, and unknown extra fields;
- Leave input objects unchanged;
- Return only a `StatePatch` for fields explicitly present in the current packet, without resetting omitted fields;
- Normalize boolean semantics, ranges, and units for Home Assistant;
- Choose to reject or clamp out-of-range/malformed numbers, and lock that choice with tests;
- Reuse the same parsing semantics for LAN and SSL for a device.

Register new categories in `parsers/__init__.py`; cover normal, boundary, missing, and wrong-type values and partial updates.

### Control and transport

Device-control semantics belong in `control.py` and `control_router.py`. `control_executor.py` selects the channel, performs a single cloud fallback, and handles optimistic state. `lan/control_adapter.py` only translates normalized calls into gateway payloads.

When adding control, document:

- Whether the switch is active-low or active-high;
- Numeric ranges, units, enums, and rounding rules;
- Request and response commands and a reliable correlation key;
- Whether LAN and cloud payloads differ;
- Which optimistic state is allowed after a timeout;
- Whether the action could create a hazard, such as locks, heating, sterilization, or motors.

Control tests must assert the method name, positional/keyword arguments, and exact payload. Asserting only “returns True” does not prove that the command targeted the right device or avoided reversing an action. LAN failure tests must also assert that cloud is called only once.

### Locks, media, and services

Locks `107/522` are cloud-only, read-only devices. Ordinary entity control must not bypass the capability table to send commands to them. Temporary passwords, media, and history are handled by dedicated managers and service handlers.

Public events or service responses must not contain:

- Passwords or password digests;
- COS credentials or internal tokens beyond the complete signing details;
- Absolute paths on the Home Assistant host;
- Arbitrary unvalidated object keys or URLs;
- Device data belonging to another config entry.

When changing a public service, update `services.yaml`, the [Services and Events Reference](docs/SERVICES_AND_EVENTS.md), and service tests together. Update user-visible strings in `strings.json` and in both English and Simplified Chinese translations.

## Evidence package for a new device

### Identity and topology

Record and redact:

- Product name, exact model, firmware/hardware version;
- China or international cloud region;
- Wi-Fi, Zigbee, Bluetooth, or other connection method;
- Whether a gateway is required and its product model;
- `deviceType`, `subDeviceType`, `classId`, `statusType`, `ui.model`, `model`;
- All capabilities visible in the App.

### State samples

Collect at least the readtable record when the device first appears and the live push corresponding to each physical state change. For devices with multiple fields, provide single-field changes to prove parsing does not clear other state. Also record offline/recovery, minimum/maximum values, and units.

### Control samples

Verify forward, reverse, and boundary actions for each capability. For example, curtains need open, close, stop, and intermediate-position cases; dimmers need minimum, middle, and maximum; HVAC devices need all modes and fan speeds. A complete evidence chain is:

```text
HA intent -> selected transport -> request -> acknowledgement -> physical result -> state push
```

A successful server response without physical action and state confirmation does not count as real-device verification.

## Diagnostic tools

### Single-family probe

`tests/orvibo_probe.py` can list devices, listen for live packets, or collect door-lock events for a limited time:

```text
python tests/orvibo_probe.py <username> <password> list
python tests/orvibo_probe.py <username> <password> listen
python tests/orvibo_probe.py <username> <password> lock <family-index> <duration-seconds>
```

Automatic masking by the probe may not cover all linked identifiers, such as family ID, device ID, and UID. Keep JSONL output local and manually minimize and redact it again before submitting.

### Multi-family coverage audit

For accounts with many families, run:

```powershell
$env:ORVIBO_USERNAME = "account"
$env:ORVIBO_PASSWORD = "password"
python tools/bulk_readtable_audit.py --cloud auto --max-families 3
```

Start with a few families to confirm the region and output, then remove `--max-families`. The script writes a checkpoint per family; rerun with the same `--output-dir` to resume. Main outputs:

| File | Purpose | Commit? |
| --- | --- | --- |
| `report.json` | Summary of protocol characteristics and support status | No |
| `unsupported.csv` | Registrations, mapping mismatches, and parsing gaps | No |
| `unsupported-enriched.csv` | Adds official catalog product names | No |
| `state.json` | Local resume state | No |

Status values include `supported_verified`, `supported_unverified`, `hidden`, `recognized_only`, `platform_mismatch`, `registration_only`, and `parser_gap`. An empty family is recorded as `empty`, not as a failure.

Existing reports can be enriched offline with official names:

```bash
python tools/bulk_readtable_audit.py --enrich-existing --output-dir audit-output
```

These directories and `tools/device_catalog.json` are in `.gitignore`. Issues/PRs may include only a minimal, manually reviewed excerpt, never the entire family audit.

### Generate the public model catalog

After obtaining a new official `device_catalog`, run:

```bash
python tools/generate_known_device_catalog.py \
  tools/device_catalog.json \
  custom_components/orvibo_smart_control/known_device_catalog.json
```

Generated files should contain only public `model`, product names, and internal model identifiers. Family audits cannot override official names, and catalog matches must not automatically set the real-device verification flag.

## Testing requirements

Run tests closest to the change first, then the full suite. Common mappings:

| Change | Targeted tests |
| --- | --- |
| Device classification/capabilities | `test_device_profiles.py`, `test_capabilities.py` |
| readtable normalization | `test_protocol.py` |
| State fields | `test_state_parsers.py` or device-specific tests |
| Control semantics | `test_control.py`, `test_control_router.py` |
| Transport selection | `test_control_transport.py`, `test_control_executor.py`, `test_coordinator_transport.py` |
| General config/runtime options | `test_config_flow_reauth.py`, `test_runtime_options.py` |
| Device transport diagnostic entity | `test_transport_sensor.py`, `test_capabilities.py`, `test_control_transport.py` |
| Binary frames/LAN session | `test_binary_protocol.py`, `test_lan_packet.py`, `test_lan_gateway_connection.py` |
| ID matching/live dispatch | `test_status_dispatcher.py` |
| Lock events/media/passwords | `test_lock_manager.py`, `test_lock_media_manager.py`, `test_temp_password_manager.py` |
| Public service boundaries | `test_service_handlers.py`, `test_video_archive.py` |
| Project naming | `test_project_identity.py`, identity-check script |

Before submitting, run at least:

```bash
python -B -m unittest discover -s tests -q
python -B -m compileall -q custom_components tests tools
node --check custom_components/orvibo_smart_control/www/orvibo-smart-control-door-lock-card.js
git diff --check
```

Structural changes should also run `codegraph sync .`. CI additionally runs HACS validation and Home Assistant hassfest. Test fixtures must be minimal, stable, and irreversibly redacted.

## Documentation and versions

Update user-visible changes in the relevant places:

| Change | Documentation |
| --- | --- |
| New model or capability | `docs/DEVICE_SUPPORT.md` |
| Service, event, or card | `docs/SERVICES_AND_EVENTS.md`, `services.yaml` |
| Transport or state semantics | `FUSION_DESIGN.md`, README transport summary |
| Cross-domain or config change | `docs/MIGRATION.md` |
| Credentials, media, or network boundary | `SECURITY.md` |
| General config option or default | README config table, three config-flow translations, related architecture/security docs |
| Any user-visible change | `Unreleased` in `CHANGELOG.md` |

Do not silently change the manifest version in a normal PR or rewrite already-released changelog history. Keep project name, domain, repository owner, and card names consistent across manifest, HACS metadata, code, and docs.

On every push to `main`, `.github/workflows/hacs-release.yml` checks unit tests, HACS validation, and hassfest. Once they pass, it checks the version in `manifest.json` and creates a missing `v<version>` tag, then builds `orvibo-smart-control.zip` and publishes a GitHub Release. Publishing no longer depends on comparing versions with the previous commit, so a subsequent push of the same version can complete a missing tag, Release, or ZIP after an earlier failure.

Release versions follow the repository-root `AGENTS.md`: use temporary diagnostic versions `0.x.ybN` by default; use a stable `0.x.y` version only when the user explicitly asks for a stable release. Both are ordinary GitHub Releases / Latest and must not have `Pre-release` set, so HACS can detect updates. Existing tags retain their original commit; a missing ZIP is built from the code at the tag. A new Release is first saved as a draft and made public only after the ZIP upload succeeds. Increment the manifest version before releasing code after an existing tag. Pushing a version tag manually, running `workflow_dispatch` on `main`, and scheduled checks use the same release flow; pushes to other branches and PRs validate only and do not publish.

## Redaction checklist

Remove or replace accounts, email addresses, phone numbers, passwords and digests, tokens, cookies, session/dynamic keys, family/user/device/status IDs, UIDs, `extAddr`, MAC/IP addresses, family/room names, lock authorizations and passwords, temporary COS credentials, signed URLs, private object paths, HA tokens, absolute config paths, and backup contents.

Suggested placeholders:

```json
{
  "familyId": "REDACTED_FAMILY_A",
  "deviceId": "w-REDACTED_DEVICE_A",
  "uid": "REDACTED_UID_A",
  "extAddr": "REDACTED_EXT_ADDR_A"
}
```

Keep placeholder relationships consistent within a sample. Do not replace a real ID with a different random but plausible 32-character value.
See [SECURITY.md](SECURITY.md) for further security boundaries.

## PR completion criteria

A reviewable device or protocol PR should include:

- A short statement of the problem and expected behavior;
- Device/environment matrix and real-device results;
- Minimal code changes to classification, parsing, control, or platforms;
- Automated tests and the command used to run them;
- Minimal redacted evidence;
- Corresponding documentation and an `Unreleased` entry;
- No project identity drift, secrets, or unrelated formatting.

Use this outline for the PR description:

```markdown
## Problem and scope

## Device and environment

- Product/firmware:
- Region/connection/gateway:
- Protocol classification fields:

## Evidence

- Initial snapshot:
- State pushes:
- Control request, acknowledgement, and physical result:
- Ranges, units, and special semantics:

## Validation

- Targeted tests:
- Full tests:
- Real-device regression:

## Redaction check

- [ ] No account, credentials, password digest, or token
- [ ] No real family/device/network identifiers
- [ ] No private media URL, object key, or host path
- [ ] Nested JSON, images, and videos manually checked
```

Maintainers may accept read-only recognition and diagnostic improvements while deferring control features that lack sufficient evidence. Leaving unknown devices untouched is an explicit compatibility policy.
