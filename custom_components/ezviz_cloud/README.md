# EZVIZ Cloud (CN) for Home Assistant

把 `ezviz_local` 里那套脚本做成 HA 原生集成：**镜头遮蔽开关 + 云台方向按键**，
直接调用萤石国内云（`api.ys7.com`），不依赖 HA 里那个被 10026 卡死的 `ezviz` 集成。

## 实体

| 实体 | 说明 |
|---|---|
| `switch.ezviz_<序列号>_jing_tou_zhe_bi` | 镜头遮蔽开/关 |
| `button.ezviz_<序列号>_yun_tai_shang` 等 4 个 | 云台上/下/左/右，按一次转一下 |
| `number.ezviz_<序列号>_yun_tai_shi_chang` | 转动时长 50–5000ms（默认 300） |
| `number.ezviz_<序列号>_yun_tai_su_du` | 速度 1–10（默认 5） |

实体名随实际 slug 变化，以开发者工具里看到的为准。

## 安装

把 `custom_components/ezviz_cloud/` 整个目录拷到 HA 的 `/config/custom_components/`，
重启 HA，然后在「设置 → 设备与服务 → 添加集成」里搜 **EZVIZ Cloud (CN)**。

配置时需要：

- 账号：`mdskiw`（或手机号）
- 密码：萤石 App 密码
- 序列号：`<序列号>`
- token：可选。把 `ezviz_local/token.json` 的内容整段粘进去，就**跳过短信验证**；
  留空则首次配置会发短信验证码，在下一步填。

## 自动化示例

```yaml
automation:
  - alias: 回家遮蔽
    trigger:
      - platform: state
        entity_id: person.zhou_jian
        to: home
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.ezviz_<序列号>_jing_tou_zhe_bi

  - alias: 离家解除遮蔽
    trigger:
      - platform: state
        entity_id: person.zhou_jian
        from: home
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.ezviz_<序列号>_jing_tou_zhe_bi
```

云台按键可以直接挂到仪表盘，或用服务：

```yaml
service: ezviz_cloud.ptz
data:
  direction: left
  ms: 300
  speed: 5
```

## 说明

- 遮蔽走 `PUT /v3/devices/{serial}/switch`（type 7，channel 0），云端回显有 5–10 秒延迟，
  开关做了乐观更新并延迟 6 秒校准。
- 云台走 `PUT /v3/devices/{serial}/ptzControl`（START → 等 ms → STOP，STOP 失败会重试）。
- 会话存在 config entry 里，脚本里那套 token 刷新逻辑保留；登录失败会自动重登一次。
- 不依赖 paho / pycryptodome / xmltodict（那几个 import 已改成可选）。

## 卸载

删除 `/config/custom_components/ezviz_cloud/`，重启 HA。
