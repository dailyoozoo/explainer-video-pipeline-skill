# explainer-video-pipeline-skill

给不同AI agent使用的视频制作skill：核事实 → 定稿 → 整篇配音 → 词级字幕对齐 → 真实素材与图表 → 渲染混音 → 验收交付。支持科普、科技新闻、商业解说、周报、原项目续跑与局部修改。

2026-11-10更新纳入最近新闻短片、AI周报和长解说经验：修正静音切句与逐句拼接的旧方法，补充声音预检、单行字幕、可读图表、缓存复用和验收分层。

## 交给其他 agent

将本仓库作为完整skill目录安装到agent支持的位置，保留 `SKILL.md`、`references/`、`scripts/` 和 `examples/` 的相对关系。不支持自动加载时让agent直接读取 `SKILL.md`，按链接按需读参考文件，无须依赖这台电脑的绝对路径。

可以直接使用：

> 请读取本仓库的SKILL.md，按流程制作一条关于【主题】的【时长/平台】视频。采用“不写代码的PM”科技新闻风格：顶部章节标题和简洁介绍、全屏摄影背景、一处单行口播字幕、真实来源素材、手机可读图表、原始关注页。先核对事实并提交可朗读稿；沿用我已经确认的内容与授权。整篇配音后按真实人声对齐，不按静音切句。交付MP4、预览、来源署名、可续跑项目与验收记录，未实际听过的声音明确标为待试听。

原始关注页、凭据、真实素材和批准稿件由实际项目提供，本仓库不包含个人密钥或第三方原始媒体。其他账号替换对应素材与约定即可。

## 内容和工具

- [SKILL.md](SKILL.md)：制作、续跑与修改入口。
- [实战经验](references/production-lessons.md)：TTS读入制作说明、型号读错、声音返工、快剪周报和图表改版。
- [跨 agent 交接](references/agent-handoff.md)：输入格式、依赖和实际命令。
- [新闻视觉](references/news-style.md)、[音频对齐](references/audio-and-alignment.md)、[事实与素材](references/research-and-assets.md)、[验收与修改](references/quality-and-revisions.md)。
- `scripts/build_subtitles.py`：已核对时轴生成单行ASS/SRT，按真实字体检查宽度。
- `scripts/render_video.py`：静帧或透明前景与视频合成，按帧渲染、复用缓存、烘焙字幕、挂载已归一完整母带。
- `scripts/inspect_video.py`：完整解码、规格、响度、逐镜中点及边界抽帧，不替代主观验收。
- [示例输入](examples/news-job/timeline.json)：三镜结构示例，替换为真实素材和已对齐时间。

工具覆盖稳定后期步骤；事实研究、TTS、ASR、素材获取、图表设计和混音由agent按环境完成，不声称任意主题都能自动成片。首次使用先验证短段，执行细节见交接指南。
