# CodeAgent

CodeAgent 是一个本地 Web Coding Agent。前端使用 Vue 3，后端使用 FastAPI；模型通过 OpenAI-compatible API 调用，默认配置示例为 DeepSeek。所有模型地址、模型名和 API Key 都由环境变量提供，代码中不包含凭据。

## 安装与启动

```bash
cp .env.example .env
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
cd frontend && npm install
```

编辑根目录 `.env`，至少填写 `LLM_PROVIDER`、`LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。API Key 不需要额外引号；值包含空格或 `#` 时可使用引号。

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
