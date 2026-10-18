# Meari Live Camera

Starting with `0.2.6b4`, selected ORVIBO cameras/NVRs can use the vendor cloud authorization and XTS P2P/relay connection through HA `camera` entities. This applies only to IPC (`devTypeID=2`) or NVR (`devTypeID=11`) devices that actually report `iotType=3` and `p2p=2`, using default hostKey authentication. Other SDKs, separate video passwords, and audio are not supported.

## Use

1. Update to `v0.2.6b5` in HACS and restart HA; this version is an ordinary Release.
2. Select the NVR/camera in the integration's device selection, then open its device page.
3. Open the new “Channel 1,” “Channel 3,” or “Live View” camera entity. Diagnostic sensors do not show video.

The HA built-in picture glance card can be used on a dashboard (replace the example entity):

```yaml
type: picture-glance
title: NVR
camera_image: camera.your_nvr_channel_1
camera_view: live
entities: []
```

Initial authorization, P2P negotiation, and the first frame may take tens of seconds. The thumbnail request itself has a shorter timeout; a prepared connection is reused the next time the camera opens, and connections unused by a playback request are released automatically. The channel list is discovered when the platform loads. Reload the integration if connecting or disconnecting a camera changes that list. Pure LAN mode cannot provide the required vendor authorization.

HAOS includes FFmpeg; this integration declares `ffmpeg` and `stream` dependencies, so no separate video service is needed. Each channel being played uses one protocol subprocess and one FFmpeg process; software HEVC transcoding uses CPU.

## Media and lifecycle

- The platform matches selected devices by `App Device.uid == CameraInfo.deviceID` and creates entities by actual channel number. Each stream start refreshes the session, inventory, and channels; a change in inventory ordering will not switch to another device.
- The protocol subprocess receives the private session through stdin and emits fixed status fields and Annex-B video through a length-limited J/V pipe. Video is emitted only after parameter sets and a keyframe arrive. The existing first-frame diagnostic mode remains available.
- FFmpeg decodes HEVC/H.264 from the pipe and outputs H.264/yuv420p as MPEG-TS. HA Stream reads from a random localhost address and generates frontend HLS; the browser never connects directly to the private vendor protocol.
- The service binds only to `127.0.0.1` and disables access logging. Cloud account details and hostKey do not appear in URLs, command lines, diagnostic responses, or video files. Video is not stored automatically; recording explicitly requested by an HA user is a separate action.
- HA Stream is shared by viewers of the same entity, and thumbnails reuse its decoded keyframe. Protocol and transcoding processes are reclaimed when a client disconnects, media stops, a timeout occurs, the platform is removed, or HA shuts down, including cancellation while a process is starting.
- Unused prepared connections are reclaimed after 20 seconds. The first transcoded output is allowed up to 55 seconds; a continuous stream with no output exits after 30 seconds. Each connection runs for at most one hour, after which HA reconnects normally. HA HLS keeps a brief buffer, so closing the frontend may not release it immediately; HA “preload” keeps the stream active according to that setting.

`video_stage` is a fixed connection stage; `streaming` means only that the transcoder has emitted data. Static SDK analysis cannot tell whether each device passes dynamic validation; entity creation depends on the actual inventory, identity match, and channel capabilities.

## Validation limits

The user confirmed that the real NVR's channel 1 is viewable; channel 3 loads slowly but becomes viewable after waiting. A 153,474-byte HEVC keyframe and parameter sets were received; current user validation confirms live playback. No hard-drive recording result has been received.

Local tests include actual FFmpeg synthesis of HEVC → H.264 MPEG-TS → forced H.264 decoding, and cover identity matching, channel selection, session refresh, process timeouts, disconnect cleanup, and cancellation cleanup. Offline results do not replace validation of real video and browser playback. There is currently no audio; frame timing is based on the receive clock, and the device's audio/video timestamps and synchronization have not been ported. Timing accuracy under network jitter still needs real-world validation.

Hard-drive history uses a different set of search and playback commands; a live keyframe does not validate it. Calendar, clip, and playback controls were added in `0.2.6b5` and still need validation on real devices. See [Hard-Drive Recording Playback](meari-hdd-playback.md) for instructions.
