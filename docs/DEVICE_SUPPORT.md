# Device Support Matrix

This document records device recognition, Home Assistant platforms, and transport boundaries for ORVIBO Smart Control `0.1.0`. “Verified” means the maintainer has checked real-device state and control for that category; it does not mean that every product model under the same `deviceType` is inherently compatible.

## Legend

| Label | Meaning |
| --- | --- |
| LAN preferred | Control is first sent to an authenticated, reachable MixPad; after failure it retries through the cloud at most once |
| Cloud control | Device control uses the ORVIBO cloud TLS long connection; LAN pushes may still contribute to merged state |
| Cloud-only | LAN does not take over state or rich features |
| Read-only | No device control commands are sent; state is received and displayed |
| Registered | Device information can be displayed, but no entity or control path has been verified |

The LAN-controllable `deviceType` set in automatic mode is
`0, 1, 34, 35, 36, 38, 81, 102, 501, 502, 503, 516`. Each actual device must also be classified using the complete `deviceType + subDeviceType + classId + ui.model` tuple, and its gateway must be connected.

## How transport mode affects device support

| Mode | LAN-controllable devices | Cloud-controlled / cloud-only devices |
| --- | --- | --- |
| Combined LAN + cloud (default) | Uses LAN when the gateway is online; retries through cloud once after failure | Uses cloud directly |
| Pure LAN | Receives live state and control only through an authenticated MixPad; no fallback | Runtime state and control unavailable |
| Pure cloud | Does not connect to MixPad; state and control use cloud | Uses cloud normally |

Startup in pure LAN mode still requires cloud login and inventory discovery to confirm the family, devices, gateway UID, and trusted address. Pure LAN limits live state, control, and periodic polling after discovery. “LAN preferred” in this table describes default combined mode; in pure LAN mode, the same device no longer has cloud fallback after a failed LAN command.

The Home Assistant device page includes a “Transport Path” diagnostic entity showing the policy above as `LAN`, `Cloud`, `LAN preferred, cloud fallback`, or `Unavailable in current mode`. It does not add a suffix to the device name; the latest actual control path and gateway connection status are in the entity attributes.

## Lights and switches

| Device or protocol profile | Home Assistant | Capabilities | Control |
| --- | --- | --- | --- |
| S2 anti-glare spotlight | `light` | On/off, brightness, color temperature | LAN preferred |
| S3 / S5 / S10 series spotlights | `light` | On/off, brightness, color temperature | LAN preferred |
| Soft-light series spotlights | `light` | On/off, brightness | LAN preferred |
| Magnetic track-light series | `light` | On/off, brightness, color temperature | LAN preferred |
| Smart light-strip controller | `light` | On/off, brightness, color temperature | LAN preferred |
| 0–10V dimmer module | `light` | Dimming mode; some models support color temperature | LAN preferred |
| MixSwitch / TouchClassic / Gauss / Defy / BACH | `switch` or `light` | One to four switches, classified by profile | LAN preferred |
| `501`, subtypes `426/429` | `light` | Monochrome light on/off | LAN preferred |
| `102` | `switch` | Standard switch | LAN preferred |
| `502` | `light` | On/off, brightness | LAN preferred |
| `38` | `light` | On/off, brightness, color temperature | LAN preferred |
| `503` | `light` | Tunable-white light strip | LAN preferred |

`deviceType=0` is currently treated as a dimmable light and `deviceType=102` as a standard switch. If a new model behaves differently, submit protocol samples and tighten classification; do not add speculative branches.

## Curtains and motors

| Device or protocol profile | Home Assistant | Capabilities | Control |
| --- | --- | --- | --- |
| Zigbee curtain `34` | `cover` | Open, close, position, stop | LAN preferred |
| Tubular motor `35/-2` | `cover` | Open, close, position, stop | LAN preferred |
| Dream Curtain `506/408` | `cover` | Open/close, position, stop, blade angle | Cloud control |

Dream Curtain blade angle can be adjusted only when fully closed; before setting the open/close position, the integration confirms that the blades have returned to the middle. High-voltage motor mode `37` is not yet supported.

## HVAC and fresh air

| Device or protocol profile | Home Assistant | Capabilities | Control |
| --- | --- | --- | --- |
| Fan-coil air conditioner `36` | `climate` | On/off, target temperature, mode, fan speed | LAN preferred |
| MixPad floor heating `300/481` | `climate` | On/off, target/current temperature, humidity | Cloud control |
| Legacy floor heating `112/-2`, `orb_floorheat` | `climate` | On/off, target/current temperature | Cloud control |
| Fresh-air system `516` | `fan` | On/off, stop/low/high presets | LAN preferred |

Do not classify all `deviceType=300` devices as locks or cloud-only: `481` is controllable floor heating, while `491` is a read-only temperature/humidity sensor. Classification must use the subtype.

## Sensors

