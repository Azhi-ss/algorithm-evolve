# Algorithm Evolve

Algorithm Evolve is a Codex plugin for bounded algorithm search. It uses Monte Carlo Graph Search (MCGS), isolated candidate directories, objective evaluators, hard-constraint gates, and independent reviewer subagents to explore, score, and retain algorithm ideas.

It is especially useful for Kaggle and other deep-learning competitions, where an agent must iterate on data processing, feature engineering, model architecture, training strategy, validation, and ensemble ideas under a fixed compute or submission budget. The same workflow also applies to non-ML algorithms, optimization routines, prompts, configurations, and multi-step agent workflows.

The plugin includes two skills:

- `$algorithm-evolve` starts and runs a measurable search.
- `$algorithm-evolve-resume` reconstructs and continues an interrupted search from its local SQLite state.

## Installation

### Option A: Install the skills directly

This is the simplest installation and works in any Codex environment with local skill discovery.

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
git clone https://github.com/Azhi-ss/algorithm-evolve.git /tmp/algorithm-evolve
mkdir -p "$CODEX_HOME/skills"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve "$CODEX_HOME/skills/"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve-resume "$CODEX_HOME/skills/"
```

Start a new Codex thread after installation so the skills are discovered. Check that both directories exist:

```bash
ls "$CODEX_HOME/skills/algorithm-evolve" \
   "$CODEX_HOME/skills/algorithm-evolve-resume"
```

### Option B: Use it as a local plugin checkout

Keep the repository in a stable location when you want to update it with Git:

```bash
git clone https://github.com/Azhi-ss/algorithm-evolve.git ~/plugins/algorithm-evolve
```

The plugin manifest is at `.codex-plugin/plugin.json`, and the skills are under `skills/`. If your Codex installation uses a personal or team marketplace, add this checkout as the marketplace's `algorithm-evolve` source, then install `algorithm-evolve` from that marketplace. Follow your Codex version's `codex plugin marketplace` and `codex plugin add` commands for that configured marketplace.

To update a checkout:

```bash
git -C ~/plugins/algorithm-evolve pull --ff-only
```

If skills were copied into `$CODEX_HOME/skills`, repeat the two `cp -R` commands after pulling.

## Usage

### Start a search

Invoke the main skill with a concrete algorithm task, evaluator, and budget:

```text
$algorithm-evolve

