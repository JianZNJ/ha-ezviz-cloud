# EZVIZ Cloud (CN) for Home Assistant

给萤石（EZVIZ）**国内账号**做的轻量 Home Assistant 集成：**镜头遮蔽开关** + **云台方向控制**。

它直接走萤石国内云 `api.ys7.com`（萤石 App 自己用的那套账号协议），不需要在萤石开放平台申请 appKey，
也就不受「设备数量超出个人版限制（错误码 10026）」的影响——那正是 HA 官方/第三方 `ezviz` 集成在个人版账号上
卡死、实体全部变 unavailable 的常见原因。

- 只控制，不取流：视频继续走你自己的 Frigate / go2rtc / RTSP，不占云带宽
- 依赖极少：只要 `requests`（HA 自带），MQTT / pycryptodome / xmltodict 都是可选导入
- 账号密码登录支持短信验证码二次验证；也可以直接粘贴 token 跳过短信

## 功能

| 能力 | 说明 |
|---|---|
| 镜头遮蔽 | `switch`，开 = 设备物理遮挡镜头（不是遮 UI 图层） |
| 云台方向 | 4 个 `button`（上/下/左/右），或服务调用带时长/速度 |
| 转动参数 | 2 个 `number`：单次转动时长 50–5000 ms、速度 1–10 |
| 状态读取 | 遮蔽状态从云端 `switch type 7` 读回，不是纯乐观状态（带 6 秒校准） |
| 会话保持 | 保存 session/rf_session，用 `token/refresh` 续期，不反复触发短信 |
| 故障可见 | 连续 3 次拉取失败发**持久通知**（侧边栏可见），恢复自动消失 |
| 自愈 | 萤石 `/v3/apigateway/login` 续期接口返回 500 时，用保存的密码重新登录（限 1 次/6 小时，遇短信验证立即停止），可在集成「选项」里关闭 |

## 变更

- **v1.0.4**：故障持久通知；续期接口 500 时受限密码登录自愈（选项 `auto_relogin` 默认开）；续期返回空 token 时回滚，避免把有效会话写坏；主客户端不再携带密码
- **v1.0.3**：续期失败保留现有会话；token 轮换自动持久化
- **v1.0.1**：后台绝不触发密码登录，新增 reauth / MFA 流程

## 安装

### HACS（推荐）

1. HACS → 右上角 ⋮ → **自定义存储库**
2. 仓库填 `https://github.com/JianZNJ/ha-ezviz-cloud`，类别选 **集成**
3. 搜「EZVIZ Cloud (CN)」下载，重启 Home Assistant

### 手动

把 `custom_components/ezviz_cloud/` 整个目录拷到 HA 的 `/config/custom_components/`，重启 HA。

## 配置

设置 → 设备与服务 → 添加集成 → 搜 **EZVIZ Cloud (CN)**。

| 字段 | 说明 |
|---|---|
| 账号 | 萤石 App 的登录名（手机号或用户名） |
| 密码 | 萤石 App 密码（明文填，存进 config entry） |
| 序列号 | 设备序列号，如 `C12345678`，在萤石 App 设备详情里能看到 |
| token | 可选。留空走账号密码登录；粘贴一段有效的 token JSON 则直接校验设备信息、不发短信 |

### 关于短信验证码

密码登录时，如果萤石账号开了短信验证，集成会自动切到**第二步**：

```
[账号 / 密码 / 序列号]  →  萤石判断需要二次验证  →  [短信验证码]
```

第一步填的是**账号密码**，第二步填的才是**短信里收到的 6 位验证码**，两者不是一回事。
验证码发送过于频繁时（萤石返回 1041），第二步会提示「短信发送失败（多为发送过于频繁）」，
等一分钟退回第一步重试即可。

## 实体

以序列号 `C12345678` 为例（实际 entity_id 依你的设备 slug 而定）：

