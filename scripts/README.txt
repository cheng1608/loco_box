Loco Box 可选工具
================

当前桌面应用可以直接导入 .mid / .midi / 按键 TXT，支持多音轨与和弦。
正常演奏无需先转谱。使用说明见 docs/MUSIC.md，固件说明见 docs/PROTOCOL.md。
以下命令均在项目根目录执行；双击 run_midi2score_gui.bat 可打开转谱窗口。

一、串口与按键诊断
------------------
历史串口试验脚本已合并为 diagnose_arduino.py：

    .venv/Scripts/python.exe scripts/diagnose_arduino.py --list
    .venv/Scripts/python.exe scripts/diagnose_arduino.py --port COM6 --keys 1 Y
    .venv/Scripts/python.exe scripts/diagnose_arduino.py --music
    .venv/Scripts/python.exe scripts/diagnose_arduino.py --keys 1 --hold-ms 50 100 200

--list 仅列出设备，不连接或发送按键。默认端口 AUTO，默认发送 1、按住 50ms。
实测前先停止自动化功能并手动断开 Arduino 或关闭应用；工具不会强制抢占串口。
连接就绪后留 5 秒切到记事本/游戏，测试期间只连接一次，结束或 Ctrl+C 后释放设备。
--music 测试 B/F/G/H/J/K/T/Y/U 九键；字母应输出为小写，出现大写时检查固件。

二、MIDI 转成单声部按键 TXT
---------------------------
依赖 Mido，已包含在 requirements.txt 中，无需另装工具依赖。
GUI 会递归列出 scripts/music/ 中的 .mid / .midi，也可以浏览其他文件。

    .venv/Scripts/python.exe scripts/midi2score_gui.py
    .venv/Scripts/python.exe scripts/midi2score.py "歌曲.mid"
    .venv/Scripts/python.exe scripts/midi2score.py "歌曲.mid" -o "data/scores/歌曲.txt"
    .venv/Scripts/python.exe scripts/midi2score.py --dir "歌曲目录" --recursive --out-dir data/scores

单文件默认输出同目录、同名的 .txt；批量模式遇到损坏或空文件会报告并继续。
常用参数：

    --track auto|名称|索引     auto 自动选择旋律轨；索引从 0 开始；省略时合并全部轨道
    --root auto|0..11         默认自动识调；0=C，1=C#，依此类推
    --strategy degree        默认音级折叠；另有 nearest（就近）、smooth（平滑）
    --polyphony top          同时起音保留最高音；可选 bottom / loudest
    --hold-ms 50             按住时长，用于计算音后停顿
    --min-gap 100            丢弃间隔过短的音；0 表示不做此过滤
    --velocity-threshold 0   过滤低于指定力度的音；0 表示全部保留
    --tail-pause 0           最后一个音之后的停顿（ms）
    --keep-percussion       保留 GM 打击乐通道（默认跳过 channel 9）

该转换器会将同一时刻的和弦折叠成单音，并可过滤过密音符，适用于单声部 TXT。
直接 MIDI 播放则保留选中的全部音符，不能用转换器的默认删音规则理解主播放器。
全部参数可用 midi2score.py --help 查看。

输出每行是“按键 停顿毫秒”，例如：

    # 小星星
    T 450
    T 450
    U 450

仅使用 B/F/G/H/J/K/T/Y/U。音后停顿已扣除按住时长，下限为 0。
键位对应：L6→B，M3→F，M4→G，M5→H，M6→J，M7→K，H1→T，H2→Y，H3→U。
当前播放器不直接解析 H1/M3/L6 音名；旧音名文件可先用下述转换工具处理。

三、旧音名谱迁移
----------------
将 data/scores/ 中的音名转成键位，停顿保持不变；已转换的行不重复处理。

    .venv/Scripts/python.exe scripts/convert_scores_to_keys.py --dry-run
    .venv/Scripts/python.exe scripts/convert_scores_to_keys.py

不带 --dry-run 会原地写入，使用前按需备份自己的谱面。

四、本地手碟模拟器
------------------
    .venv/Scripts/python.exe -m pip install -r requirements-tools.txt
    .venv/Scripts/python.exe scripts/handpan_sim.py

聚焦模拟器后按九个键位发声，也可接收 Arduino HID 按键。pygame 只用于本工具。
音名与键位映射统一维护在 loco_box/handpan.py，主播放器和转谱器也共用其中的音高映射。