Optimize this Kaggle image-classification solution. Compare the current baseline
with stronger augmentation, a different backbone, and a calibrated ensemble.
Use 10 iterations, a 30-minute evaluation budget, and maximize validation AUC.
Hard constraints: training must fit in the available GPU memory, inference must
finish within the submission limit, and every candidate must pass the smoke test.
Keep each candidate isolated and return the best candidate with evidence.
```

Before searching, the skill confirms a task contract in `.algorithm-evolve/<task-id>/task.json`. The contract should define:

- the goal and baseline;
- the evaluator, metric, or reviewer rubric;
- score direction (`maximize` or `minimize`);
- hard constraints;
- iteration, model-call, time, or compute budget.

For Kaggle, point the evaluator at a local validation split or a reproducible cross-validation command. Keep the competition test labels and any hidden evaluator data outside the generator subagents' context.

### Search lifecycle

The main skill coordinates the following loop:

1. Inspect the project, tests, benchmark, and current baseline.
2. Initialize a task-scoped SQLite database.
3. Add a baseline or first proposal as an isolated candidate.
4. Select a finalized node with UCT.
5. Ask generator subagents to propose, refine, repair, or fuse one bounded idea.
6. Evaluate the candidate with an execution subagent, or with three independent judgment reviewers.
7. Record constraint and score evidence, then finalize the node.
8. Backpropagate a coarse rollout reward and continue until the budget, target, stagnation, or another stop reason is reached.

The state tool never executes candidate code. Candidate execution stays in the host sandbox and follows the project's permissions.

### Resume an interrupted search

Use the resume skill in a new turn or after an interrupted run:

```text
$algorithm-evolve-resume
Continue the interrupted Kaggle model search in this workspace.
```

The skill reads `.algorithm-evolve/*/state.db` and reports the next required action. It can continue pending constraint checks, objective evaluations, reviewer calls, finalization, or the next MCGS expansion without reinitializing the task or duplicating recorded evaluations.

The command behind the skill is:

```bash
python3 skills/algorithm-evolve/scripts/search_state.py \
  --db .algorithm-evolve/<task-id>/state.db resume \
  --task-id <task-id>
```

State is local and queryable:

```text
.algorithm-evolve/<task-id>/
  task.json       # confirmed task contract
  state.db        # tasks, nodes, edges, and evaluations
  candidates/     # isolated candidate artifacts
  evidence/       # evaluator and reviewer evidence
```

### Inspect state manually

```bash
STATE_TOOL="skills/algorithm-evolve/scripts/search_state.py"
DB=".algorithm-evolve/<task-id>/state.db"

python3 "$STATE_TOOL" --db "$DB" status --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" resume --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" best --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" query --task-id <task-id> --text "augmentation"
```

All commands emit JSON. The database is the source of truth for recovery; conversation history is not required.

## Kaggle Guidance

- Use a fixed local validation split or deterministic cross-validation seed.
- Record the exact dataset version, preprocessing configuration, seed, hardware, and evaluator command as evidence.
- Treat GPU memory, runtime, package versions, and submission format as hard constraints.
- Compare every candidate with the same evaluation protocol; do not transfer scores between unrelated tasks.
- Keep generated candidates and notebooks isolated so a failed experiment cannot overwrite the source project.
- Use `fuse` only after independent branches have evidence that their mechanisms are compatible.
- Rerun the winning candidate from a clean copy before claiming an improvement.

## Repository Layout

```text
.codex-plugin/plugin.json
skills/
  algorithm-evolve/
    SKILL.md
    agents/openai.yaml
    references/protocol.md
    scripts/search_state.py
  algorithm-evolve-resume/
    SKILL.md
    agents/openai.yaml
```

## Development Checks

Run the state lifecycle tests and plugin validator from the repository root:

```bash
python3 -m unittest discover -s skills/algorithm-evolve/scripts -p 'test_*.py'
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve-resume
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

## License

Apache-2.0. See `.codex-plugin/plugin.json` for plugin metadata.

---

# 中文说明

Algorithm Evolve 是一个用于有界算法寻优的 Codex 插件。它使用蒙特卡洛图搜索（MCGS）、隔离的候选目录、目标评估器、硬约束门控和独立 reviewer subagent，持续探索、评分并保留算法思路。

它尤其适合 Kaggle 及其他深度学习竞赛：Agent 可以在固定的计算或提交预算内，迭代数据处理、特征工程、模型结构、训练策略、验证方式和 ensemble 方案。同一套流程也适用于非机器学习算法、优化例程、提示词、配置以及多步骤 Agent 工作流。

插件包含两个 skill：

- `$algorithm-evolve`：创建并运行可度量的算法搜索。
- `$algorithm-evolve-resume`：从本地 SQLite 状态恢复并继续被中断的搜索。

## 安装

### 方式 A：直接安装 skills

这是最简单的安装方式，适用于支持本地 skill 发现的 Codex 环境。

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
git clone https://github.com/Azhi-ss/algorithm-evolve.git /tmp/algorithm-evolve
mkdir -p "$CODEX_HOME/skills"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve "$CODEX_HOME/skills/"
cp -R /tmp/algorithm-evolve/skills/algorithm-evolve-resume "$CODEX_HOME/skills/"
```

安装后开启新的 Codex 对话，使其重新发现 skills。可以检查两个目录是否存在：

```bash
ls "$CODEX_HOME/skills/algorithm-evolve" \
   "$CODEX_HOME/skills/algorithm-evolve-resume"
```

### 方式 B：作为本地插件仓库使用

如果需要通过 Git 更新，建议将仓库放在稳定路径：

```bash
git clone https://github.com/Azhi-ss/algorithm-evolve.git ~/plugins/algorithm-evolve
```

插件清单位于 `.codex-plugin/plugin.json`，skills 位于 `skills/`。如果你的 Codex 使用 personal 或 team marketplace，请把这个 checkout 配置为 marketplace 中的 `algorithm-evolve` source，再从该 marketplace 安装插件。具体命令以当前 Codex 版本的 `codex plugin marketplace` 和 `codex plugin add` 帮助为准。

更新本地 checkout：

```bash
git -C ~/plugins/algorithm-evolve pull --ff-only
```

如果之前是复制到 `$CODEX_HOME/skills`，拉取更新后重新执行两个 `cp -R` 命令即可。

## 使用

### 开始一次搜索

用明确的算法任务、评估方式和预算调用主 skill：

```text
$algorithm-evolve

优化这个 Kaggle 图像分类方案。比较当前 baseline、更强的数据增强、
不同 backbone 和校准后的 ensemble。使用 10 次迭代和 30 分钟评估预算，
最大化验证集 AUC。硬约束：训练必须符合 GPU 显存限制，推理必须符合提交
时限，每个候选都必须通过 smoke test。隔离每个候选，并返回带证据的最佳方案。
```

搜索前，skill 会在 `.algorithm-evolve/<task-id>/task.json` 中确认任务契约，内容应包括：目标和 baseline、评估器/指标或 reviewer rubric、分数方向（`maximize` 或 `minimize`）、硬约束以及迭代、模型调用、时间或计算预算。

对于 Kaggle，建议使用本地 validation split 或可复现的 cross-validation 命令作为 evaluator。竞赛测试集标签和其他隐藏评估数据不应放进生成 subagent 的上下文。

### 搜索生命周期

主 skill 会协调以下循环：

1. 检查项目、测试、benchmark 和当前 baseline。
2. 初始化任务范围内的 SQLite 数据库。
3. 将 baseline 或第一个 proposal 加入隔离的候选目录。
4. 使用 UCT 选择已 finalize 的节点。
5. 让 generator subagent 提出、改进、修复或融合一个有界思路。
6. 使用 execution subagent 评估候选，或使用三个独立 reviewer 进行判断评分。
7. 记录约束和分数证据，然后 finalize 节点。
8. 回传粗粒度 rollout reward，直到达到预算、目标、停滞或其他停止原因。

状态工具不会执行候选代码。候选执行始终由宿主 sandbox 和项目权限控制。

### 恢复被中断的搜索

在新的对话中或任务中断后使用 resume skill：

```text
$algorithm-evolve-resume
继续当前工作区中被中断的 Kaggle 模型搜索。
```

它会读取 `.algorithm-evolve/*/state.db` 并报告下一步需要执行的动作，可以继续待处理的约束检查、目标评估、reviewer 调用、finalize 或下一轮 MCGS 扩展，不会重新初始化任务，也不会重复已经记录的评估。

底层命令：

```bash
python3 skills/algorithm-evolve/scripts/search_state.py \
  --db .algorithm-evolve/<task-id>/state.db resume \
  --task-id <task-id>
