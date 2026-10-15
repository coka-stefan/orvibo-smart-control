# Meari NVR 通道快照接口

依据：HomeMate APK 5.2.6.307，SHA256 `6ea3f3eff41ad4657ca437d10c79022949a1f080af857a8800dc6b6819abac8c`。以下是静态调用证据，通道批量接口尚待用户环境验证。

`_1IB.m947Z51OSo`（Java 导出第 14603 行）将原始 SN 列表与属性列表合成 `snIdentifier` JSON，
由 `i.e(5)` 加会话参数及表单签名，`SdkUtils.getOKHttpHeader` 对该接口路径另做头签名。
`ql.g.a()` 使用 GET。`O55lO` 从 `SdkCacheUtil.getNvrList()` 取 SN，固定查询 `213,1015,67`。

```text
GET {cmd148下发的apiServer}/v1/app/nvr/iot/model/get/batch
snIdentifier={"<SN>":"213,1015,67"}
```

`JsonUtil.getIotInfoListBatch` 将整个响应的 `result[SN]` 交给 `getDeviceParamsIot`；
213 表示容量，1015 是包含 `state` 数组的 JSON 字符串，各项为 channel/state/type。
67 为按通道编号关联的能力集合。`matchNvrChannel` 再按 SN 绑定到父录像机，
`MeariDeviceUtil.dealNvrChannel` 构造对应通道对象，不能用欧瑞博业务 deviceId 代替 channel ID。

REA 对 `JsonUtil.getIotInfoListBatch` 的精确方法复核：
`ev_38a7b8bbf1a17f36493ccae55418dff9c4674945b021e11b9df9ef302dd488d2`，
Java body complete、无 fallback。反编译证据没有执行 APK。

集成只向会话下发的 HTTPS API 发送请求，不跟随重定向；响应限 2MB、单请求限 20 秒。
SN、token、原始属性与密钥仅保留在请求内存，返回值使用固定键及有界数值，不输出名称或任意服务端字符串。
这只提供云端通道快照，不证明通道当前在线，也没有媒体流。

硬盘录像的月/日索引另走已连接的 native/P2P `commomrequest2`，内部参数包含
`deviceurl` 的 `/devices/record/search_by_month` 或 `/devices/record/search_by_day`、
年月/日期及实际 `videoid`。这些内部 URL 不表示设备开放了可供 HA 直接访问的 HTTP 接口。
实时首帧、硬盘片段检索、回放与 seek 均需单独实现及真实设备验证。
