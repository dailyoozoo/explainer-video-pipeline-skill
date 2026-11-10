# 跨 agent 交接与可执行工具

## 环境与分工

本包后期工具需要 Python 3.11+、Pillow、PATH中的FFmpeg/ffprobe，以及支持libx264、AAC、libass的FFmpeg。安装Pillow：`python -m pip install -r requirements.txt`。项目提供许可合适的中文字体，`--font`用于测宽，`--font-name`与实际libass字体一致；跨系统用 `--font-dir`加载对应字体。

TTS、ASR、检索、取材、图表/前景设计、混音不是这些脚本自动完成的步骤。agent先按参考文档完成它们，再调用稳定后期工具。不要求安装特定外部skill，也不需要本人的本地路径、代理或私钥。示例没有真实素材与配音，不能直接当作已完成新闻。

Windows传递中文脚本时优先保存为UTF-8文件再执行；PowerShell管道若先把中文替换成问号，`python -X utf8`也无法恢复。遇到乱码先检查JSON/ASS的实际文本，再判断字体；本次合成验证曾由测试输入编码导致标题与字幕都变成问号，修正输入后中文正常。

## 项目保留结构

```text
video_jobs/<job>/
  README.md                    当前版本、阶段、待完成、执行命令
  research.md                  claim/source对应、日期与条件
  script-v01.md                用户批准版本与范围
  narration-say-v01.txt         纯朗读正文
  pronunciation.json           字形、读法、句ID、风险与确认范围
  sources-and-credits.md       来源、取段、许可与音乐署名
  assets/
    plates/                    完整画幅PNG或透明视频前景
    media/                     已验证的视频/摄影/截图
    audio/                     TTS原响应/原音、补录、干声、48kHz归一母带
    fonts/                     项目可使用的字体
  build/
    timeline-v01.json           最终人声驱动的字幕与镜头
    asr-words.json              模型、提示情况、词级时间与差异
    <output-stem>/              按输入指纹复用的逐镜渲染缓存
  output/
    news-v01.mp4               新版本文件名
    news-v01.manifest.json      成片、输入、脚本指纹与待验收状态
    subtitles/v01/             ASS/SRT及真实字体测宽结果
  preview/                     相对链接、逐镜跳转、上下文干声/成片试听
  review/v01/                  技术报告、实际目视、播放、真人听感
  history/                     仍被新版依赖的基线和失败审计
```

原始账号关注页由实际项目提供。不要把用户资产、凭据、原始API响应或大量第三方媒体默认推入公开仓库；本skill仓库发布的是方法、工具和结构示例。

## 时间轴契约

参考 [示例JSON](../examples/news-job/timeline.json)。`width`、`height`为正偶数，`fps`为正整数。`duration`和镜头start/end按fps量化，连续从0覆盖到duration，含关注页。

每镜有唯一安全字符 `id`、`start`、`end`、`kind`、`plate`；可提供 `frames`，必须等于区间帧数。静帧 `kind=image` 的plate为已完成全画幅图：背景、标题、简介、素材与图表均由agent预制，不包含口播字幕。需要图表动画时先渲染真实图表视频，作为下一类video输入。

视频镜 `kind=video` 还需要 `source`、非负 `offset`（秒）和 `box=[x,y,width,height]`（像素）。plate是画幅大小的RGBA图，在box保留透明视频窗口，其他前景由agent设计；素材等比适配并黑底补边，不自动裁切、不自动循环。source须覆盖完整使用范围，先按来源需要完成裁切。

plate/source相对job目录，不能越出job。字幕 `subtitles=[{id,start,end,text}]` 为已对齐的单行纯文字，按时间递增且无重叠；可在关注页留空。拒绝ASS控制字符与换行，避免重复字幕和标签注入。字幕不要求与镜头一一对应，时间可以更精确。

## 实际命令

以下从skill仓库根目录执行，将 `video_jobs/my-news`、字体与版本换成项目实际值；Windows也可使用这些正斜线相对路径。先完成已批准人声、独立对齐、前景/视频和含片尾的48kHz归一母带。

```text
python scripts/build_subtitles.py video_jobs/my-news/build/timeline-v01.json --font video_jobs/my-news/assets/fonts/ChineseSans.ttf --font-name "Chinese Sans" --out video_jobs/my-news/output/subtitles/v01
python scripts/render_video.py --job video_jobs/my-news --timeline video_jobs/my-news/build/timeline-v01.json --subtitles video_jobs/my-news/output/subtitles/v01/captions.ass --master video_jobs/my-news/assets/audio/master-v01.wav --font-dir video_jobs/my-news/assets/fonts --output video_jobs/my-news/output/news-v01.mp4
python scripts/inspect_video.py video_jobs/my-news/output/news-v01.mp4 --timeline video_jobs/my-news/build/timeline-v01.json --out video_jobs/my-news/review/v01
```

只改画面、声音和时长不变，可在render命令把 `--master ...` 换成 `--audio-video video_jobs/my-news/output/news-v01.mp4`，并输出 `news-v02.mp4`。该模式复制旧AAC；验收时仍核对流哈希、字幕指纹和新版画面。帧缓存只在输入/脚本/FFmpeg指纹与实际文件哈希一致时复用。输出已存在就停止，避免覆盖已交付版本。

字幕工具按真实字体测宽，低于最小字号仍太长就报错，agent应按真实词时轴拆语义字幕。它不负责听写、发音和时轴推断。ASS与SRT只写新目录，metrics绑定输入时轴与字体。

渲染工具只读取已归一、已补齐的母带；它不调音乐或再TTS。母带不足以覆盖关注页会报错，不用 `-shortest` 悄悄截尾。预制字体/图片应先检查，渲染出成片后不能仅凭工具结束就称验收通过。

检查器完整解码并实测编码响度，timeline模式抽取每镜中点、各切点前后及首尾。默认检查H.264/AAC、48kHz、-16～-13LUFS、≤-0.9dBTP；渠道目标不同用 `--min-lufs`、`--max-lufs`、`--max-true-peak`明确调整。没有timeline时仅8帧采样，不能当作逐镜目视。所有工具都不把抽帧生成或ASR当作真人通过。

## 本包验证范围（2026-11-10）

已用3秒、三镜、1080×1920/30fps的合成测试片验证静帧、透明前景视频、中文单行字幕和完整片尾；成片完整解码、规格与编码响度检查通过，三镜中点实际目视中文正常。画面改版重建一镜、复用两镜，复制AAC的流哈希一致。时轴空档、过宽字幕、片尾音频不足和输出覆盖均被拒绝。

测试使用合成音调，没有调用付费TTS；它验证后期工具，不证明配音自然、新闻事实或真实项目的完整验收。每个新项目仍需实际画面与声音审查。

## 新 agent 的续跑任务

给agent当前README、批准正文/范围、交付清单、真实素材位置、配置与有效报告。让它先核对最新成片和输入指纹，报告当前阶段，然后完成下一项缺失工作。缺凭据只阻碍对应外部调用，已有音频可用时先复用。

留存命令、工具版本、音色、模型、输入哈希与限制；声音确认绑定具体范围。下次修改只让受影响阶段失效，不能把历史“待验收”当作需要全片重做，也不能把旧版“已看”当新版已验收。