```

本地状态可查询：

```text
.algorithm-evolve/<task-id>/
  task.json       # 已确认的任务契约
  state.db        # tasks、nodes、edges 和 evaluations
  candidates/     # 隔离的候选产物
  evidence/       # evaluator 和 reviewer 证据
```

### 手动查看状态

```bash
STATE_TOOL="skills/algorithm-evolve/scripts/search_state.py"
DB=".algorithm-evolve/<task-id>/state.db"

python3 "$STATE_TOOL" --db "$DB" status --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" resume --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" best --task-id <task-id>
python3 "$STATE_TOOL" --db "$DB" query --task-id <task-id> --text "augmentation"
```

所有命令均输出 JSON。数据库是恢复流程的事实来源，不依赖对话历史。

## Kaggle 使用建议

- 使用固定的本地 validation split 或确定性的 cross-validation seed。
- 将数据集版本、预处理配置、随机种子、硬件和 evaluator 命令写入证据。
- 将 GPU 显存、运行时间、依赖版本和提交格式视为硬约束。
- 所有候选使用同一评估协议，不要在无关任务之间转移分数。
- 隔离生成的候选和 notebook，避免失败实验覆盖源项目。
- 只有在独立分支已有证据证明机制兼容后才使用 `fuse`。
- 声称改进前，从干净副本重新运行胜出候选。

## 仓库结构

```text
.codex-plugin/plugin.json
skills/
  algorithm-evolve/
    SKILL.md
    agents/openai.yaml
    references/protocol.md
    scripts/search_state.py
  algorithm-evolve-resume/
    SKILL.md
    agents/openai.yaml
```

## 开发检查

在仓库根目录运行状态生命周期测试和插件校验：

```bash
python3 -m unittest discover -s skills/algorithm-evolve/scripts -p 'test_*.py'
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve
python3 /path/to/skill-creator/scripts/quick_validate.py skills/algorithm-evolve-resume
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

## 许可证

Apache-2.0。插件元数据见 `.codex-plugin/plugin.json`。
