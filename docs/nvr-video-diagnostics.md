# 录像机视频接入诊断

目前普通摄像机和 NVR 仍只有诊断传感器，没有实时取流或录像机硬盘回放实体。
`inspect_video_session` 是开发诊断入口，不是播放功能修复。

它复用本集成已连接的欧瑞博云端会话，按 HomeMate APK 的 `cmd=148` 请求
Meari 外部授权。结果仅包含字段是否存在和阶段，不返回用户信息、token、hostKey、
厂商原始 JSON 或可复用的授权 URL；授权数据不写入配置或诊断文件。
该动作不建立 Meari MQTT 会话，也不连接摄像机、不修改设备、不查询或删除硬盘录像。
欧瑞博厂商授权请求本身是否影响手机会话尚未有真实账号验证。

## 运行

在已加载该诊断构建的 HA 中，打开“开发者工具 → 动作”，执行：

```yaml
action: orvibo_smart_control.inspect_video_session
data: {}
```

只有一个欧瑞博配置项时不需要配置项 ID；有多个时提供 `entry_id`。
中国账号默认 `country_code: CN`、`phone_code: "86"`、`language: zh`。
其他地区可指定国家代码和电话区号。需要现有云连接；纯本地模式不会自动切换到云端。

- `external_session_received`：取得了 API 地址、用户标识和用户 token。仅证明会话响应
  满足结构检查，不能证明 token 被厂商接受、实时画面或硬盘回放可用。
- `external_session_incomplete`：响应缺少必需字段。
- `session_rejected`：欧瑞博拒绝请求；`orvibo_status` 是返回的数值状态。
- `cloud_connection_required`：没有已连接的欧瑞博云会话。
- `no_response`：请求超时或当前会话不可用。
- `select_one_entry`：需指定一个有效配置项。

可以将动作返回的脱敏 JSON 用于后续排查，无需提供账号密码、设备 IP 或原始授权响应。

## 当前证据与下一阶段

用户目标是 HAOS 虚拟机/x86 Linux 宿主上的实时画面和录像机硬盘历史。
APK 的 Android ARM 原生视频库不能直接用于此环境。公开 MIT 项目
[Ha-CloudEdge-Meari](https://github.com/ajeanney/Ha-CloudEdge-Meari/tree/5bc9f97766c3d8076da8bb15dcb7b62ca7721127)
提供了可参考的 Python P2P 实时协议；其当前代码没有 NVR 硬盘索引、回放和定位实现。
该参考实现与欧瑞博账号、NVR 通道和媒体格式的兼容性尚未通过真实设备验证。

下一阶段需要验证外部厂商会话、读取实际设备/通道信息，再验证一个通道的首帧、
一个硬盘片段的检索和播放、以及定位。此诊断结果不会改变 `stream_supported=False`。
