# 录像机硬盘录像

`0.2.6b5` 新增硬盘录像日期/片段查询和按时间播放。实时通道 1 已获用户确认可看，
通道 3 在等待后也能播放。**硬盘查询和回放尚待真实录像机验证**。

## 打开回放

1. 在 HACS 更新到 `v0.2.6b5`，重启 Home Assistant，刷新浏览器。
2. 编辑仪表盘 → 添加卡片 → 搜索“欧瑞博硬盘录像”。也可添加手动卡片：

   ```yaml
   type: custom:orvibo-smart-control-nvr-card
   title: 录像机硬盘录像
   ```

3. 选择通道，如“录像机 通道 1 硬盘回放”，选择日期，点击“查询当天”。
   “查询当月”会显示有录像的日期，点击日期可查询片段。
4. 点击片段播放。也可填写“指定回放时间”后点击“从此时间播放”。首次建立 P2P
   连接可能需要约一分钟。点击“停止回放”释放连接。

卡片可通过 `entity: camera.your_nvr_channel_1_hdd` 固定为一个硬盘回放实体。
若卡片列表没有更新，先强制刷新；需要手动资源时，资源地址为
`/orvibo_smart_control/www/orvibo-smart-control-nvr-card.js`，类型 JavaScript 模块。
若没有回放实体，请检查集成设备选择中已勾选录像机；实体随在线通道创建。

日期和时间采用**录像机本身的日历时间**，不自动按 HA 时区换算。日列表最多展示
256 个有效片段，超过时会提示截断；仍可指定时间播放。

## 开发者工具中的操作

`orvibo_smart_control.search_hdd_recordings`：

```yaml
entity_id: camera.your_nvr_channel_1_hdd
operation: day
date: "20261015"
```

月查询使用 `operation: month` 和六位日期，例如 `"202610"`。成功响应
`stage: hdd_search_received`，带 `recording_days` 或 `fragments`。
连接失败的响应只含固定阶段；可将响应贴回用于诊断。

`orvibo_smart_control.start_hdd_playback`：

```yaml
entity_id: camera.your_nvr_channel_1_hdd
date: "20261015090000"
```

该操作选择回放位置；打开对应 camera 后才开始建连。`playback_selected` 只表示
已选时间，不能证明收到录像。停止使用 `orvibo_smart_control.stop_hdd_playback`，
只需相同的 `entity_id`。

## 当前范围

- 支持 Meari XTS/p2p=2、默认 hostKey 鉴权的 NVR 普通硬盘录像；不含云存储或
  需要 record_id 的另一种录像模式。
- 每个通道有独立实时/回放实体；查询也建立独立短连接。录像机能否允许多路同时
  连接仍取决于设备。当前没有音频、暂停和倍速；重新选择时间会重新建连定位。
- 回放结束后不会自动从最初时间重播。请重新点击片段或选择新时间。
- 缩略图不启动硬盘播放；播放过程不自动保存视频文件。卸载或 HA 关闭会取消
  查询并清理协议、FFmpeg 和 HA Stream。
- 实时实体中的 `video_diagnostics` 提供固定阶段、连接次数、失败/超时计数和
  帧/字节统计；`streaming` 只说明已输出转码视频，不代替肉眼画面验证。

离线验证涵盖原生命令字节、隧道请求/回复序号、日历/片段解析、回放媒体类型及
结束标记、取消清理、实体切换和卡片交互。真实硬盘录像的查询结果、播放流畅度与
定位精度需要用户测试。
