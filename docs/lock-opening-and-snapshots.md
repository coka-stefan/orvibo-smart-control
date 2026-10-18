# Door Lock Direction, Unlocker Identity, and Snapshots

This work was checked against existing decompilation artifacts from HomeMate 5.2.6.307 (APK SHA-256
`6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`). The APK was not run and no new commands were sent to a lock. Source paths below are relative to the reverse-engineering package's `java/sources/` directory; these are static observations and do not mean all firmware has been tested.

| Static evidence | Integration handling |
| --- | --- |
| `com/orvibo/homemate/model/bind/scene/thing/a.java:24`: `doorLock/unlockEvent`, `userId`, password/card/fingerprint/temppassword/face | Supports the new event and normalizes the unlock method |
| `com/orvibo/homemate/core/g.java:2947`, `:2953`: `unlock`, `userID`, `picture_url` | Supports the old event and retains the snapshot URL |
| Same file `:2960`, `device/smartlock/auth/AuthInfoFragment.java:478` | Treats the user number as the lock's authorization number, not a login account |
| `com/orvibo/homemate/util/f3.java:158`, `:197` | Old standalone-record enum: 1 fingerprint, 2 password, 3 card, 4 temporary password, 5 key |
| `com/orvibo/homemate/device/smartlock/ble/status/f.java:105`, `LockSafetyProblem.java:287` | Old standalone record 20 explicitly means unlocking from inside; parsed only for old records with `value2=65535` |
| `com/orvibo/homemate/model/bind/scene/thing/a.java:39` | `insideLockState` represents only the deadbolt, not unlocking from inside |
| `com/orvibo/homemate/device/smartlock/LockKeyUnlockAlarmSettingActivity.java:115` | `manual_unlock_alarm` is a key alarm; the word `manual` does not mean unlocking from inside |

The integration follows the rule requested by the user: password (including temporary password), fingerprint, key, and card count as opening from outside; all other unlock methods (including face and unknown methods), and door openings caused by a door-contact change that is not associated with one of those four credential types, count as opening from inside. An inside opening does not inherit any prior outside user's identity and displays the person as unknown. This is a direction inference rule; it does not mean the firmware explicitly reported an inside opening. The numeric `type=20` from the new thing model is not interpreted using the old enum, and the old packed `value4` is not treated as a direct enum value.

Names come from the integration option's mapping, which supports scoping by device and credential method. The person cannot be recovered when the lock reports no identity. See [Services and Events Reference](SERVICES_AND_EVENTS.md).

Snapshots use the existing COS credentials and object keys. The integration tries immediately and retries with a newly signed URL if needed. After download, it saves the file atomically and prunes each device's archive to the configured number of recent images (30 by default); retained images are not affected by the automatic 7-day video cleanup. Different objects captured in the same second are archived separately, and a late old event does not replace the current newer image. On reload, the integration restores images from disk; on unload, it cancels download tasks and waits for any active disk operation to finish.

Regression coverage includes both event formats, administrator ID 0, credential-based direction priority, clearing identity for inside openings, expired and duplicate events, assigning one unlock to only one opening, per-device and per-method name mappings, snapshots in the same second, download retries, concurrent saves, reload restoration, retention pruning, image filtering, and card refresh when the camera changes. Tests do not replace validation on a real door lock.

## Overview card

The overview card shows the main lock, door contact, and deadbolt separately. It prefers a battery source with a valid percentage; 0% is valid. The recent-opening section shows the person, inside/outside direction, unlock method, and time. When the person is unknown for an inside opening, the card does not show the name from the previous outside opening.

The door-view snapshot section shows the 30 most recent images by default. It previews the newest image separately and lets the user scroll horizontally through the remaining thumbnails. Selecting an image opens a large view; use the previous/next buttons or left/right arrow keys to move between images. Escape closes the view and returns focus to the image. The refresh button in the upper-right retries image loading. If a refresh fails, existing snapshots remain; if an image itself cannot load, the card offers a retry.
`history_limit` controls only how many images the card displays. Disk retention is set in the integration option “Door Lock Snapshot Retention Count.”

Starting in `0.2.6b14`, images and videos are read through the integration's separate media source:
`media-source://orvibo_smart_control/archive/<device>/<file>`. The media endpoint uses Home Assistant authentication and signatures. Existing archives remain under `config/media/orvibo_smart_control/`; there is no need to configure `media_dirs` or move files. The card parses image URLs using HA's `media_content_id` parameter.

The card follows Home Assistant's light and dark themes and adapts to narrow columns and phones. After upgrade and restart, when HA finishes starting, the integration checks the resource URL again and updates it in place, preserving the existing resource entry and card configuration. If the browser still loads an old script, force-refresh the page. The separate temporary-password card continues to use its existing custom type and services.