| 实体 | 类型 | 作用 |
|---|---|---|
| `switch.ezviz_c12345678_jing_tou_zhe_bi` | switch | 镜头遮蔽 |
| `button.ezviz_c12345678_yun_tai_shang` | button | 云台上 |
| `button.ezviz_c12345678_yun_tai_xia` | button | 云台下 |
| `button.ezviz_c12345678_yun_tai_zuo` | button | 云台左 |
| `button.ezviz_c12345678_yun_tai_you` | button | 云台右 |
| `number.ezviz_c12345678_yun_tai_shi_chang` | number | 单次转动时长（ms） |
| `number.ezviz_c12345678_yun_tai_su_du` | number | 转动速度（1–10） |

## 服务：`ezviz_cloud.ptz`

适合脚本、自动化、语音助手调用。

```yaml
service: ezviz_cloud.ptz
data:
  direction: right   # up / down / left / right，必须是**小写**
  ms: 900            # 转动时长，默认 500
  speed: 5           # 速度 1–10，默认 5
```

> `direction` 用的是 `vol.In(["up","down","left","right"])`，传大写会报 400。

## 自动化示例

### 回家遮蔽 / 离家解除

```yaml
alias: 回家遮蔽 / 离家解除（EZVIZ）
trigger:
  - platform: state
    entity_id: person.zhou_jian
    to: home
    id: home
  - platform: state
    entity_id: person.zhou_jian
    to: not_home
    id: away
action:
  - choose:
      - conditions:
          - condition: trigger
            id: home
        sequence:
          - service: switch.turn_on
            target:
              entity_id: switch.ezviz_c12345678_jing_tou_zhe_bi
      - conditions:
          - condition: trigger
            id: away
        sequence:
          - service: switch.turn_off
            target:
              entity_id: switch.ezviz_c12345678_jing_tou_zhe_bi
mode: single
```

### 打开遮蔽时顺手把镜头转向墙角

```yaml
- service: ezviz_cloud.ptz
  data:
    direction: left
    ms: 1200
```

## 工作原理

| 动作 | 萤石云接口 |
|---|---|
| 登录 | `POST /v3/users/login/v3`（`appId: ys7`、VideoGo UA、密码 MD5） |
| 续期 | `PUT /v3/users/token/refresh` |
| 遮蔽 | `PUT /v3/devices/{serial}/switch`，`switchType: 7` |
| 云台 | `PUT /v3/devices/{serial}/ptzControl`，`{command: LEFT, action: START\|STOP, channelNo, speed}` |
| 读状态 | `POST /v3/devices/infos` 里的 `SWITCH[type=7]` |

云台是「START 转动 + 延时 + STOP」的模式，所以一次按键转多大角度由**时长**决定，由**速度**决定快慢。

## 已知限制

- 云控有 0.3–1 秒延迟；转完立刻截图可能还是旧画面
- 没有预置位（收藏点）封装；要定点只能靠 `ms` 粗调，或在 HA 里存「转多少毫秒」的组合
- 一个配置条目绑定一台设备（以序列号去重，重复添加会报「该设备已经配置过了」）
- 只测过 C6CN 系列 + HA 2026.11.x；其他型号/版本可能字段不同，欢迎提 issue
- 账号密码会以明文存在 HA 的 config entry 里（HA 的 .storage 常规行为），介意的话用 token 方式并留意备份

## 安全与隐私

- 仓库里不含任何账号、密码、令牌、设备序列号
- 集成只和 `api.ys7.com` 通信，不向第三方发数据
- 设备视频流不经过本集成

## 致谢

- [pyezviz](https://github.com/RenierMoorlag/pyezviz) — 萤石云客户端基础
- [liuzexier/ezviz_cn](https://github.com/liuzexier/ezviz_cn) — 国内账号协议分支，本集成内嵌了它的 `pyezvizapi`
- 内嵌副本按 Apache-2.0 保留，详见 [NOTICE.txt](NOTICE.txt)

## License

Apache License 2.0，见 [LICENSE](LICENSE)。
