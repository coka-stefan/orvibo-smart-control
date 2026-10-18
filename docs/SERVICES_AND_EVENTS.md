# Services and Events Reference

All services are in the `orvibo_smart_control` domain. When there are multiple config entries, pass `entry_id` explicitly to avoid sending a request to the wrong household. Find the config entry ID under “Settings → Devices & Services → ORVIBO Smart Control.”

## Service overview

| Service | Purpose | Response |
| --- | --- | --- |
| `refresh_devices` | Immediately refresh the selected config entry's device snapshot | None |
| `set_lock_user_name` | Set or clear the display name for a door-lock user number | None |
| `fetch_video` | Fetch and archive a door-lock event recording | `ok`, `media_id`, or `error` |
| `list_events` | Query archived door-lock images/recordings | `events` |
| `cleanup_history` | Prune door-lock media by age or count | `removed` |
| `grant_temp_password` | Create a temporary door-lock authorization | New authorization metadata; `password` appears only in this response |
| `revoke_temp_password` | Delete a specified temporary authorization | `ok`, `authorized_id`, or `error` |
| `list_temp_passwords` | Read server-side authorization metadata | Grouped by device ID; no passwords |

Services with responses use Home Assistant's optional response mechanism. Set `response_variable` in an automation when the result is needed.

## Refresh and user mappings

### `refresh_devices`

`entry_id` is required; this service refreshes one config entry only.

```yaml
action: orvibo_smart_control.refresh_devices
data:
  entry_id: 0123456789abcdef
```

### `set_lock_user_name`

| Field | Required | Description |
| --- | --- | --- |
| `entry_id` | No | Recommended when there are multiple config entries |
| `device_id` | Yes | Door-lock device ID |
| `user_id` | Yes | Door-lock user number from the push |
| `name` | Yes | Display name; an empty string clears the mapping |

```yaml
action: orvibo_smart_control.set_lock_user_name
data:
  device_id: w-example-door-lock-id
  user_id: "2"
  name: John Doe
```

Mappings change only the display and event fields in Home Assistant; they do not modify users inside the lock.

To save names persistently, enter one mapping per line in the integration option “Lock User Mapping”: `userID=name`.
For multiple locks, use `deviceID/userID=name`. If different unlock methods reuse a number, specify a method, for example `deviceID/fingerprint/userID=name` or `deviceID/password/userID=name`.
Matching order is device plus method, method, device, then global user number; user number `0` is valid. Service changes last only for the current run and are scoped by device; after reload, the integration option takes precedence. If a name is missing, the user number is shown. If an inside opening has no reported identity, the card displays “Person unknown.”

## Media archive

### `fetch_video`

`device_id` and `object_key` are required. `object_key` must be a relative object key supplied by an event; full URLs, values with query strings, path traversal, and backslashes are rejected.

```yaml
action: orvibo_smart_control.fetch_video
data:
  device_id: w-example-door-lock-id
  object_key: /REDACTED/videoPicklockEvent/picklockEvent_1700000000.h264
response_variable: video_result
```

The successful response exposes only a Home Assistant media reference:

```yaml
ok: true
media_id: media-source://orvibo_smart_control/archive/...
```

The service does not return an absolute path on the Home Assistant host. Recordings are initially saved as H.264; if ffmpeg is available, they are remuxed as MP4 using stream copy.

### `list_events`

| Field | Default | Constraint |
| --- | --- | --- |
| `entry_id` | All matching config entries | Optional |
| `device_id` | All door locks | Optional; must belong to the target config entry and be a door lock |
| `limit` | `100` | `1..500` |
| `media_type` | All | Optional `image` / `video`; filter first, then apply the limit |

Each response record can contain only `device_id`, `kind`, `time`, `type`, and `media_id`.

```yaml
action: orvibo_smart_control.list_events
data:
  device_id: w-example-door-lock-id
  limit: 50
response_variable: lock_history
```

### `cleanup_history`

| Field | Default | Constraint |
| --- | --- | --- |
| `keep_days` | `7` | `0..3650`; `0` means do not retain old records |
| `device_id` | All door locks | Optional |
| `max_entries` | No count-based pruning | `1..10000`; retain newest records per device |
| `entry_id` | All matching config entries | Optional |

```yaml
action: orvibo_smart_control.cleanup_history
data:
  keep_days: 14
  max_entries: 500
response_variable: cleanup_result
```

The integration runs the default cleanup once at startup and then every 7 days. Recordings are retained for 7 days by default; snapshots are retained by count per lock, 30 by default. The “Door Lock Snapshot Retention Count” option supports `1..500`. Automatic age-based cleanup does not remove snapshots within the retention window. A manual call to `cleanup_history` can explicitly delete snapshots.

## Temporary passwords

### `grant_temp_password`

| Field | Default | Constraint |
| --- | --- | --- |
| `entry_id` | Automatically selected | Recommended when there are multiple config entries |
| `device_id` | First door lock | Must belong to the target config entry |
| `type` | `2` | `1` time-limited, `2` temporary |
| `minutes` | `1440` | `1..525600` |
| `number` | `1` | `0..100`; `0` means unlimited uses |
| `name` | Generated automatically | Up to 64 characters |
| `phone` | Empty | Optional, 6 to 20 digits, may start with `+` |
| `start_time` | Current time | Optional Unix timestamp in seconds |
| `end_time` | Calculated from duration | Optional, must be later than `start_time` |

The server allows at most 4 active authorizations. The service response includes metadata such as `authorized_id`, validity period, and use count; the six-digit `password` is returned only in the current response for a successful creation:

```yaml
action: orvibo_smart_control.grant_temp_password
data:
  device_id: w-example-door-lock-id
  type: 2
  minutes: 30
  number: 1
  name: Visitor
response_variable: temp_password
```

Do not write `temp_password.password` to logs, Recorder-visible entities, blueprint traces, or public notifications. Every 6 hours the integration checks locally known authorizations and attempts to revoke records that have expired or exhausted their uses.

### `revoke_temp_password`

`device_id` and a positive integer `authorized_id` are required.

```yaml
action: orvibo_smart_control.revoke_temp_password
data:
  device_id: w-example-door-lock-id
  authorized_id: 101
response_variable: revoke_result
```

### `list_temp_passwords`

`device_id` is optional. Results are grouped by device ID and contain server metadata such as authorization ID, validity period, use count, name, phone, and expiration status, but never the plaintext password.

```yaml
action: orvibo_smart_control.list_temp_passwords
data:
  device_id: w-example-door-lock-id
response_variable: authorizations
```

## Door-lock events

### `orvibo_smart_control_lock_event`

Door-lock state changes, unlocks, alerts, doorbell rings, and text messages are published as this event. Basic fields are below; optional fields without a value may be omitted or set to `null`.

| Field | Description |
| --- | --- |
| `device_id`, `uid` | Identifier of the door lock associated with the event |
| `source` | Original live channel, usually `ssl`; the `lan` enum is retained for a unified event contract |
| `locked`, `door_open` | Bolt and door-contact state |
| `inside_locked`, `child_locked` | Interior deadbolt and child-lock state |
| `leave_home_armed` | Away-mode security state |
| `kind` | Normalized event category |
| `time` | Device event timestamp |

Common `kind` values include `unlock`, `error_unlock`, `picklock`, `door_unclose`, `leave_home`, `ring`, and `message`. Unlock events may also include:

| Field | Description |
| --- | --- |
| `unlock_type` | `fingerprint`, `password`, `face`, or `card` |
| `unlock_method` | Normalized method: `fingerprint/password/card/key/face/temporary_password`; `null` if unknown |
| `open_direction` | `inside` or `outside` |
| `unlock_user_id` | Door-lock user number |
| `unlock_user_name` | Name from the configured mapping |
| `opened_by_user_id`, `opened_by_type`, `opened_by_name` | Attribution linking the most recent unlock with the subsequent door opening |

The new `doorLock/unlockEvent` field `userId` and old `unlock` field `userID` are both read as the lock-side authorization number. Under the four-credential rule, password, fingerprint, key, and card (including temporary passwords and duress credentials) mean opening from outside; all other unlock methods (including face recognition, unrecognized methods, or methods not reported by the lock) mean opening from inside. A door-contact opening without a matching one of the four outside credentials also counts as an inside opening and does not inherit the previous outside person's identity. This is the integration's inferred direction rule. It does not guess a person's identity from an outside-user mapping for an inside opening. Deadbolt state is not used to infer direction. The unlock-to-opening association window is 30 seconds; one unlock can be assigned to only one opening, and closing then reopening does not reuse the previous person. A delayed older unlock event is marked `historical: true`; its snapshot is still archived, but it does not change recent-opening state or identity.

Events with media may include short-lived signed URLs: `media_url`, `pic_media_url`, and `doorbell_media_url`. These URLs contain temporary access credentials; do not persist them or submit them in an Issue. Media is archived in the background and can then be accessed through services or the media browser.

Automation example:

```yaml
triggers:
  - trigger: event
    event_type: orvibo_smart_control_lock_event
    event_data:
      kind: unlock
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.unlock_user_id == 2 }}"
actions:
  - action: notify.mobile_app_phone
    data:
      title: Door unlocked
      message: >-
        {{ trigger.event.data.unlock_user_name
           | default('User ' ~ trigger.event.data.unlock_user_id) }} opened the door
```

### `orvibo_smart_control_temp_password_event`

Published after temporary authorization is created successfully. The event contains `device_id` and non-sensitive authorization metadata and explicitly excludes `password`. To obtain a new password, read only the current service response from `grant_temp_password`.

## Built-in door-lock cards

The integration registers two cards in the frontend:

- `custom:orvibo-smart-control-door-lock-card`: door-lock state, automatically saved snapshot history, and temporary-password management;
- `custom:orvibo-smart-control-temp-password-card`: create temporary passwords, list authorizations, and revoke them.

Standalone temporary-password card:

```yaml
type: custom:orvibo-smart-control-temp-password-card
device_id: w-example-door-lock-id
```

Overview card:

```yaml
type: custom:orvibo-smart-control-door-lock-card
device_id: w-example-door-lock-id
history_limit: 24
```

`history_limit` is optional and sets how many historical snapshots the card displays (`1..500`, default `30`).

Door-lock event snapshots are saved automatically under Home Assistant's `config/media/orvibo_smart_control/<device>/` directory. The most recent 30 are retained by default; change this in the integration options. The overview card's “Saved Snapshot History” section can refresh the list and open a large view of any thumbnail. Only snapshots count toward the limit; recordings do not. Old images are pruned only after a snapshot is saved successfully. Different images captured in the same second are saved separately, and after reload the latest view is restored from disk. You can also call `list_events` with `media_type: image` to get each snapshot's `media_id`.

If `device_id` is omitted, the card tries to select the lock with the most complete set of entities. In environments with multiple config entries or locks, configure it explicitly. The card calls the services above, and permissions depend on the current Home Assistant user. The authorization list does not return or redisplay plaintext passwords; a new password appears once after a successful creation. Do not expose a door-lock dashboard anonymously to the public internet.
