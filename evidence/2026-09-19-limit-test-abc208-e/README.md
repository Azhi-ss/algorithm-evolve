# ABC208 E Digit Products — 极限测评证据包

本地闸通过：官方 3 样例 + 对抗集全绿；错基线（积超 K 就丢状态）被证伪。**不是** AtCoder AC。`submit=0`。

STATE_DIR **新建**：`.algorithm-evolve/abc208-e-limit-fixed`（未复用旧 ABC run）。`/workspace/company` 不在本机；循环只用本仓 `skills/algorithm-evolve/scripts/search_state.py`。产品文件（evoK / gates / runGoldenPath / Broker / `search_state.py` / `skills/`）**未改**。

## Tip / env / models（无密钥）

| 项 | 值 |
|---|---|
| Repo | `github.com/Azhi-ss/algorithm-evolve` |
| Tip (main) | `1b68978aa0206871f80a4e3f9bd12e9ef9fbfe5b`（PW-1 已在） |
| Evidence branch | `cursor/abc208-e-limit-fixed-79b2` |
| Cloud run | `bc-71cbf5ad-d8ab-50d5-aa4e-b0b8cecf79b2` |
| Env public id | `77f55ea9-aab6-11f1-b532-320a589b8025` |
| Boot build | `bld-20260917-20bd9f86-2cef-4e5d-89aa-5574dd31a568` |
| Python | 3.12.3 |
| STATE_DIR | `.algorithm-evolve/abc208-e-limit-fixed` |
| Selection | 产品默认 **`fixed_uct` only**。每次 live `select` payload keys = `{selected, uct}`。无 `--selection-id`，无 Progressive，`#40` off。Elite ≠ promotion |
| submit | **0** |
| NEWAPI host | `newapi.ai-modeling.top`（base 已含 `/v1`） |
| Chat helper | `curl` + User-Agent（躲 Cloudflare 1010） |
| Model rotate (lead) | `gemini-3.8-flash` → `gemini-3.7-flash-high` → `gemini-flash-latest` |
| Optional（未用） | `gemini-3.6-flash-high`, `gemini-pro-agent` |
| Forbidden sole LONG | `coding-deepseek-*`、`deepseek-v4-*-ga`、GPT* — **从未调用** |
| Gateway remaps | 请求 `gemini-3.7-flash-high` → 响应 `gemini-3.7-flash`；请求 `gemini-flash-latest` → 响应 `gemini-3.8-flash` |
| Live LLM nodes | 8（`model_calls=8`）；墙钟 **114.5s** |
| Tree size | 10 finalized（1 baseline + 1 CONTROL + 8 Gemini） |
| Best | `n-17f05b3c1944` score **8.0 / 8** |
| Company repo | 不在 |

预循环烟测：`GET /models` HTTP 200（34 ids）。短 `gemini-3.8-flash` ping HTTP 200，content `PONG`。

对抗期望交叉核：`N≤1010` 暴力 ∩ 参考数位 DP（`leading_zero` + 溢出桶 `K+1`）。官方 3 与题面一致。

## parent_id 序列

单脊。`select` 始终默认 UCT；第一次扩展选中 CONTROL（reward 1.0 vs baseline 0.5）。

```
n-0259ed57fd78  baseline     score 0  reward 0.5  baseline-nolead
 └─ n-7e5e8f802973  propose  score 4  reward 1.0  control-discard-overflow
     └─ n-17f05b3c1944  refine   score 8  reward 1.0  refine-01-gemini   ★ first all-green / best
         └─ n-8aef0af305cc  propose score 8  reward 0.5  propose-02-gemini
             └─ n-c429804cf75b  propose score 8  reward 0.5  propose-03-gemini
                 └─ n-7028cf230c1c  propose score 8  reward 0.5  propose-04-gemini
                     └─ n-bee4db62b6c3  propose score 8  reward 0.5  propose-05-gemini
                         └─ n-50a64e7c0c41  propose score 8  reward 0.5  propose-06-gemini
                             └─ n-602b555d1be6  propose score 8  reward 0.5  propose-07-gemini
                                 └─ n-65d16821086a  propose score 8  reward 0.5  propose-08-gemini
```

