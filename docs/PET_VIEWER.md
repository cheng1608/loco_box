# 精灵查看

「精灵查看」读取野生交互 PVE 的原始性格、属性增减，以及已下发的声音、体型、血脉和异色信息。功能可独立于 Arduino 运行，监听期间仍可进行区域框选。

## 使用步骤

1. 按下文准备资源，打开 Box 的「精灵查看」面板，确认资源已就绪。
2. 实时监听需要安装 [Npcap 官方驱动](https://npcap.com/#download)。缺少驱动时面板会提供官网入口。
3. 网卡默认自动选择，也可刷新列表后指定正在连接游戏的网卡。
4. 点击「开始监听」，再从登录界面进入游戏世界，然后遭遇野生精灵。解析需要捕获新连接的握手，已登录时可保持监听并重新登录。
5. 属性下发后会在面板显示。打开悬浮窗可在游戏上方查看，关闭悬浮窗会继续监听。
6. 点击「停止监听」释放网卡句柄并清空当前结果。正常战斗结束时，面板会保留本场结果并标记结束。

Npcap 若在安装时设置为仅管理员可访问，实时监听需要匹配的权限。应用不会自动安装驱动或提权。

「示例回放」用合成握手和战斗消息检查解析与显示。导入资源后即可使用，无需安装 Npcap 或启动游戏。面板会标记「示例回放」，结果不会进入真实遭遇历史。

## 资源准备与更新

导入器将两份外部文件及清单放在 `data/pet_viewer/resources/`。

| 文件 | 用途 |
|---|---|
| `all.pb` | Protobuf `FileDescriptorSet`，包含战斗消息、精灵字段及相关类型 |
| `gamedata.json` | `species`、`natures`、`medals` 配置字典 |
| `manifest.json` | 导入器生成的版本、来源、大小及 SHA-256 记录 |

游戏资源不随 Git 源码分发。请从有权使用的本机程序资源中取得文件，或从 [Roco PVE Viewer v0.1.14 安装包](https://github.com/Evenstar-tools/roco-pve-viewer/releases/tag/v0.1.14) 提取其配套资源。安装目录通常为 `%LOCALAPPDATA%\Programs\RocoPveViewer`，资源位于 `_internal\assets`；安装包本身不是导入器的输入。来源与许可说明见 [third_party/roco-pve-viewer/NOTICE.md](../third_party/roco-pve-viewer/NOTICE.md)。

按照 [从源码运行](../README.md#从源码运行) 创建 Python 环境并安装依赖。停止精灵监听后，在项目根目录执行下列任一导入命令。

```powershell
.\.venv\Scripts\python.exe scripts/import_pet_resources.py --source "C:\路径\assets"
# 也可以传入已安装程序的目录，工具只在所选目录内寻找完整资源对
.\.venv\Scripts\python.exe scripts/import_pet_resources.py --source "$env:LOCALAPPDATA\Programs\RocoPveViewer"
```

工具先将两份文件复制到暂存目录，使用同一个后端解析器检查协议和配置，再生成 manifest 并替换整个资源目录。新资源验证失败时不改动旧资源；替换失败时回滚；成功替换后的旧资源保留为同级 `resources.backup-*` 目录。历史数据库和其他 Box 配置不受影响。使用 `--destination` 可指定验证目标目录，`--version`、`--source-release` 可补充其他版本的来源说明；已验证的 v0.1.14 文件按哈希自动识别。工具不会下载或执行安装程序。

导入后重新开始监听加载新资源。仅文件名相同不足以证明兼容：曾核对的上游旧版 `all.pb` 缺少新版破盾、变身描述，不能直接替换当前解析器所需资源。协议缺失、文件损坏或 manifest 校验失败会显示资源错误，功能不使用猜测值。

## 性格与状态规则

入战消息中的原始性格路径为：

```text
init_info.enemy_team[].pets[].battle_common_pet_info.nature
```

`nature` 编号从 `gamedata.json.natures` 查出中文名称和原始属性增减。`changed_nature_pos_attr_type`、`changed_nature_neg_attr_type` 与 `nature_attr_change_way` 单独显示在性格详情，不覆盖主性格。字段未下发、未知编号或占位形态保持未知。

解析处理入战（4886）、回合开始（4890）、战斗演出（4900）和结束（4908）消息。回合快照、同步、数据更新、破盾、变身与捕获结算可以补齐属性；形态替换会清除旧形态值。所有后续更新须匹配当前战斗及已登记的敌方。

收到报文后，后端先解析战斗模式、战斗编号和玩家目标标记，仅对已确认 `battle_mode == 1` 的野生交互 PVE 完整解码属性。普通 PVE、玩家对战、玩家目标和未知模式均会阻断。后续消息出现玩家对战标记时，清空当前结果并撤销同场已保存的历史。

## 本机记录与接口

网卡设置保存在 `data/settings.json` 的 `features.pet_viewer.adapter`，空字符串表示自动。真实遭遇历史保存在 `data/pet_viewer/history.sqlite3`，记录展示结果，不保存原始报文、会话密钥或账号信息。相同遭遇的后续属性更新到原记录；停止监听保留历史，示例回放不写历史。

后端目录 `backend/pet_viewer/` 负责采集、解析、状态与历史，Feature 负责启停生命周期；实时状态通过 `pet_viewer.state` 事件推送。Vue 主面板与 `pet_overlay` 悬浮窗使用同一个后端状态。详细端点见 [API.md](API.md)。

## 验证范围

- 本机使用 Npcap 1.90 验证了网卡枚举、监听启停和一次真实野生遭遇。成功读取恶魔狼的原始性格「沉默」（生命↑、物攻↓），并写入本机历史。
- 回归测试使用合成报文覆盖 TCP 重组、协议解码、性格映射、属性缺失、玩家对战阻断和同场历史撤销。玩家对战阻断的验证范围为离线测试。
