# CodeAgent

CodeAgent 是一个本地 Web Coding Agent。前端使用 Vue 3，后端使用 FastAPI；模型通过 OpenAI-compatible API 调用，默认配置示例为 DeepSeek。所有模型地址、模型名和 API Key 都由环境变量提供，代码中不包含凭据。

> 本项目未使用 LangChain、LlamaIndex、OpenAI Agents SDK、AutoGen 等 Agent 框架。对话历史与上下文管理、Tool Call 解析、本地工具执行、Agent 循环、终止条件、错误处理和运行记录均由项目自行实现。

## 核心架构

| 层次 | 技术与职责 |
| --- | --- |
| 前端 | Vue 3、Vite、Pinia、Vue Router，负责对话、项目、事件流和 Diff 界面 |
| API | FastAPI，提供项目、对话、Run、工具、Skill、文件及 SSE 接口 |
| Agent 运行时 | 负责上下文组装、模型调用、工具循环、取消、超时和终止条件 |
| 模型适配 | OpenAI-compatible Chat Completions API，默认使用 DeepSeek 配置示例 |
| 存储 | SQLite，保存对话历史、运行状态、事件和文件版本 |

```text
用户任务
  → 加载对话历史与当轮能力快照
  → 调用模型并解析流式输出
  → 校验并执行 Tool Calls
  → 将工具结果追加到上下文
  → 继续迭代，直到最终回答或命中终止条件
```

Agent 支持正常完成、用户取消、总任务超时、模型错误、最大迭代数、无进展重复工具调用和服务重启等终止情况。

## 安装与启动

```bash
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
cd frontend && npm install
```

编辑根目录 `.env`，至少填写 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。API Key 不需要额外引号；值包含空格或 `#` 时可使用引号。

Agent 单轮任务默认最多运行 900 秒。复杂任务可以在 `.env` 中通过
`CODEAGENT_TASK_TIMEOUT_SECONDS` 调整，允许范围为 60～7200 秒；修改后需要重启后端。

启动后端：

```bash
backend/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd frontend
npm run dev -- --host 127.0.0.1
```

浏览器打开 `http://127.0.0.1:5173`。

## 项目与对话

- 在左侧输入本地项目的绝对路径并添加。一个项目永久绑定一个工作区目录。
- 每个项目可以创建多个对话；每个对话拥有独立上下文，并可连续进行多轮任务。
- URL 形如 `/projects/{projectId}/conversations/{conversationId}`，刷新后会从后端恢复项目、消息、运行和历史修改。
- “从 CodeAgent 移除”只删除本地数据库中的项目与对话元数据，绝不会删除、移动或修改真实工作区文件。
- 如果项目目录被移动或删除，历史仍保留，但必须恢复目录后才能启动新任务。

## 每轮文件修改

每次运行进入完成、失败或取消状态时，后端都会结算这一轮实际产生的文件变化。对话记录中可以展开修改文件，并在右侧切换：

- 本轮冻结 Diff；
- 本轮结束时的历史文件版本；
- 当前工作区文件版本。

后续任务再次修改同一文件不会覆盖旧运行的 Diff。二进制和超限文件只保存路径、大小和哈希，不保存完整内容。

## 实时思考与运行过程

模型支持思考流时，当前轮会在对话中实时展示可折叠的“Agent 思考过程”；工具开始后会继续展示正在读取、写入、修改或运行的具体操作。历史思考默认折叠并可重新展开。展示内容会经过凭据脱敏，单轮最多保留 30000 个字符。

DeepSeek thinking 模式可通过 `.env` 显式开启：

```env
LLM_EXTRA_BODY_JSON={"thinking":{"type":"enabled"}}
```

不返回 `reasoning_content` 的 OpenAI-compatible 服务会自动退化为阶段状态和工具轨迹，不影响 Agent 正常执行。

## 工具管理

当前对话标题右侧的“工具”按钮会在右侧打开该对话的能力设置。对话内容和标题保持可见，因此可以明确配置作用于哪个对话。七个内置工具按只读、文件修改和命令执行分组，可以逐项开启或关闭：

- 关闭的工具不会发送给模型，模型即使伪造对应 Tool Call，后端也会以 `unknown_tool` 拒绝执行。
- 关闭全部工具后进入“仅聊天模式”，Agent 仍能回答问题，但不能读取或改动项目，也不能执行命令。
- 每次 Run 创建时都会冻结当轮工具与 Skill 配置。后续调整不会改变历史记录；运行期间不能修改当前对话的能力。
- `run_command` 仍经过原有风险分级和对话内审批，工具开关不会绕过路径边界、参数校验或命令审批。

## Skill 配置

当前对话标题右侧的“Skill”按钮会在右侧打开工作流配置。添加时填写包含 `SKILL.md` 的本地文件夹绝对路径；注册仅保存元数据和指令内容，不执行目录中的脚本，也不会删除原目录。Skill 是用户本地管理的配置，不随本仓库分发。

`SKILL.md` 使用受限 YAML front matter：

```markdown
---
name: cpp-problem-solver
description: 完成 C++ 算法题并编译验证
version: 1.0.0
required_tools:
  - read_file
  - write_file
  - run_command
recommended_tools:
  - search_text
---

先读取题意和现有代码，再实现解法并执行编译测试。
```

启用 Skill 时会自动开启其必需工具；必需工具仍被 Skill 使用时不能单独关闭。系统只读取 Skill 根目录中的普通 `SKILL.md`，拒绝符号链接、未知字段、未知工具和超限内容。Skill 正文只进入冻结后的模型系统提示，不会出现在公开能力事件中。

## 持久化与重启

默认数据库位于 `runtime/codeagent.sqlite3`，可以通过 `CODEAGENT_DATABASE_PATH` 修改。数据库、WAL 和 SHM 文件均已被 Git 忽略。

已完成的对话历史可跨后端重启恢复。后端无法恢复重启前仍在执行的模型请求、命令或审批；启动时这类运行会被明确标记为 `failed/server_restarted`。

## 验证

```bash
backend/.venv/bin/python -m pytest -c backend/pyproject.toml backend/tests --ignore=backend/tests/live
backend/.venv/bin/ruff check backend/app backend/tests
backend/.venv/bin/mypy backend/app
cd frontend && npm test -- --run && npm run build
```

真实模型测试需要显式开启，会产生 API 请求和费用：

```bash
RUN_LIVE_LLM_TESTS=1 backend/.venv/bin/python -m pytest \
  -c backend/pyproject.toml backend/tests/live/test_deepseek_provider.py
```

当前测试基线为后端 144 项、前端 30 项，并通过 Ruff、Mypy 和前端生产构建。

## 安全与设计边界

- 文件工具只接受工作区相对路径，拒绝绝对路径、`..` 和解析后越界的符号链接。
- 工具参数通过 JSON Schema 校验，未启用或未注册工具不会执行。
- Shell 命令分为自动允许、需要审批和直接禁止三档，支持超时、取消和进程组终止。
- API Key、本地 `.env`、SQLite 数据库与运行数据均已被 Git 忽略。
- 本项目定位为本地单用户工作台；命令规则与审批机制不等价于完整的操作系统沙箱。