| step | action | parent_id | child_id | UCT | requested model |
|---|---|---|---|---|---|
| seed | baseline | — | `n-0259ed57fd78` | — | scripted |
| seed | propose | `n-0259ed57fd78` | `n-7e5e8f802973` | — | scripted CONTROL |
| 1 | refine | `n-7e5e8f802973` | `n-17f05b3c1944` | 2.482 | `gemini-3.8-flash` |
| 2 | propose | `n-17f05b3c1944` | `n-8aef0af305cc` | 2.665 | `gemini-3.7-flash-high` |
| 3 | propose | `n-8aef0af305cc` | `n-c429804cf75b` | 2.294 | `gemini-flash-latest` |
| 4 | propose | `n-c429804cf75b` | `n-7028cf230c1c` | 2.393 | `gemini-3.8-flash` |
| 5 | propose | `n-7028cf230c1c` | `n-bee4db62b6c3` | 2.473 | `gemini-3.7-flash-high` |
| 6 | propose | `n-bee4db62b6c3` | `n-50a64e7c0c41` | 2.539 | `gemini-flash-latest` |
| 7 | propose | `n-50a64e7c0c41` | `n-602b555d1be6` | 2.596 | `gemini-3.8-flash` |
| 8 | propose | `n-602b555d1be6` | `n-65d16821086a` | 2.646 | `gemini-3.7-flash-high` |

循环后默认 `select` 仍只返回 `{selected, uct}`。

## Propose summaries

| node | leading_zero | keep overflow→0 | idea |
|---|---|---|---|
| baseline | **false** | n/a（前导零已乘进积） | 无数位 leading 标志；前导 0 乘进积 |
| CONTROL | true | **false** | 积 >K 直接 `continue` 丢状态 |
| refine-01 ★ | true | **true** | `(tight, lead, prod)`，超 K 封顶 `K+1`，后遇 0 回到 0 |
| propose-02 | true | true | 按层频率表 `(tight, lead, prod)` |
| propose-03 | true | true | 素因子指数 `(e2,e3,e5,e7)` + 零积/溢出桶 |
| propose-04 | true | true | 下标 + 积封顶 `K+1` 的 memo DFS |
| propose-05 | true | true | 同 memo；非前导 0 把积重置为 0 |
| propose-06 | true | true | `(digit_index, product)` 溢出可再转 0 |
| propose-07 | true | true | 迭代计数：≤K 的积 + 溢出态 `K+1` |
| propose-08 | true | true | 素因子积 + 溢出态，遇 0 转零 |

Winner 策略（可审）：数位 DP `(i, tight, lead, prod)`；前导零保持 `prod=1` 且不计入；非前导乘积，`prod>K` 收成 `K+1`（保留，供后续 0 重置）；终点 `lead` 不计入（x=0），否则 `prod<=K` 计 1。Python int，无 32-bit 截断。

## Pass vectors（官方 + 对抗）

用例序：official1=`5` · official2=`99` · official3=`841103275147365677` · 1010/`1`=`194` · 290/`5`=`75` · N=1=`1` · hold 590/`4`=`129` · hold 10/`1`=`2`。

| candidate | o1 | o2 | o3 | 1010 | ovf→0 | n=1 | hold590 | n=10 | score |
|---|---|---|---|---|---|---|---|---|---|
| baseline-nolead | **F** | **F** | **F** | **F** | **F** | **F** | **F** | **F** | 0 |
| control-discard-overflow | T | T | **F** | **F** | **F** | T | **F** | T | 4 |
| refine-01-gemini ★ | T | T | T | T | T | T | T | T | **8** |
| propose-02 … 08 | T | T | T | T | T | T | T | T | 8 |
| winner-clean-copy | T | T | T | T | T | T | T | T | **8** |
| Arm B oneshot | T | T | T | T | T | T | T | T | **8** |

官方三件每节点都打。对抗（含 holdout）每节点都打。CONTROL 在官方 1–2 全绿后仍挂 `adv_overflow_then_zero`（60 vs 75）和 `adv_multizero_1010`（26 vs 194）；官方 3 同 bug 给出 `779710487084330517`。32-bit 闸靠官方 3：正确值 >2^31−1。

## First all-green step / score

