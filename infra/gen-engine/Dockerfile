# syntax=docker/dockerfile:1
#
# ローカル大量生成エンジン(instructions/001)。apps/batch_factory/start_vllm.sh で
# 手動運用されていたvLLM起動手順を、GPUパススルー対応のコンテナサービスとして
# 固定する。
#
# 【役割の切り分け】SSoT_architecture.md 8.3節の「① ローカルLLM (Ollama) -
# タイムシェアリング稼働」(ELYZA/Gemma/Qwenの対話的エスカレーション用、ホスト常駐
# のOllamaプロセスがそのまま担う)とは別レーン。このgen-engineは
# apps/batch_factory の大量生成バッチ専用に、GPUを占有してvLLMのスループットを
# 活かすための独立サービス(instructions/001の「gen-engine」要件)。
#
# 【引き継がないもの】apps/batch_factory/start_vllm.sh にハードコードされていた
# HF_TOKEN は絶対に引き継がない。トークンは docker-compose.yml の env_file
# (../.env) 経由でのみ注入する。
FROM vllm/vllm-openai:v0.6.3

# モデル・並列度は再ビルド無しで docker-compose.yml 側の environment から
# 上書き可能にし、イメージ自体はモデル非依存に保つ。既定値は
# apps/batch_factory/start_vllm.sh が実運用していた構成を引き継ぐ。
ENV GEN_ENGINE_MODEL="tokyotech-llm/Swallow-13b-instruct-v0.1" \
    GEN_ENGINE_TENSOR_PARALLEL_SIZE=1 \
    GEN_ENGINE_MAX_MODEL_LEN=4096 \
    HF_HOME=/data/hf_cache

EXPOSE 8000

# vllm/vllm-openai の既定ENTRYPOINTは `python3 -m vllm.entrypoints.openai.api_server`
# 固定のため、ここではCMDとしてオプションのみを渡す(sh -cで環境変数展開)。
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec python3 -m vllm.entrypoints.openai.api_server --model \"$GEN_ENGINE_MODEL\" --tensor-parallel-size \"$GEN_ENGINE_TENSOR_PARALLEL_SIZE\" --max-model-len \"$GEN_ENGINE_MAX_MODEL_LEN\" --host 0.0.0.0 --port 8000"]
