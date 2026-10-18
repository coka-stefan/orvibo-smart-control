# XTS Specified-Channel Encoded First-Frame Probe

Adaptation is based on the HomeMate 5.2.6.307 APK provided by the user, SHA256
`6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`,
and the pinned MIT reference [Ha-CloudEdge-Meari](https://github.com/ajeanney/Ha-CloudEdge-Meari/tree/5bc9f97766c3d8076da8bb15dcb7b62ca7721127).
Vendor attribution, licensing, and the scope of modifications are documented in `meari_transport/vendor/ORIGIN.md` and `LICENSE`.

## Static APK evidence

- `SdkUtils.java:487–506,536–590`: `iotType=3` uses XTS/factory10, with UUID derived from SN; defaults are `username=admin`, `password=hostKey`, `auth=0`; NVR `devTypeID=11` corresponds to `devicetype=3`.
- `MeariIotController.java:177–215`: `brand` is the external session's `partnerId`, `clientid` is `userID`, `c` is `countryCode`, and `v` is the host app version plus the Android system version; do not substitute brand/account constants from public projects.
- Native `libmrplayer.so`, SHA256
  `4ef7e16fba2a5d043dfe98b2b61b159778f1eaf695aa1f27d8de8e933fc6d857`:
  ELF `0x1e6b2c` copies connection input to `ctx+0x128`, so `ctx+0x718=auth`,
  and `ctx+0x71c=(protocolv>1)`. ELF `0x1dd168` uses these to choose the full or first 16 password bytes and `licenceId`.
  The `licenceId` in the variadic call must be confirmed from assembly stack arguments; do not rely on the missing argument in decompiled C.
- ELF `0x1dd80c`, `0x1de0a8`, `0x1deb14`: live start, stop, and heartbeat commands are
  `0x11ff`, `0x12ff`, and `0x888e`, respectively, with `param=8` and packet length 60.
  The authentication function ultimately writes network-order 1 at header offset 4; the initial value 0 is not the final wire value.
- Live packet offset `0x34` is a little-endian uint32 for the low 24 bits of the channel; `0x38` is video quality, `0x39` is camera tags, and `0x3a` is reserved. This single-channel ordinary preview uses `tags=0` and `quality=0`; `channel=0` in SDP is transport signaling and does not replace the actual NVR media channel.

This version tries only the default hostKey mode. When `p2p=2`, the signature is the lowercase MD5 of these fields joined by `|`:

```text
admin | first 16 bytes of hostKey | decimal magic | seq | cmd | 8 | meari.p2p.ppcs | licenceId
```

When the SN has 9 characters, 7 zeros are prepended to the UUID and 11 zeros to `licenceId`; for other valid SNs, the first four UUID characters are removed and `licenceId` is retained. The `auth=1` path for a separate video password is not enabled. The implementation does not guess based on password length or cycle through authentication combinations.

## Lifecycle and result limits

The parent process refreshes the external session and inventory, selects one explicit device and channel, then sends a bounded set of parameters over private stdin to `python -I -u -B worker.py`. The command line contains only the script and installed dependency directories, not credentials. The worker reuses signaling, TURN, ICE, KCP, VVP, and encoded-frame primitives; it does not import HA, the full brand login, MQTT, or the reference engine, does not start keepalive/wake/relay-probe threads, and does not create other processes.

The process emits fixed JSON scalars, which are filtered again at the HA boundary. Logs, stderr, and raw protocol contents are not returned as diagnostics. Timeouts, cancellation, and exceptions all kill and wait for the worker, including blocked DNS. Complete output, line count, candidate count, network bytes, frame size, and KCP queue are bounded. The HTTP inventory response is released before the media connection starts. Each config entry allows one probe at a time; HA shutdown or config-entry unload waits for cleanup.

`encoded_video_verified` confirms only encoded-frame packaging, basic NAL header/length, required parameter sets, and random-access frame type; H.264 supports IDR, and HEVC supports IRAP 16–21. It does not fully validate RBSP or parameter associations, and it does not mean decoding succeeded. The first-frame action itself does not decode. `0.2.6b4` added separate continuous streaming and an HA playback output; see [Live Video](meari-live-video.md). Hard-drive recording search and playback are still unavailable.

The Android suffix in client version `5.2.6.307a13` is a simulated selection. The root discovery protocol version 15259 comes from the reference implementation. A HEVC keyframe was received from the user's channel 1; this does not establish compatibility with other devices.

User's real evidence: NVR index=2/channel=1, HEVC, 153474 bytes, 144 packets, parameter sets and keyframe present; `encoded_video_verified=true`, `decoded=false`. The worker was stopped when the probe ended. This does not establish successful continuous HA playback.
