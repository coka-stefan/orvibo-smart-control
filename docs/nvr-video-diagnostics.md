# NVR Video Integration Diagnostics

Ordinary cameras and NVRs currently have diagnostic sensors only; they do not yet have live playback or NVR hard-drive playback entities. `0.2.6b3` added a time-limited media connection and encoded first-frame probe, described below as `probe_video_stream`.
`inspect_video_session` is a development diagnostic entry point, not a fix that enables video playback.

It reuses this integration's existing ORVIBO cloud session and requests Meari external authorization using the HomeMate APK's `cmd=148`. The result reports only field presence and stage. It does not return user information, tokens, hostKey, raw vendor JSON, or reusable authorization URLs; authorization data is not written to config or diagnostic files.
The action does not establish a Meari MQTT session, connect to a camera, modify a device, or search/delete hard-drive recordings. Whether the ORVIBO vendor authorization request itself affects a phone session has not been verified with a real account.

## Run

In HA with this diagnostic build loaded, open “Developer Tools → Actions” and run:

```yaml
action: orvibo_smart_control.inspect_video_session
data: {}
```

If there is one ORVIBO config entry, an entry ID is not needed; if there are multiple, provide `entry_id`.
Chinese accounts default to `country_code: CN`, `phone_code: "86"`, and `language: zh`.
Other regions can specify a country code and calling code. An existing cloud connection is required; pure local mode does not switch to cloud automatically.

- `external_session_received`: API address, user identifier, and user token were obtained. This proves only that the session response passed structural checks, not that the vendor accepted the token or that live video/hard-drive playback works.
- `external_session_incomplete`: the response is missing required fields.
- `session_rejected`: ORVIBO rejected the request; `orvibo_status` contains the numeric status returned.
- `cloud_connection_required`: no ORVIBO cloud session is connected.
- `no_response`: the request timed out or the current session is unavailable.
- `select_one_entry`: specify one valid config entry.

You can use the action's redacted JSON response for follow-up diagnostics; there is no need to provide account credentials, device IP, or the raw authorization response.

## Vendor device-list diagnostics (`0.2.6b1`)

After the session action returns `stage: external_session_received`, run:

```yaml
action: orvibo_smart_control.inspect_video_devices
data: {}
```

This action refreshes the external session, signs the device-list request using the in-memory token, and sends one read-only query to the HTTPS API supplied by ORVIBO. It does not connect to MQTT or the camera, and it does not modify the device or hard drive.
Region and `entry_id` parameters are the same as for the session action. Tokens, device identifiers/names, keys, and raw responses are not included in the action response or written to integration config or logs.

The response retains `stage` for the ORVIBO session stage; `vendor_stage` gives the Meari request stage:

- `vendor_devices_received`: success code `1001` and recognized device categories were returned; inspect `device_count` and `category_counts`. An empty list is also a valid result and does not imply the user has no devices.
- `vendor_request_rejected`: the vendor returned a non-success code; `vendor_result_code` is a bounded numeric code.
- `vendor_http_error`: HTTP status was not 200; `vendor_http_status` is returned, and redirects are not followed.
- `inventory_request_data_invalid`: the API address or a required signature field from the session does not meet request requirements.
- `vendor_request_failed`, `vendor_response_too_large`, `invalid_device_response`, `unrecognized_inventory_shape`: network, response-size, or structure validation failed; do not claim authorization was accepted.

`devices` are numbered in list order and contain only fixed classifications, whether connection fields exist, and bounded raw capability codes.
`inventory_shape` distinguishes the App's top-level category structure from the `result` wrapper structure; arbitrary server keys are not returned.
At most 512 items are output. When there are more, `devices_truncated` is true while `device_count` remains the total row count.

NVR channels come from a later App device-parameter request, not a simple inventory field. This version therefore always returns `channel_query_implemented: false`. Codes such as `nct` cannot be interpreted directly as the number of online channels, and this action does not prove that a first frame or hard-drive recording can be played. Provide the complete redacted response for further diagnosis.

## NVR channel diagnostics (`0.2.6b2`)

