# Meari NVR Channel Snapshot API

Source: HomeMate APK 5.2.6.307, SHA256 `6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`. The following is static call evidence; the batch channel API has not yet been validated in the user's environment.

`_1IB.m947Z51OSo` (Java export line 14603) combines the raw SN list and property list into `snIdentifier` JSON. `i.e(5)` adds session parameters and a form signature, while `SdkUtils.getOKHttpHeader` signs the API path separately. `ql.g.a()` uses GET. `O55lO` obtains SNs from `SdkCacheUtil.getNvrList()` and always queries `213,1015,67`.

```text
GET {apiServer supplied by cmd148}/v1/app/nvr/iot/model/get/batch
snIdentifier={"<SN>":"213,1015,67"}
```

`JsonUtil.getIotInfoListBatch` passes the entire `result[SN]` response to `getDeviceParamsIot`; 213 represents capacity, 1015 is a JSON string containing a `state` array whose entries have channel/state/type fields, and 67 is a capability set keyed by channel number. `matchNvrChannel` then binds by SN to the parent NVR, and `MeariDeviceUtil.dealNvrChannel` constructs the corresponding channel object. The ORVIBO business `deviceId` cannot be used in place of the channel ID.

Exact method review of REA `JsonUtil.getIotInfoListBatch`:
`ev_38a7b8bbf1a17f36493ccae55418dff9c4674945b021e11b9df9ef302dd488d2`,
Java body complete, no fallback. This is decompilation evidence; the APK was not executed.

The integration sends requests only to the HTTPS API supplied by the session and does not follow redirects; responses are limited to 2 MB and each request to 20 seconds. SNs, tokens, raw properties, and keys exist only in request memory. Returned values use fixed keys and bounded numbers; names and arbitrary server strings are not emitted. This provides only a cloud channel snapshot, does not prove that a channel is currently online, and does not provide a media stream.

Hard-drive recording month/day indexes use a separate native/P2P `commomrequest2` request. Its internal parameters include `deviceurl` paths `/devices/record/search_by_month` or `/devices/record/search_by_day`, a year/month or date, and the actual `videoid`. These internal URLs do not mean the device exposes an HTTP interface that HA can access directly. Live first frames, hard-drive clip search, playback, and seeking each require separate implementation and validation on real devices.
