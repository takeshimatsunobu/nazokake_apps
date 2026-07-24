# syntax=docker/dockerfile:1
#
# ローカル・クリーンルーム(instructions/001)の自律コード修正ループ実行環境。
# tools/nazo_agent.py / tools/agent_graph.py (Gemma -> Qwen -> Claude の3層防弾
# エスカレーション実行コア、SSoT_architecture.md 8.4節) を駆動する。
#
# tools/benchmark/Dockerfile と同じ方針で、apps/ packages/ tools/ tests/ は
# ビルド時にCOPYしない(ホストのソースをイメージへ焼き込まない)。エージェントが
# 実際にファイルを読み書きする対象は infra/docker-compose.yml 側のbindマウントで
# 実行時に供給する(ビルドとソース変更のサイクルを分離し、コード修正のたびの
# 再ビルドを不要にする)。
#
# Build from repo root: docker build -f infra/agent-workspace/Dockerfile -t nazo-agent-workspace .
FROM python:3.11-slim

RUN useradd --create-home --uid 1000 agentuser

WORKDIR /workspace

# requirements_orchestrator.txt (anthropic, google-genai, langgraph,
# langchain-ollama, libcst, pyright, pytest 等) は tools/nazo_agent.py の
# 実行に必要な依存一式であり、これのみをビルド時にCOPYする(ソース本体は
# bindマウント対象のため含めない)。
COPY requirements_orchestrator.txt .
RUN pip install --no-cache-dir -r requirements_orchestrator.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

RUN chown -R agentuser:agentuser /workspace

USER agentuser

# 実際のエントリポイントは docker-compose.yml 側の command で明示する
# (bindマウントされた /workspace/tools/nazo_agent.py を起動する想定)。
CMD ["python", "-m", "tools.nazo_agent"]
