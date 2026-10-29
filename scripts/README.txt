一键

.venv/Scripts/python.exe scripts/midi2score.py "scripts/music/歌名.mid" --track auto -o "data/scores/歌名.txt"


洛克王国 9 音手碟简谱转换工具（midi2score）
================================================

一句话：把 .mid 文件转成 data/scores/ 里能直接演奏的简谱 .txt。

------------------------------------------------
一、依赖
------------------------------------------------
需要 mido（MIDI 解析库），可选工具依赖在 requirements-tools.txt：

    .venv/Scripts/python.exe -m pip install -r requirements-tools.txt

------------------------------------------------
二、快速开始
------------------------------------------------
单文件转换（输出到输入同目录的同名 .txt）：

    .venv/Scripts/python.exe scripts/midi2score.py 歌曲.mid

直接写进歌单目录：

    .venv/Scripts/python.exe scripts/midi2score.py 歌曲.mid -o data/scores/歌曲.txt

批量转换目录下所有 .mid：

    .venv/Scripts/python.exe scripts/midi2score.py --dir 歌曲目录

批量 + 递归子目录 + 统一输出目录：

    .venv/Scripts/python.exe scripts/midi2score.py --dir 歌曲目录 --recursive --out-dir data/scores

------------------------------------------------
三、命令行参数
------------------------------------------------
单文件模式：
    midi                  输入 .mid 文件
    -o, --output          输出 .txt 路径（默认与输入同目录同名）

批量模式：
    --dir 目录            转换目录下所有 .mid
    --out-dir 目录        输出目录（默认每个 .txt 写到各自 .mid 旁边）
    --recursive           递归子目录

转换选项：
    --track auto|名称|索引  只转换指定轨道。auto=自动找旋律轨（推荐）；
                          纯数字=轨道索引(0 起)，否则按音轨名匹配（如 --track MELODY）
    --root auto|0..11     主音。auto=自动检测并转调到 C 大调（默认）；
                          0=不转调，只把升降音量化到自然音；1..11 手动指定
    --polyphony top       和弦折叠策略：top=保最高音（默认）/ bottom=保最低音 / loudest=保力度最大
    --strategy degree     音高映射：degree=音级折叠（默认，保音准，do/re 跳八度）；nearest=纯就近
                          （保连贯）；smooth=平滑（就近限全音≤2 半音，超了回退音级）
    --hold-ms 50          每个音固定按住毫秒，算停顿时扣掉（对齐 music.py 的 HOLD_MS）
    --min-gap 100         丢弃起点间隔小于此毫秒的贴脸音（默认 100；0=不丢）
    --velocity-threshold 0 力度低于此值的音当幽灵音丢弃（0=保留全部）
    --tail-pause 0        最后一个音之后的停顿毫秒
    --keep-percussion     保留打击乐轨（默认跳过 channel 9）

------------------------------------------------
四、输出格式
------------------------------------------------
每行一个音：`音符 停顿毫秒`，与 data/scores/*.txt 一致，可被 music.py 的
parse_score 直接解析。例如：

    # 小星星
    # 由 MIDI 自动转换
    H1 450
    H1 450
    H3 450
    ...

音符只可能是这 9 个之一：

    低音区：L6
    中音区：M3 M4 M5 M6 M7
    高音区：H1 H2 H3

------------------------------------------------
五、转换原理（简要）
------------------------------------------------
MIDI →(tempo换算) 音符起点(ms) →(和弦折叠) 单音序列 →(音级折叠) 9 音
     →(间隔−50ms) 停顿

1. 只取 note_on（velocity>0），丢弃 note_off —— 手碟「按一下就是一下」，音长无意义。
2. 同一时刻的和弦按 --polyphony 折叠成单音（手碟是单旋律）。
3. 音高归约：检测主调，把任意音映射到手碟 9 音之一（转调到 C 大调 + 量化升降音）。
4. 停顿 = 相邻起点间隔 − 50ms（50ms 是固定按住时长），下限钳到 0。

------------------------------------------------
六、常见问题
------------------------------------------------
Q: 下载的 MIDI 转出来一大片音、很吵怎么办？
A: 那是整编（多乐器）MIDI，把伴奏/贝斯/鼓全混进来了。加 --track auto 自动选旋律轨
   （或 --track MELODY 手动指定）。想看有哪些轨道，先用任意 MIDI 编辑器打开，或：
       .venv/Scripts/python.exe -c "import mido;m=mido.MidiFile('歌曲.mid');[print(i,t.name) for i,t in enumerate(m.tracks)]"

Q: 为什么低音 C 会变成 H1（高音 1）？
A: 手碟 9 音里 do 只有一个，就是高音 1（H1）。低八度的 do 只能落到它，
   这是乐器本身的限制。

Q: 为什么 re（D）也老跳到 H2？
A: 同理，手碟缺中音 2（D4），re 只有高音 2（H2），中音 re 会被抬上去。
   想就近把 re 落到 mi（M3）不跳八度，用 --strategy smooth；想纯就近（do 也
   一起改）用 --strategy nearest。

Q: 和弦 / 伴奏音怎么办？
A: 同一时刻只留一个音（默认最高音=旋律）。想留低音改 --polyphony bottom。

Q: 打击乐（鼓）轨会不会被转进来？
A: 默认跳过 GM 打击乐通道（channel 9）。要保留加 --keep-percussion。

Q: 转换出来节奏感觉偏快/偏慢？
A: 停顿已扣掉 50ms 按住时长，理论上与 MIDI 原节奏一致。想整体拉长/压缩
   节奏目前需要改谱，或用 --min-gap 丢弃过快的装饰音。

Q: 单个文件损坏会不会中断批量？
A: 不会。批量模式跳过损坏/空文件并打印原因，其余照常转换。
