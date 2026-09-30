# distill-my-session

「轨迹进，词表出。」把 [Vocabulary-First](https://github.com/justinatusa/vocabulary-first)
反过来用在自己的 agent 会话上：从轨迹中提取有名字、可复用的工作方法。

这个 Agent Skill 读取 Claude Code、Codex、Grok Build 的 session，整理 prompt 结构、
关键时序、并发与 harness 用法。输出解释**怎么做**，不披露公司工作或未发表研究的实质内容。

## 安装与调用

```bash
git clone https://github.com/chenghaoYang/distill-my-session ~/developer/distill-my-session
mkdir -p ~/.claude/skills ~/.agents/skills
ln -s ~/developer/distill-my-session ~/.claude/skills/distill-my-session
ln -s ~/developer/distill-my-session ~/.agents/skills/distill-my-session
```

两条软链分别用于 Claude Code 与 Codex 等支持 Agent Skills 的环境，按需选择；已有同名安装时先检查它，勿覆盖。
调用 `/distill-my-session 7d`，或说「蒸馏我最近一周的 session」。完整输入与执行合同见 [SKILL.md](SKILL.md)。

## 产物与边界

公开包包含核心命题、词表 `lexicon.md`、关键时序 `trajectories.md`，以及并发、harness 和 prompt 模式。
每个论断带 `[S03·T12]` 这样的证据锚点；无证据的内容标为推测或删除。
固定字段见 [输出规范](references/output-schema.md)。

工作目录放在仓库外。先确认范围和消密规则，再进行确定性脱敏、语义抽象、leakcheck 与独立 red-team 审查。
自动检查通过不等于安全；原始/摘要轨迹与 `private/` 不发布，只有经操作者明确批准的 `public/` 才能对外分享。
详细规则和检查退出状态见 [消密合同](references/declassify.md)。

## 样例

[operator-playbook](examples/operator-playbook/) 是作者 7 天、65 个交互 session 的已消密学习包，
核心命题是「目标写进文件，心跳交给 harness，人只做裁决」。样例中的统计与逐条证据保留在原文：

- 同时活跃 session：峰值 6，均值 1.5
- 同时活跃 agent（含 subagent）：峰值 15，均值 3.7
- 人发起轮次 : harness 发起轮次 = 417 : 659

## 按需阅读

- [SKILL.md](SKILL.md)：输入、执行顺序、确认与交付
- [lens](references/lens.md)：Vocabulary-First 术语；[method](references/method.md)：三遍读法、倒推与反事实
- [declassify](references/declassify.md)：消密；[output-schema](references/output-schema.md)：卡片与公开包字段
- [team](references/team.md)：reader 与 red-team 派活 prompt
- [distill.py](scripts/distill.py)：scan / digest / timeline / suggest / leakcheck（Python 标准库）；各子命令用 `--help` 查参数
- [sources.py](scripts/sources.py) · [redact.py](scripts/redact.py)：轨迹解析与第一层消密

## 许可

[MIT](LICENSE)。读法借用 [Vocabulary-First](https://github.com/justinatusa/vocabulary-first)（MIT）。
