# Camera SD Card and NVR Hard-Drive Playback

`0.2.6b5` added hard-drive recording date/clip search and playback by time; `0.2.6b8` extended support to SD/TF card recordings on the S1 Jumu 2K Smart Camera. The user confirmed that live NVR channels 1 and 3 are viewable.
**Hard-drive and SD card search and playback still need validation on real devices.**

## Open playback

1. Update to `v0.2.6b8` in HACS, restart Home Assistant, and force-refresh the browser.
2. Edit the dashboard → Add Card → search for “ORVIBO Recording Playback.” You can also add a manual card:

   ```yaml
   type: custom:orvibo-smart-control-nvr-card
   title: ORVIBO Recording Playback
   ```

3. Select a device/channel, such as “S1 SD Card Playback” or “NVR Channel 1 Hard-Drive Playback,” choose a date, and click “Search recordings.” To search the current month, open “More Options → Search dates this month”; click a returned date to search its clips.
4. Click a clip to play it. You can also enter a “Specified playback time” in “More Options” and click “Play.” The initial P2P connection can take about a minute. Click “Stop playback” to release the connection.

The card uses a compact layout and automatic height by default. The clip list takes about three rows at most, with additional clips scrollable inside the list. After playback starts, the clips and additional options collapse automatically; click “Recording clips” to expand them when selecting another clip. The player is below the channel and date, so a long list does not push it to the bottom of the page.

If the old dashboard had a fixed row count and has a large blank area after the update, set the card's “Layout” to automatic height or add the following to the card YAML:

```yaml
grid_options:
  columns: 12
  rows: auto
```

Set `entity: camera.your_nvr_channel_1_hdd` to pin the card to a specific playback entity; for the S1, select its “SD Card Playback” entity. Starting with `0.2.6b6`, the integration automatically registers the card in the storage-mode dashboard resources, updates an existing older URL, and refreshes the cache using a script-content checksum. YAML mode does not modify user configuration and continues to load the frontend module globally.

If you see `Custom element doesn't exist: orvibo-smart-control-nvr-card`, the card script has not been registered. In “Settings → Dashboards → upper-right menu → Resources” (Advanced Mode must be enabled), add:

```text
/orvibo_smart_control/www/orvibo-smart-control-nvr-card.js?v=0.2.6b8
```

Choose “JavaScript module,” save, and force-refresh. In YAML resource mode, use the same URL and `type: module` in `lovelace.resources`. If it still does not load, open the path above directly on the same HA address; it should return JavaScript source. If it returns 404, check the installed version and HA logs for “ORVIBO card static resource registration failed.”

If no playback entity appears, make sure the S1 or NVR is selected under the integration's device selection. S1 channel 0 is an internal protocol number; the card shows the device name. NVR entities are created for online channels. Restart HA after updating to b8 to create the new S1 playback entity. If you previously registered the b7 card resource manually, update its URL to `/orvibo_smart_control/www/orvibo-smart-control-nvr-card.js?v=0.2.6b8` to avoid a duplicate old entry.

Dates and times use the **camera or NVR's own calendar time**; they are not automatically converted to the HA time zone. A day list shows up to 256 valid clips and displays a truncation notice if there are more; playback can still be started for a specified time.

## Developer tool actions

`orvibo_smart_control.search_hdd_recordings`:

```yaml
entity_id: camera.your_nvr_channel_1_hdd
operation: day
date: "20261015"
```

For a month search, use `operation: month` and a six-digit date such as `"202610"`. A successful response has `stage: hdd_search_received` and includes `recording_days` or `fragments`. A connection failure response contains only a fixed stage; you can share the response for diagnosis.

`orvibo_smart_control.start_hdd_playback`:

```yaml
entity_id: camera.your_nvr_channel_1_hdd
date: "20261015090000"
```

This action selects a playback position; connection setup begins only after opening the corresponding camera. `playback_selected` means only that a time was selected and does not prove that a recording was received. To stop, use `orvibo_smart_control.stop_hdd_playback` with the same `entity_id`.

## Current scope

- Supports ordinary SD card recordings from IPC devices (including S1) and ordinary NVR hard-drive recordings for Meari XTS/p2p=2 devices using default hostKey authentication. Cloud storage and the other recording mode that requires `record_id` are not supported.
- Each IPC or NVR channel has a separate live/playback entity, and searching also creates a separate short-lived connection. Whether the device allows multiple simultaneous connections depends on the device. Audio, pause, and variable speed are not supported; choosing another time reconnects to seek.
- Playback does not automatically restart from the beginning when it ends. Click a clip again or choose a new time.
- A thumbnail does not start recording playback, and playback does not automatically save video files. Unload or HA shutdown cancels searches and cleans up the protocol, FFmpeg, and HA Stream.
- `video_diagnostics` on the live entity provides a fixed stage, connection count, failure/timeout counters, and frame/byte statistics. `streaming` means only that transcoded video was emitted; it does not replace visual verification.

Offline validation covers native command bytes, tunnel request/reply sequence numbers, calendar and clip parsing, playback media types and end markers, cancellation cleanup, entity switching, and card interactions. Users still need to validate search results, playback smoothness, and seek accuracy for real hard-drive and SD card recordings.