In the real `0.2.6b1` response, the user confirmed that the vendor accepted authorization and returned one IPC and one `nvr-neutral` recorder, both with `iotType=3`. The SDK uses XTS authentication for these devices and derives a connection UUID from the serial number, so `uuid_present=false` alone does not block this path. This did not validate a media connection.

Install `v0.2.6b2` (an ordinary GitHub Release; prerelease mode is not required), restart, then run:

```yaml
action: orvibo_smart_control.inspect_video_channels
data: {}
```

The action fetches a session and device list once, then calls the vendor HTTPS batch API to read NVR properties `213,1015,67`. It reads only the cloud channel snapshot; it does not connect over P2P, start a live stream, or search/delete hard-drive clips.
Use the existing `entry_id` and region parameters. The response retains session and device-list diagnostic fields and adds:

- `channel_query_implemented`: channel-query code is included; this does not mean video is implemented.
- `channel_stage: nvr_channels_received`: the vendor returned a success code and result object. Inspect each `nvrs` item; top-level success does not imply every recorder has channel data.
- `nvr_count`, `queried_nvr_count`: identified and actually queried NVRs. At most 32 are queried; devices without a serial number are not requested.
- `nvrs[].index`: index into the current `devices` list, without exposing a device identifier.
- `maximum_channel_count`: capacity value from 213, separate from the count of actual returned channel entries.
- `channel_count`, `channels[].channel_id`, optional `state/type/capability_codes`: actual channel entries from 1015 and bounded capability codes. Unknown values are omitted; at most 128 channels are output.
- Per-NVR `channel_stage` can be `channel_state_received`, `channel_state_missing`, `invalid_channel_state`, or `nvr_result_missing`, distinguishing empty lists, missing data, and invalid data.
- Top-level stages such as `channel_request_rejected`, `channel_http_error`, and `channel_request_failed` indicate request failures; only bounded result codes/HTTP status are returned, not raw error text.

Cloud snapshots can be stale; raw `state/type` values do not directly establish that a channel is online or playable.
Starting with `0.2.6b4`, `video_playback_implemented=true` means that live-playback code is available; `real_device_video_verified=false` means this action did not validate real video playback in HA.
The user supplied a successful real result: the NVR's capacity and returned channel count were both 8; channels 1 and 3 had state=1 and p2p=2, while the others had state=0 and p2p=0.
This proves only that the cloud channel query succeeded; media must be tested separately.
See the [NVR Channel API](meari-nvr-channel-protocol.md) for request and static evidence.

## Specified-channel media test (`0.2.6b3`)

After installing the ordinary Release `v0.2.6b3` and restarting Home Assistant, first test channel 1 on the discovered NVR:

```yaml
action: orvibo_smart_control.probe_video_stream
data:
  device_index: 2
  channel_id: 1
  timeout_seconds: 35
```

Then change `channel_id` to `3` and retain both complete redacted responses.
`device_index` refers to the vendor inventory from that run; if inventory changes, run device/channel diagnostics again first.
Only NVR (`devTypeID=11`) or IPC (`devTypeID=2`, requiring `channel_id=0`) devices with `iotType=3` and `p2p=2` are accepted.
The action connects to one explicitly selected channel at a time; it returns `probe_in_progress` if a probe is already active for the same config entry.

The action obtains a fresh cloud session and inventory, then establishes signaling and a P2P/TURN media connection in a separate process and sends a live-start request for the selected channel. It does not fetch hard-drive indexes, save video, or write user credentials or raw responses.
The media budget is 10–60 seconds (35 seconds by default); obtaining the cloud session and inventory also takes time, and the action has an additional total deadline.
After timeout or cancellation, the parent forcibly stops and reclaims the child process to avoid leaving blocked network threads. Integration unload and HA shutdown also cancel probes.

The response retains session/inventory fields and adds:

| Field | Meaning |
| --- | --- |
| `probe_stage` | Last result; `probe_stage_history` lists attempted connection stages in order. A stage appearing does not prove that it succeeded. |
| `root_discovery` / `signaling_connect` / `signaling_registered` | Discover signaling address, attempt connection, finish registration |
| `device_status` / `turn_allocate` / `sdp_offer` | Query device status, request relay, send media negotiation |
| `ice_connect` / `kcp_connect` / `receiving_video` | Attempt ICE, send KCP/IVA handshake, send live-start request and wait for video |
| `video_keyframe_received` | Basic header/length structure of H.264/HEVC parameter sets and key NALs was recognized; this is not a full decode check |
| `encoded_video_verified` | The encoded structure probe above succeeded; this is distinct from `decoded`, playback, and history playback |
| `video_frames` / `video_bytes` / `codec` | Candidate video-frame count, encoded payload bytes, and codec name |
| `received_packets` | Total network packets received, including negotiation; not a video-frame count |
| `keyframe_received` / `parameter_sets_received` | Whether the encoded keyframe and required parameter sets passed basic structure checks |
| `no_video_frame` / `device_unavailable` / `probe_timeout` | No valid first frame after stream start, device status disallows connection, or time limit reached; do not infer a password error automatically |
| `probe_failed` / `dependency_missing` / `invalid_context` | Connection or protocol processing failed, dependency unavailable, or input session/device parameters invalid; raw errors are not echoed |
| `last_probe_stage` / `worker_stopped` | Most recent stage and whether the media subprocess exited and was reclaimed |
| `probe_device_index` / `probe_channel_id` | Explicit device index and channel requested for this probe |

The first-frame action still returns `decoded=false` and `real_device_video_verified=false` because it does not decode. Starting with `0.2.6b4`, `video_playback_implemented=true` means a separate live-camera playback output is available. Successful first-frame structure detection does not imply that hard-drive clips can be played.

Identity comes from the external session's `partnerId/userID`; credentials from another brand are not substituted.
This run simulated client version `5.2.6.307a13` and reused discovery protocol version `15259` from the pinned reference implementation; device compatibility still needs real testing.
Only the App's default hostKey mode is tried. If a separate video-password state is explicitly reported, this mode is rejected. The App may also store video-password state locally on the phone, so a missing field does not prove there is no video password.

## Current evidence and next stage

The user's target is live video and NVR hard-drive history on an HAOS virtual machine / x86 Linux host. The APK's Android ARM native video library cannot be used directly in this environment. The public MIT project [Ha-CloudEdge-Meari](https://github.com/ajeanney/Ha-CloudEdge-Meari/tree/5bc9f97766c3d8076da8bb15dcb7b62ca7721127) provides a Python P2P live-protocol reference; its current code does not implement NVR hard-drive indexing, playback, or seeking.
The user's real NVR channel 1 HEVC keyframe and parameter sets were received (153,474 bytes over 144 network packets). This confirms encoded data reception on the specified channel, not real continuous playback or hard-drive playback.

External session, inventory, and NVR channel queries have returned successfully in the user's environment. The next action validates a media first frame on one channel, then connects decoding and playback output; hard-drive clip search, playback, and seeking remain separate implementation work.
This probe does not change `stream_supported=False`.

## Live camera (`0.2.6b4`)

After updating, open the NVR's device page and select a new `camera` channel entity. Existing “Cloud” and “Meari” entities are diagnostic sensors; opening them does not show a picture. An entity is created for channels reported by cloud with state=1 and p2p=2 that also pass XTS session checks. Exact matching uses App `Device.uid` and `CameraInfo.deviceID`; it does not guess from names, device counts, or old inventory indexes.
If no entity appears, check that the NVR is selected, run `inspect_video_channels`, and see whether the integration's camera platform in HA is retrying.

`video_stage` is the current connection stage (a fixed value such as `idle`, `starting`, `connecting`, `transcoding`, or `streaming`). `streaming` means the transcoder has emitted data; it does not by itself prove that the browser displayed the video successfully.
Please report whether the picture is visible, results for channels 1 and 3, and whether closing and reopening restores the stream. Audio, hard-drive history, and the device timeline are not yet integrated.

See [Live Video](meari-live-video.md) for implementation details and limitations.
