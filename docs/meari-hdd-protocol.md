# Ordinary XTS HDD protocol evidence

Implemented from the Android APK and its ARM64 `libmrplayer.so`, with no claim
of real recorder playback verification. UI instructions: [HDD playback](meari-hdd-playback.md).

Artifact SHA256:

- APK: `6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`
- `libmrplayer.so`: `4ef7e16fba2a5d043dfe98b2b61b159778f1eaf695aa1f27d8de8e933fc6d857`

The ordinary HDD search sends VVP common command `0x8000` through the existing
KCP/IVA tunnel. IVA type `0x7010` carries control data; the native receive path
strips the 20-byte IVA header and queues the raw VVP reply. Media is identified
by its own frame prefix after tunnel demultiplexing. `0x7012` is the IVA handshake.

VVP is 52 bytes followed by payload: BE magic `0x56565099`, BE version `1`,
BE sequence, BE command, ASCII MD5 signature, BE payload length at byte48.
Default outer MD5 auth uses the first16 hostKey characters and the native
licence derivation. The HTTP body carries the full Java request object.

The fixed destination `http://127.0.0.1` is the recorder endpoint **inside the
device tunnel**, not an HTTP request to the Home Assistant host. Paths:

- `/devices/record/search_by_month`: action POST, rec_type0, videoid=actual
  channel, month=`YYYYMM`, deviceurl=fixed path.
- `/devices/record/search_by_day`: action POST, rec_type0, videoid=channel,
  version0, day=`YYYYMMDD`, deviceurl=fixed path.

Native wraps that JSON unchanged in HTTP/1.0 POST, Host127.0.0.1,
User-Agent `Awesome HTTP Client`, Content-Type `text/plain, charset=us-ascii`,
Connection close, Content-Length, and Basic `admin:FULL_hostKey`.
Native replies are JSON envelopes with http_code200 and JSON text in
http_result, not raw HTTP response bytes. Older VVP sequences are discarded;
newer sequences are rejected. Requests are serialized with a10s reply budget.

Month results are indexed flags (array position+1 gives the day). Version0 day
results are `HHmmss-HHmmss` strings. The calendar is the recorder calendar;
there is no implicit epoch or HA timezone conversion.

Ordinary time playback command is `0x131a`, total76 bytes, payload24:

| Absolute byte | Encoding and start value |
| --- | --- |
| 52 | LE uint32 actual channel |
| 56 | LE uint32 action16 (stop1) |
| 60 | LE uint32 tags shifted24, default0 |
| 64 | LE uint16 year |
| 66,67 | month,day |
| 68 | zero |
| 69,70,71 | hour,minute,second |
| 72 | start flag1 (stop0) |
| 73 | normal speed byte2 (stop0) |
| 74 | zero uint16 |

Start/stop advance the sequence; a matching start acknowledgement is required
before media is accepted. Acknowledgement alone is not playback proof.
The different record_id/type1 command `0x1360` is not implemented.

Compact/extended media stream type is byte23 for FC/FE, byte15 for FD/FA;
live=1, HDD=2. Extended format is LE DWORD at28 (FC/FE) or20 (FD/FA).
Native checks format `0xffb` before the stream type gate, causing playback end
callback0xc even if the end notification has an unspecified mode. Complete
extended headers are60/52 bytes. No equivalent compact end callback was proven.
The worker recognizes the end only in an acknowledged HDD session; ordinary
video still requires mode2 and the existing codec/keyframe checks.

Offline tests assert the byte vectors, sequence correlation, tunnel framing,
malformed/large replies, media selection and end markers. Device recording
lists, playback, positioning and multiple simultaneous sessions remain runtime
validation items.

## S1 / IPC storage-card playback (0.2.6b8)

The same APK's `MeariSDCardVideoPlayBackFragment.c8` selects a calendar time
and calls `MeariDeviceController.startPlaybackSDCard`. The fragment labels
positive NVR channels as HDD and the IPC path as card recordings. Its date
presenter `device/meari/video/t` calls both month/day APIs with videoid 0.
`getPlaybackVideoDaysInMonth` and `getPlaybackVideoTimesInDayImpl` preserve
that value unless a positive NVR/base channel replaces it. Ordinary S1 IPC
uses channel 0; no base-station or record-ID branch is enabled.

The single-surface playback overload forwards the selected stream ID and
substitutes positive NVR/base channels. `MeariDeviceUtil.getVideoStreamId`
returns [0, 1] when bps is absent/zero; the existing ordinary IPC path uses 0.
Nonzero-only stream profiles are not established by this change.

REA method evidence: `ev_df85a80722300d7da46e1640379eadcc5aa70a83c5488171b6827b2e006b6976`.
This is static decompiler evidence from the APK identified above; it does not
observe S1 execution. Tests cover channel-0 month/day requests, exact
start/stop payloads, historical media gating, and shared entity/card flows.
Real SD recording lists, playback and positioning still require the device.
