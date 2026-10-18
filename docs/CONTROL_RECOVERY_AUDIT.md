# Switch Control Failure Investigation

Investigation date: 2026-10-08.

User report: after controlling device switches from `smart-home-dashboard`, some switches could no longer be controlled through this integration. The interface showed no error, and restarting restored operation.

## Conclusions and evidence scope

The integration's cloud TLS control path had stability defects reproducible with automated tests: after a disconnect it retained an incorrect connection flag, and it swallowed send failures. These defects could produce the reported failure pattern: the switch does not act, the interface shows no error, and restarting restores operation. The related code has been fixed.

The investigation did not connect to the actual Home Assistant instance or physical devices, and no runtime logs from the failure were available. Therefore it cannot prove that operating a switch from the dashboard directly caused the cloud connection to drop, nor that every affected device had the same cause.

## Call flow between the two projects

In the dashboard, `src/features/devices/device-controls.ts` maps a light or switch power action to `turn_on` / `turn_off`. `src/adapters/homeAssistantAdapter.ts` sends `call_service` through the Home Assistant WebSocket, specifying the entity's domain and `entity_id`, and queues service calls. It does not log in to the ORVIBO cloud or create a separate ORVIBO device-control session.

After Home Assistant receives a service request, it calls the current integration entity method, then the coordinator and `ControlExecutor` select LAN or cloud TLS. Operating the same entity from the dashboard or HA's built-in page uses the same integration control path.

When LAN is unavailable, control falls back to the cloud; cloud-only devices also use the cloud. As a result, a cloud connection problem can affect only some devices.

## Reproduced and fixed defects

| Defect | Previous behavior | Behavior after the fix |
| --- | --- | --- |
| TLS reader disconnect left `connected=True` | `_listen_loop()` exited on EOF or a network error; `_reconnect()` returned immediately because the flag was still True, without actually logging in again | An unexpected exit immediately clears the connection flag and releases pending requests, then establishes a new session |
| Missing reader prevented recovery | The reconnect loop exited immediately when the reader was None | It still tries to establish a new connection when there is no reader |
| Temporary cleanup was treated as permanent closure | `_disconnect()` set `_closed=True`; later retries could stop after the first failed login | Temporary cleanup preserves retry capability; integration unload uses permanent closure |
| Send failure was swallowed | `_send_packet()` caught an exception and returned; `send_control_*()` then returned True, so the control layer could write an optimistic state | Raises `ConnectionError` to the caller and prevents false success; network errors also release requests and close the failed stream |
| Current control was dropped when the writer was missing | Packet sending only attempted reconnection and did not send the original command, while the caller still reported success | A missing or closed writer fails explicitly; a command with an unknown result is not replayed automatically |
| Send wait had no timeout | If `writer.drain()` did not return, the control call remained occupied, also blocking later dashboard operations in the queue | Each send waits at most 10 seconds; timeout releases the failed connection path and reports the error upstream |

The main change is in `custom_components/orvibo_smart_control/ssl_client.py`; regression tests are in `tests/test_ssl_client_recovery.py`.

## Verification results

Nine new tests cover EOF, network errors, missing reader/writer, continued retry after the first failed login, blocked sends, normal switch packets, explicit closure, and retry limits.

Before the fix, tests for disconnects, send failures, a missing writer, and blocked sends failed; after the fix, all passed.

Full verification command:

```powershell
python -B -m unittest discover -s tests -q
```

Result: 391 tests run, 390 passed, 1 skipped; none failed.

## Confirm on a real device

1. Update the integration code in Home Assistant, then reload the integration or restart HA once to load the code.
2. Operate the same switch from the HA built-in page and the dashboard, and confirm both update state and cause the same physical action.
3. If it fails again, first check whether the device's `transport_path` diagnostic entity is `lan` or `cloud`, and retain integration logs from around the failure time.
4. After a cloud disconnect, expect reconnection and a new login, not only a “reconnected” message without a new login. A send failure should be reported to the service caller.

The existing optimistic update behavior remains when a packet is sent normally but no device state confirmation arrives, so a successful service call does not prove the physical action occurred. If a pure-LAN device has the same issue, investigate gateway logs; it cannot be attributed directly to this cloud defect.