The devices below do not accept control commands. State from sensors that are not cloud-only may be merged from LAN live pushes, cloud live pushes, or REST snapshots, following the configured source priority. In pure LAN mode after startup, only LAN live changes are received.

| Device or protocol profile | Home Assistant | State |
| --- | --- | --- |
| Motion sensor `26` | `binary_sensor`, `sensor` | Motion, battery |
| Door/window sensor `46` | `binary_sensor`, `sensor` | Door contact, battery |
| Temperature/humidity sensor `300/491` | `sensor` | Temperature, humidity, battery |
| Smoke detector `27` | `binary_sensor`, `sensor` | Smoke, battery |
| Combustible-gas detector `25` | `binary_sensor`, `sensor` | Gas; no battery entity for line-powered models |
| Emergency button `56` | `binary_sensor`, `sensor` | Trigger, battery; resets after a timer |
| Water-leak detector `54` | `binary_sensor`, `sensor` | Water leak, battery |

Temperature/humidity sensors remain independent devices; they are not forcibly linked to a floor-heating panel just to reuse its readings.

## Door locks and clothes dryers

| Device or protocol profile | Home Assistant | Capabilities | Channel |
| --- | --- | --- | --- |
| Smart lock `107/522` | `sensor`, `binary_sensor`, `camera` | Lock/door contact, battery, events, snapshots, recordings, temporary passwords | Cloud-only; device control is read-only |
| Smart clothes dryer `52` | `sensor` and feature entities | Light, sterilization, air-dry, heat-dry, raise/lower | Cloud-only; controllable |

Even if MixPad discovers a door lock, it does not use the LAN state or control path. Temporary passwords and media use cloud services rather than the ordinary device-control channel. To use locks or clothes dryers, do not select pure LAN; keep the default combined mode or use pure cloud mode.

## Cameras and NVRs (read-only diagnostics)

Ordinary cameras (`deviceType=14`) and NVRs (`deviceType=162`) appear in the “Cameras” device-selection group. If selected, the integration creates only “Transport Path” and “Camera SDK Recognition” diagnostic sensors; it does not create live camera entities. Diagnostics remain viewable when the device is offline. SDK type comes from the latest inventory snapshot and does not mean a live connection succeeded.

The `cameraInfo` supplementary table is associated by hardware `Device.uid`; HA's `device_id` remains the business `Device.deviceId`. Only the supplementary table's `type` is retained as `camera_type`; its token, password, and SDK credentials are not stored. App `Device.deviceType`, App `CameraInfo.type`, and catalog `productType` are separate fields.

| Device type / camera table type | SDK hint | Evidence limit |
| --- | --- | --- |
| `14` / `3–7` | Danale | Static type branch |
| `14` / `8–10` | Meari | Static type branch |
| `14` / `-1, 1, 2` | EZVIZ | Static type branch |
| `162` | Meari | NVR page entry |
| `14` / missing or other value | Unknown | May be an older SEP2P or model-priority branch; no guess is made |

Combined and pure-cloud modes show the cloud inventory path; pure LAN shows “Unavailable in current mode,” while existing inventory diagnostics remain visible. The cloud marker here means only that this integration's inventory comes from the cloud; it does not mean the video stream must use the cloud. Devices do not use MixPad LAN state/control, and SDK control, NVR channel playback, and guessed RTSP URLs are not exposed. Catalog `521` has not been connected to the main playback call path, so no playback support is inferred.

Type branches come from static reverse engineering of HomeMate APK `5.2.6.307`: `ActivityTool.j` and Flutter `gc.b.d/c`. APK SHA-256:
`6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`.
Reviewable REA Evidence:
`ev_9d0f3dbb5f213df33b5f9acc09d5baf74c11dfc30bb2d40ee7497d17d8e00acc`
and `ev_1ae7d7ced477d6d3bbd9ed9db22d48080df5664ecf758855ad741c7eacf73acc`.
The native app also has model-priority branches, so the sensor reports an SDK hint, not a runtime assertion for every model.
This work did not include real-device validation, vendor SDK authentication, or a verified HTTP/RTSP stream URL; `hardware_verified` and `stream_supported` are both false. The APK's legacy camera SEP2P path also does not prove that all door-view locks use the same protocol.

## Deliberately unsupported or hidden

| Type | Current behavior | Reason |
| --- | --- | --- |
| Virtual light group `10086` | No controllable entity | Avoid duplicate controls with member devices |
| High-voltage motor `37` | Registered or ignored | No complete control and response validation |
| Unknown category | Registered for display only | Never send speculative commands to an unknown device |
| Gateway and parent container | Entities hidden | Topology or transport role only |

The integration includes an exact model catalog generated from the public ORVIBO device catalog. A catalog match proves only that a product can be recognized, not that its state or control is supported.

## Submitting a new device

New models need at least a redacted initial snapshot, physical/App state pushes, request and response for each control, value units, and real-device results. See the [Contribution Guide](../CONTRIBUTING.md) for collection steps, classification entry points, and the test matrix.
