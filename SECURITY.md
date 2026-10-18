# Security Policy

ORVIBO Smart Control connects to a home LAN, the ORVIBO cloud, and the Home Assistant service bus. Account authentication, door-lock authorization, and event media must all be treated as highly sensitive data. This document describes reporting channels, trust boundaries, and requirements for submitted materials.

## Vulnerability reports

Do not disclose exploitable vulnerabilities, real credentials, or unpatched attack steps in public Issues. Prefer contacting maintainer `maycode0-0` through the repository's private GitHub Security Advisory reporting feature. If that feature is unavailable, first request a private contact channel through the maintainer's GitHub profile; send only an impact summary, not secrets.

Reports should include:

- Affected integration and Home Assistant versions;
- Preconditions for the attack, impact, and minimal reproduction steps;
- Relevant modules, stack trace, and a redacted representation of the protocol;
- Mitigations already tried;
- Whether there is a public exploit or known affected users.

Do not disclose full details until the maintainer confirms receipt. Use a public Issue for ordinary compatibility problems, device support requests, and bugs without security impact.

## Support scope

Security fixes target the latest released version. Users of older versions may be asked to upgrade first to rule out an already-fixed issue. Development branches and unpublished local changes have no compatibility commitment, but reproducible security defects in them are still welcome as private reports.

## Data classification

### Must be kept secret

- HomeMate / Smart Home 365 accounts, phone numbers, and plaintext passwords;
- Uppercase MD5 digests of cloud-account passwords and separate MixPad LAN passwords; these can be used directly for protocol authentication and must be protected like passwords;
- Access tokens, session IDs, session keys, dynamic keys, cookies, and OAuth parameters;
- Temporary COS keys, security tokens, signed media URLs, and private object keys;
- Temporary door-lock passwords, authorization IDs, and real user mappings;
- Home Assistant long-lived tokens, backups, `.storage` contents, and complete diagnostic bundles.

### Must be redacted

Family IDs, user IDs, device IDs, UIDs, status IDs, `extAddr`, MAC addresses, IP addresses, family/room names, and identifiable device names may not directly log into an account, but can reveal the household layout or link different datasets. In public materials, replace them with stable, obvious placeholders such as `REDACTED_DEVICE_A`; do not substitute another plausible-looking hexadecimal value.

### Public protocol compatibility materials

The shared client certificate and private key inside the component are used for compatibility with the vendor's TLS service. They come from publicly obtainable vendor-app protocol materials; they are not identity credentials unique to each user, and the server cannot distinguish Home Assistant instances using them alone. Reversible encryption of these files would not create a new trust boundary, because unattended connections require distributing the ability to decrypt them as well.

This does not reduce the sensitivity of account tokens and session keys. Shared certificates do not replace protection of runtime secrets.

## LAN boundary

The LAN channel discovers the MixPad and establishes a protocol-authenticated session over TCP `8088`. The implementation checks the expected gateway UID, session identity, response correlation, and pushed values, and masks IPs, UIDs, and device identifiers in logs.

Deployments must still:

- Avoid forwarding the gateway port to the public internet;
- Run Home Assistant on a trusted home network;
- When allowing traffic across VLANs, permit only the minimum traffic between HA and the specified gateway;
- Prevent untrusted clients from joining a network that can reach the gateway;
- Keep Home Assistant, the integration, and the host system up to date.

Cloud fallback after a LAN failure in the default combined mode improves availability; it is not a replacement for security authentication. Pure LAN mode explicitly forbids this fallback, and pure cloud mode does not connect to the gateway. Data from an unexpected gateway or malformed push must be rejected rather than accepted because the cloud exists. Use separate LAN credentials only when the MixPad actually uses a different account. The config entry stores a digest rather than plaintext; disabling this option deletes the separate username and digest and resumes using the cloud-account digest.

## Door locks and media

Door locks are cloud-only, read-only devices, but the temporary-password service performs a real authorization action. Before calling it, automations should restrict their trigger sources, door-lock `device_id`, authorization duration, and number of uses. Do not give anonymous dashboards or low-trust users permission to call the service.

`grant_temp_password` returns the password only once in the current service response; the event bus and list service do not return it again. Home Assistant automation traces, notification history, and third-party logs may still record response variables, so users must control those downstream systems themselves.

Event media is stored under Home Assistant's `media/orvibo_smart_control/` and may briefly appear in a signed URL. It may contain faces, door numbers, indoor surroundings, and access times, so it should be covered by backup encryption, access control, and retention policies. The default retention is 7 days, with weekly cleanup; adjust it using `cleanup_history`.

Local cleanup in the general options removes only the integration media directory above and can reset general options. It does not delete accounts, families, device selection, door-lock user mappings, entity registration, or Home Assistant `.storage`, and does not operate on other integration directories.

## Optional external notifications

Integration update checks are disabled by default. When enabled, Home Assistant accesses `api.github.com/repos/maycode0-0/orvibo-smart-control/releases/latest` at the configured interval of 6 to 168 hours, reads only the latest stable version tag, and creates a persistent notification with a fixed ID when it finds an update. The request does not include ORVIBO account, family, or device data. Device online/offline notifications are also disabled by default and can be sent to a user-specified `domain.service`; that notification service and its downstream storage will see the device display name and online/offline status.

## Logs, diagnostics, and packet captures

Before submitting, at a minimum check:

```bash
git diff --check
git grep -n -I -E "accessToken|sessionKey|sessionId|password|phone|familyId|deviceId|security-token"
```

Legitimate protocol fields will also match; inspect manually to confirm their values have been replaced. A JSON string may contain another layer of JSON, and images or videos may show entity IDs, family names, or temporary passwords.

Project diagnostics should retain only the minimum state needed to solve the problem and must not claim to include MQTT records: the current live cloud channel is the vendor's binary TLS/SSL long connection, and the project has no standalone MQTT client. Use packet capture tools only with accounts and devices you control.

See [Contribution Guide](CONTRIBUTING.md) for the full rules on sample submissions.

## Dependencies and releases

Runtime dependencies are defined by `manifest.json`. Commits must not introduce executables from unpinned sources, include real cloud responses, bypass HACS/hassfest validation, or write test credentials into a workflow. Release packages should contain only files needed to run the component. The project name, repository address, and integration domain are maintained together through the manifest, HACS metadata, CI validation, and code review.
