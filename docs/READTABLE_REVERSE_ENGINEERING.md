# Reverse-Engineering Basis for Device Loading and State Merging

This update improves device loading and state synchronization based on static code analysis of ORVIBO Smart Home APK `5.2.6.307`. APK SHA-256:
`6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`.
The APK was not run, no ORVIBO server was called, and no real devices were connected; tests use synthetic data and transport mocks.

## Contracts confirmed in the APK

- `model/SyncTableData.java:30,131,162`: device loading uses HTTPS `v2/cmd/app/readtable`; `data.tableNameList` lists table names, and records are in `data[table name]`.
- `bo/device/DevicePropertyStatus.java:16`, `core/f.java:1786`: property status can be stored separately in the `devicePropertyStatus` table with fields `deviceId/property/value`.
- `data/e0.java:675`, `dao/p0.java:58`: property records are keyed by `(deviceId, property)`; `devicePropertyStatusId` cannot replace the business device ID.
- `core/g.java:1971,2034`: `deviceStatus.properties` is another source of properties.
- `bo/BaseBo.java:84`: `updateTimeSec` is converted to milliseconds and used for comparisons; batch writes in `dao/p0.java:64` accept entries without a timestamp or with a timestamp no earlier than the existing record.
- `core/c.java:3646` constructs ordinary control `cmd=15`; `core/g.java:2185,3434` dispatch status reports `cmd=42`. A control ACK alone does not prove that the device reached its target state.

These paths and line numbers refer to this decompiled export, not a vendor-published API or original source line numbers.

## Integration implementation

`protocol.parse_readtable_devices` handles both array tables and tables represented as dictionaries indexed by ID, retaining rooms, gateways, status aliases, subtypes, interface models, and legacy status values supplied by devices. The HTTPS wrapper and homepage fallback parser reuse this path. Unknown types remain in the inventory, while control capabilities continue to be determined by the existing capability table.

Properties from the device and device-status `properties` are merged first, followed by separate property records. Compound JSON strings are converted to objects/arrays; ordinary strings, numbers, booleans, and lists retain their types. Recursive merging retains members of the same property that were not updated; input objects are not modified.

Numeric timestamps on separate records are normalized to milliseconds; an older record does not overwrite a newer property. When no timestamp is available or timestamps are equal, this implementation uses arrival order, with separate records placed after embedded properties. A deleted record removes its property from the current snapshot and prevents a later older record from reintroducing it. This is the integration's explicit snapshot policy. The APK's batch SQL hardcodes `delFlag=0`, so that behavior cannot be applied directly to HA deletion handling.

LAN/SSL dispatch retains the current-state view needed by parsers but sends only fields assigned in the current update to `StateStore`. An explicitly reported value, even if unchanged, refreshes its protection window; brightness, color temperature, and similar fields that were not reported do not enter that window with a switch update. Partial updates for ordinary devices, switches, and clothes dryers retain omitted fields.

## Validation and remaining limits

Sixteen offline regression tests were added in `tests/test_readtable_loading.py`, covering both inventory formats, room/status joins, separate properties, JSON values, numeric timestamps, deletion flags, gateway fault tolerance, initial light state, and LAN/SSL field protection. The full Python 3.11 test suite passed, 477 tests.

This work added no control categories and did not change control payloads. Brightness ranges, curtain stop commands, and air-conditioner bit fields still need model-specific validation. Deletion of separate properties currently applies to the parsed snapshot; cross-snapshot cache invalidation, per-leaf property source protection, and periodic cloud state parsing for non-light devices need further work. Initial inventory loading on a clean install or reload still depends on the cloud; this does not establish that arbitrary gateways can be deployed fully offline.
