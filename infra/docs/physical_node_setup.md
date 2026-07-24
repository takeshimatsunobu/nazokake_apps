# 物理Linuxノード セットアップ手順書 (instructions/002)

## 目的

自律コーディングエージェント(`agent-workspace`)と大量生成エンジン(`gen-engine`)を、
この開発機(Windows)やクラウド本番環境(Cloud Run)から物理的に隔離した専用のUbuntu
LTSマシン上で、Rootless Docker + NVIDIA Container Toolkitの下に安全に実行するための
手順書。`infra/scripts/setup_host.sh` が本手順書のステップ2〜5をスクリプト化する。

**このドキュメントは設計・手順書であり、実際の物理サーバーへの適用結果はこのセッション
では検証していない**(この開発機には対象の物理Linuxマシンが存在しないため。
`infra/verification_env/README.md` と同じ位置づけ)。適用後は必ず
[検証コマンド](#検証コマンド)を実行し、合否を確認すること。

## 推奨OS・初期設定

- **推奨OS:** Ubuntu 24.04 LTS、または 22.04 LTS(いずれもデフォルトでcgroup v2
  unified hierarchyが有効)。デスクトップ/サーバーいずれのisoでも構わないが、
  常設のクリーンルーム専用機とする場合はサーバー版(GUI無し)を推奨する。
- **セキュアブートの扱い:** NVIDIAプロプライエタリドライバはカーネルモジュールの
  署名を要求するため、以下いずれかの対応が必要。
  1. **(推奨・単純)** このマシンをクリーンルーム専用機として運用する場合、BIOS/UEFI
     設定でSecure Bootを無効化する。運用がシンプルになる代わりに、Secure Bootが
     提供するブート改ざん検知は失われる(専用機・物理アクセス制限前提なら許容範囲)。
  2. **(Secure Bootを維持する場合)** `ubuntu-drivers install` でNVIDIAドライバを
     導入すると、初回インストール時にMOK(Machine Owner Key)登録用パスワードの
     設定を求められる。設定後の再起動時に表示される青い「MOK management」画面で
     パスワードを入力し、鍵を手動で登録(Enroll MOK)する必要がある。無人・遠隔での
     初期セットアップには不向き(物理コンソールでの操作が必須)。
- **NVIDIA Driverの導入:** `infra/scripts/setup_host.sh` はNVIDIA Driver本体の
  インストールは行わない(GPUモデル・カーネルバージョンに応じた選定が必要なため、
  範囲外とする)。`sudo ubuntu-drivers install` または
  `sudo apt-get install nvidia-driver-<version>` で事前に導入し、
  `nvidia-smi` がホスト上で正常に動作することを確認してから本スクリプトを実行すること。

## `setup_host.sh` の実行手順

1. 対象マシン上に本リポジトリをクローンする。
2. NVIDIA Driverを導入し、ホスト上で `nvidia-smi` が動作することを確認する(上記参照)。
3. sudo権限を持つ一般ユーザーとして以下を実行する(**root/sudoで丸ごと実行しない**。
   Rootless Dockerのセットアップツール自体がroot実行を拒否する):

   ```bash
   cd nazokake_apps
   CONFIRM_WIPE_DOCKER=yes bash infra/scripts/setup_host.sh
   ```

   `CONFIRM_WIPE_DOCKER=yes` は、スクリプトのステップ1(既存Docker環境の完全削除、
   `/var/lib/docker` 以下のコンテナ・イメージ・ボリュームを含む)が破壊的操作である
   ことを踏まえた明示的な確認ゲート。既存のDocker環境に残しておきたいコンテナ・
   イメージがある場合は、実行前に個別にバックアップ/移行すること。

4. スクリプトが `cgroup v2が無効です` と出力して終了した場合、GRUB設定
   (`systemd.unified_cgroup_hierarchy=1`)を反映するため再起動し、同じコマンドを
   再実行する。
5. 完了後、`infra/verification_env/setup_verification_env.sh` の
   systemd cgroup delegation(`Delegate=yes`)設定も必要に応じて重ねて実行する
   (本スクリプトはその設定を意図的に重複実装していない)。

## 検証コマンド

```bash
# 1. Rootless dockerdが一般ユーザー権限で稼働していることを確認
docker info --format '{{.SecurityOptions}}' | grep -q rootless && echo "OK: rootless"

# 2. Rootless Docker経由でのGPUパススルーと権限分離の疎通確認
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi
```

2つ目のコマンドが、権限昇格エラー無しにGPU情報を出力すれば、Rootless Docker配下でも
コンテナからGPUへ到達できていることの確認になる。`--gpus all` はlegacy nvidia
ランタイム経由の指定であり、`infra/scripts/setup_host.sh` が構成したCDI
(`/etc/cdi/nvidia.yaml`)を実際に使う場合は `--device nvidia.com/gpu=all` に置き換えて
同様に確認すること。

## CVE-2026-24260 に対する構造的防壁について

**正直な前提:** このセクションを書いているAIエージェントの知識には2026年1月までの
情報しか含まれておらず、CVE-2026-24260の具体的な脆弱性メカニズム(攻撃条件・影響範囲・
修正バージョン)を検証済みの情報として記述することはできない。以下は、脆弱性の詳細に
依存しない、Rootless Docker + cgroup v2 + Linux namespacesが提供する一般的な
構造的防壁の解説であり、CVE-2026-24260固有の修正の代替にはならない。
**実際の対策状況は、NVIDIA公式のセキュリティ勧告
(<https://github.com/NVIDIA/nvidia-container-toolkit> のSecurity Advisories)で
`infra/scripts/setup_host.sh` 実行後のバージョン番号を必ず照合すること。**

一般的に、NVIDIA Container Toolkit/Runtime層の脆弱性の多くは「コンテナ内プロセスが、
本来到達できないはずのホストリソース(デバイスノード・ファイルシステム・場合により
ホストのroot権限)に到達できてしまう」という形を取る。この構成が提供する多層防御は
CVEの詳細に関わらず有効:

1. **User Namespaces(Rootless Dockerの前提):** コンテナ内の`root`(UID 0)は、
   ホスト上では非特権の一般ユーザーUIDにマッピングされる。ランタイム層の脆弱性で
   コンテナ脱出が成立しても、脱出先で得られる権限はホストの非特権ユーザーの権限に
   留まり、ホストのroot権限には直結しない。
2. **cgroup v2 (unified hierarchy) のデバイスコントローラ:** コンテナに許可された
   デバイスノード(GPU等)のみへのアクセスを、カーネルのcgroupサブシステムが強制する。
   `infra/scripts/setup_host.sh` のステップ2で有効化を確認しているのはこの前提。
3. **CDI (Container Device Interface) による明示的デバイス注入:** legacyの
   `--gpus all`(broad, ランタイムフック経由の暗黙的なデバイス列挙)と異なり、CDIは
   `/etc/cdi/nvidia.yaml` に列挙された具体的なデバイスノード・マウントのみを注入する。
   注入対象が静的ファイルとして明示され、レビュー・監査が可能になる。

これら3点は、特定のCVEが修正される「前」でも被害範囲を非特権ユーザー権限・許可された
デバイスのみに構造的に限定する効果を持つ。ただし、脆弱性そのものを塞ぐものではないため、
最新パッチの適用(instructions/002・本スクリプトのステップ4)は別途必須。

## 既知の制約・フォローアップ事項

- `infra/docker-compose.yml`(instructions/001)の`gen-engine`サービスは現在legacy
  nvidiaランタイム方式(`deploy.resources.reservations.devices`)でGPUを指定しており、
  本スクリプトが構成するCDI方式とは異なる。両方式は同一ホスト上で共存可能だが、CDI方式に
  完全統一する場合は`docker-compose.yml`側の追加更新が必要(instructions/002の範囲外、
  将来のバックログ対象)。
- NVIDIA Driver本体の導入は本手順書の範囲外(上記「推奨OS・初期設定」参照)。
- このスクリプト・手順書は物理サーバー上で実行・検証されていない(前述の通り)。
