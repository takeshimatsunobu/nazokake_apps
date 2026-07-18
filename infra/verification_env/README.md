# 検証サーバー: Rootless Docker + セキュア基盤の移行設計 (instructions/145/146/147)

## 目的

`tools/benchmark/run_benchmark.py`(Nazo-Agentの6次元定量評価ゲート)を、この開発機
(Windows、Docker未導入)から分離した専用のLinux検証サーバー上で、Rootless Docker +
NVIDIA GPUパススルーの下で決定論的に実行できるようにする。

**このドキュメントは設計・手順書であり、実際のサーバーへの適用結果はこのセッションでは
検証していない**(該当する物理/クラウドサーバーが存在しないため)。適用後は必ず
[検証方法](#検証方法)の節に従って動的テストを実行し、合否を確認すること。

## セキュア基盤の移行方針: 「再現」ではなく「再利用」

このリポジトリには既に以下のセキュア基盤が実装済みで、いずれも本番(Cloud Run)・
開発機(Windows)の両方で同一のコードが動いている:

| 基盤 | 実装場所 |
|---|---|
| アトミックI/O(fsync+os.replace) | `tools/export_metrics.py`, `tools/ast_modifier.py._atomic_write_text` |
| CQRS静的JSONダンプ | `tools/export_metrics.py` → `apps/evaluator/frontend/public/data/metrics.json` |
| VRAM排他制御(filelock) | `tools/config.py:VRAM_LOCK_PATH`, `tools/mlops_common.py.acquire_vram_lock_with_backoff()` |
| ドメイン固有例外/終了コード規約 | `tools/exceptions.py`, `run_benchmark.py`(exit code 125=インフラエラー) |
| 6次元定量評価ゲート | `tools/benchmark/run_benchmark.py.evaluate_6d_quality_gate()` |
| 軽量ローカルRAG(Experience Replay) | `tools/compile_knowledge.py`, `tools/knowledge_retriever.py` |

**検証サーバーはこれらを再実装(フォーク)しない。** `setup_verification_env.sh` の役割は
OS/ホストレベルの前提条件(cgroup委譲・GPUランタイムフック)を整えることだけであり、
検証サーバーは本リポジトリを直接クローンして上記モジュールを無改変のまま実行する。
これにより、開発機と検証サーバーで実装が二重化してドリフトするリスクを構造的に排除する。

**【instructions/147での修正】** 以前は「クローンしてそのまま実行する」という運用手順を
README上の文章のみで説明しており、実行環境(Pythonバージョン・依存関係・マウント構成)
そのものはコード化されていなかった。これを`infra/verification_env/docker-compose.yml`
として明示的にコード化した:
- `knowledge-base-builder`サービス: `tools/ai_knowledge_base.json`(Experience Replayの
  知識ベース)を、ホストのuv/Python環境に依存せず常に同一の`python:3.11-slim`イメージで
  再生成する(`tools/compile_knowledge.py`は標準ライブラリのみに依存するため追加の
  pip installは不要)。
- `benchmark-sandbox`サービス: `tools/benchmark/Dockerfile`から
  `nazo-benchmark-sandbox`イメージ(`run_benchmark.py`が`docker run`で直接起動する
  イメージ名と一致させる)をビルドする定義。

`setup_verification_env.sh`はこの2サービスを`docker compose run`/`docker compose build`
で明示的に呼び出すよう改修済みであり、「暗黙の前提」への依存はこの2つの前処理については
解消されている。

## セットアップ手順

1. 検証サーバー上で本リポジトリをクローンする(`REPO_DIR`、既定は
   `$HOME/nazokake_apps`。上書きする場合は環境変数で指定)。
2. NVIDIA Driver + NVIDIA Container Toolkit + Rootless Docker(`dockerd-rootless-setuptool.sh`
   でのセットアップ)が導入済みであること。
3. `sudo bash infra/verification_env/setup_verification_env.sh` を実行する。
   - `/etc/systemd/system/user@.service.d/delegate.conf` (`Delegate=yes`) を配置し、
     rootless dockerdがcgroup v2経由でメモリ/CPU/pids制限を実際に適用できるようにする。
   - NVIDIA Container Toolkitの `config.toml` に `nvidia-container-cli.no-cgroups=true`
     を設定し、rootless dockerd向けのランタイム登録・再起動を行う。
   - `.env.verification.template` から `<REPO_DIR>/.env` を生成し、
     `NAZOKAKE_DB_PATH`/`VRAM_LOCK_PATH` を絶対パスに固定する(`run_api.ps1` の
     Windows向けパターンと同じ設計思想をLinux向けに再現)。
   - `docker compose -f infra/verification_env/docker-compose.yml run --rm
     knowledge-base-builder` を実行し、`tools/ai_knowledge_base.json`
     (Experience Replayの知識ベース)を決定論的に事前ビルドする。
   - `docker compose -f infra/verification_env/docker-compose.yml build
     benchmark-sandbox` を実行し、ベンチマークサンドボックスイメージをビルドする。
4. `uv sync` 等で依存関係をインストールする(このスクリプトの範囲外)。

## VRAM決定論的制御についての技術的前提

Dockerには、コンテナ単位でのハードVRAM量子化機構がネイティブには存在しない
(NVIDIA vGPU/MPSライセンスが別途必要)。したがって「決定論的な強制」は以下2点の
組み合わせで実現する(抽象論ではなく、この2点が実際の制御ロジックそのもの):

1. `docker run --gpus device=0` によるGPU単一専有(複数コンテナへの分割共有を許可しない)。
2. `tools/config.py:VRAM_LOCK_PATH`(filelock)による、アプリ本体・MLOpsパイプライン・
   このベンチマーク検証の全プロセス間での直列化。既存の排他制御をそのまま再利用し、
   検証サーバー用に新しい仕組みを作らない。

## 検証方法

Linter(`ruff check`)のパスは実装完了の条件にしない。以下を検証サーバー上で実行し、
実際の動的な振る舞いで証明すること:

```bash
cd "${REPO_DIR}"
uv run python -m pytest tests/verification_env/test_infra_behavior.py -v
```

開発機(このセッション)では `test_cgroup_delegation_is_active` と
`test_nvidia_toolkit_hook_and_gpu_visible` は `pytest.skip` される
(`systemctl`/`docker`/`nvidia-ctk` が存在しないため)。**正しくプロビジョニングされた
検証サーバー上では、この2件がskipされずに実際にPASSすることを確認すること。**
skipされたままの場合は前提条件(NVIDIA Container Toolkit・Rootless Docker)の導入が
不完全である。

他の4件(VRAMロックの直列化・アトミック書き込みの並行読み取り耐性・6次元ゲート・
Experience Replay検索)は開発機・検証サーバーのいずれでも実行可能であり、既にこの
開発機上で動的に合格を確認済み(instructions/145実装時)。