- **Step 1 / `refine-01` / `n-17f05b3c1944`**
- Model: `gemini-3.8-flash`（requested = response）
- Score: **8.0 / 8**
- Reward: 1.0（CONTROL 4 → 8）
- 存库 `best_node_id` 保持此节点
- 干净拷贝 `solve.py` 复评与存库向量/分数完全一致

## Wrong baseline falsified?

**Yes。** CONTROL `n-7e5e8f802973`：

- 过官方 1–2（`5` / `99`）——弱样例放过「超 K 丢状态」
- 挂 `adv_overflow_then_zero`（290 5：先 2×9=18>5，后乘 0 应得 0≤5；discard 少计 15）
- 挂 `adv_multizero_1010`（1010 1：194 vs 26）
- 挂官方 3（同公式大尺度）
- `adv_n1_positive` 与 `hold_n10` 仍过（这两条打的是数 0 / nolead，不是 discard）

baseline-nolead 被官方 1 直接打死（13 vs 5）：前导零乘进积。官方样例**能**抓 nolead，**不能**抓 discard（1–2）。

## Arm B 对照（无搜索树 / 无迭代 falsify）

单次 `gemini-3.8-flash` 直出，同一官方+对抗套件：**8/8 全绿**。`missed_hidden_while_official_green=false`。

一句话：对照臂**没有**栽在官方样例会放过的错公式上；本轮 Gemini 一枪就带了 leading_zero + 溢出桶。Arm A 的增量是树 + 脚本 CONTROL 被闸证伪（官方 1–2 绿、对抗红），不是「直出必挂隐藏例」。

## 硬锁确认

| 锁 | 状态 |
|---|---|
| submit=0 | 评测器零网络；从未访问 AtCoder 提交接口 |
| fixed_uct only | 每次 `select` 无 `--selection-id` / Progressive flag；payload 仅 `{selected, uct}` |
| `#40` SelectionPolicy | off（未焊开） |
| Elite ≠ promotion | 未走 Progressive，无 Elite 采样 |
| Gemini-led rotate | 仅 3.8 → 3.7-high → flash-latest；optional 未用 |
| 无 DeepSeek LONG | catalog 有 `coding-deepseek-*` / `deepseek-v4-*-ga`，**0 次调用** |
| 无 GPT* | catalog 有 gpt-*，**0 次调用** |
| 新 STATE_DIR | `.algorithm-evolve/abc208-e-limit-fixed` |
| 未改 evoK / runGoldenPath / Broker / `skills/` | `git diff origin/main -- skills` 空 |

## Yellow notes

- `/workspace/company` 不在 VM。循环 = algorithm-evolve live-tree + 本地评测 + NEWAPI Gemini。
- Context7 MCP 不在本 run 动态命名空间。
- 8 个 Gemini 节点在 CONTROL refine 提示后全部 8/8。闸的杀伤体现在**脚本 CONTROL**，不像 ABC061 还有「声称正确但仍挂 holdout」的 LLM 节点。
- `gemini-flash-latest` 被网关映到 `gemini-3.8-flash`。optional 3.6 / pro-agent 未需要。
- 墙钟 ~115s（8 次 LLM，约 6–26s/次）。候选 10 个，落在 8–12。
- 主机循环用 NEWAPI curl 代替 skill 文案里的 generator subagent。评测器不连 AtCoder。
- 证据-only Git commit。产品 `skills/` 未改。不主张合入 main。

## 结论

合理 Gemini 策略存在（leading_zero + 溢出桶 `K+1`）。本地闸**能**杀掉「官方 1–2 绿、积超 K 丢状态」的 CONTROL，以及 nolead / 计数 x=0 类。Arm B 本轮也全绿，对照说明的是「直出也能对」而非「直出必漏杀」。**不要声称 AtCoder AC。** KPI = 证伪错数位 DP 公式 + 两臂对比，不是竞赛排名。

## Layout

```
evidence/2026-09-19-limit-test-abc208-e/   # 本报告（提交）
.algorithm-evolve/abc208-e-limit-fixed/    # gitignored live tree
  task.json  state.db  evaluator/  candidates/  evidence/  tools/  logs/  oneshot/
/opt/cursor/artifacts/abc208-e-limit-fixed/
```
