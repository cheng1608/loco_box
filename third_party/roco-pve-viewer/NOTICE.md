# Roco PVE Viewer 来源与移植说明

本项目的精灵查看功能移植了 [Evenstar-tools/roco-pve-viewer](https://github.com/Evenstar-tools/roco-pve-viewer) 中的只读采集、传输解析、野生 PVE 状态投影及合成回放相关实现。采用的源码快照为 [`287d33587f200d0c55026a0a66227d5c8a6a1ed6`](https://github.com/Evenstar-tools/roco-pve-viewer/tree/287d33587f200d0c55026a0a66227d5c8a6a1ed6)，对应 v0.1.13 的原始性格修复。原作者的 MIT 许可保留在本目录 [LICENSE](LICENSE)。

在 Box 中，相关实现位于 `backend/pet_viewer/`，并通过 `backend/features/pet_viewer.py` 与 `backend/api/pet_viewer.py` 接入。移植适配 Python 3.9、FastAPI/事件总线、线程生命周期与本机历史；界面使用本项目的 Vue/Tauri 面板与悬浮窗。

协议描述和游戏配置独立于上述代码许可。本机验证所用的 `all.pb`、`gamedata.json` 来自 [v0.1.14 安装包](https://github.com/Evenstar-tools/roco-pve-viewer/releases/tag/v0.1.14)，通过静态解包取得。它们放在 Git 忽略的 `data/pet_viewer/resources/`，不作为本仓库的源码资源发布。第三方协议、游戏名称和配置的权利归各自权利人；原项目 MIT 许可不重新授权这些资源。来源记录见上游 [THIRD_PARTY.md](https://github.com/Evenstar-tools/roco-pve-viewer/blob/287d33587f200d0c55026a0a66227d5c8a6a1ed6/THIRD_PARTY.md)。

用于验证的资源标识：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `all.pb` | 1,225,100 | `8fe02b1a8ef8ee7bf191ef8ffc59d9d64077cf46c8c9af8591a3062241602825` |
| `gamedata.json` | 223,704 | `b021f08802c582d7d48fb627867d7c05053dcca83c148a92876e404966c01b55` |

实时采集通过用户本机安装的 [Npcap](https://npcap.com/) 进行，Npcap 驱动不随本仓库分发。Protobuf 与 PyCryptodome 为独立 Python 依赖，各自适用其许可。
