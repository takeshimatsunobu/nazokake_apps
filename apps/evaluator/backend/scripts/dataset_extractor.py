import os
import sys
import json
import yaml
import itertools
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


class DatasetExtractor:
    """
    SFT / DPO データ抽出を統合管理する、関心の分離とフェイルファストを徹底した統合抽出エンジン
    """

    def __init__(self, config_name="ml_config.yaml"):
        # __file__ を起点とした動的絶対パス解決（環境の揺らぎを吸収）
        self.base_dir = Path(__file__).resolve().parent.parent
        self.config_path = self.base_dir / "config" / config_name

        # 強制上書きモードで.envを読み込み
        env_path = self.base_dir.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=True)
            logger.info(f"✅ Loaded .env from: {env_path}")
        else:
            load_dotenv(override=True)

        self._load_config()
        self._init_firestore()

    def _load_config(self):
        """外部YAMLファイルからクオリティゲート（閾値）を読み込む"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
            logger.info(f"✅ Config loaded from: {self.config_path}")

    def _init_firestore(self):
        """Firestoreクライアントの初期化（相対パス解決＆完全マジックナンバー排除仕様）"""
        # フォールバック無しの厳格なキー参照（欠損時は即座に KeyError でフェイルファスト）
        try:
            project_id = self.config["dataset"]["project_id"]
        except KeyError:
            logger.critical(
                "🚨 [Fatal] ml_config.yaml 内に 'project_id' の定義が存在しません。処理を強制停止します。"
            )
            raise KeyError("Missing required config: ['dataset']['project_id']")

        if not firebase_admin._apps:
            options = {"projectId": project_id}
            cred_path_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

            if cred_path_raw:
                # ▼ 監査指摘：相対パスが指定されていた場合の罠を、プロジェクトルート起点の絶対パス化で完全封殺 ▼
                cred_path = Path(cred_path_raw)
                if not cred_path.is_absolute():
                    cred_path = (self.base_dir.parent / cred_path).resolve()

                if not cred_path.exists():
                    logger.critical(
                        f"🚨 [Fatal] GOOGLE_APPLICATION_CREDENTIALS のファイルが物理的に存在しません: {cred_path}"
                    )
                    raise FileNotFoundError(f"Credentials file missing at: {cred_path}")

                cred = credentials.Certificate(str(cred_path))
                firebase_admin.initialize_app(cred, options)
                logger.info(
                    f"🔑 Initialized Firebase via Service Account JSON: {cred_path}"
                )
            else:
                # 環境変数がない場合は、gcloud auth 等の Application Default Credentials (ADC) に安全に委譲
                firebase_admin.initialize_app(options=options)
                logger.info(
                    f"☁️ Initialized Firebase via Application Default Credentials (ADC) for project: {project_id}"
                )

        self.db = firestore.client()
        self.collection_name = self.config["dataset"].get(
            "collection_name", "nazokake_items"
        )

    def _fetch_base_items(self):
        """共通のデータフェッチと無効データパージロジック"""
        logger.info(f"🔄 Fetching data from collection: {self.collection_name}...")
        docs = self.db.collection(self.collection_name).stream()

        valid_items = []
        for doc in docs:
            d = doc.to_dict()
            if not d.get("odai") or not d.get("nazokake_text"):
                continue
            if d.get("s_total", 0) <= 0:
                continue
            valid_items.append(d)

        logger.info(f"✅ Fetched {len(valid_items)} valid items from Firestore.")
        return valid_items

    def export_sft_dataset(self, output_dir: Path):
        """SFT用（Hugging Face `messages` スキーマ）の特級データ抽出"""
        min_score = self.config["sft"]["min_score"]
        require_golden = self.config["sft"]["require_golden_flag"]

        items = self._fetch_base_items()
        sft_records = []

        for item in items:
            if require_golden and not item.get("is_golden_data"):
                continue
            if item.get("s_total", 0) < min_score:
                continue

            prompt_text = f"お題「{item['odai']}」でなぞかけを作成してください。"
            record = {
                "messages": [
                    {"role": "user", "content": prompt_text},
                    {"role": "assistant", "content": item["nazokake_text"]},
                ]
            }
            sft_records.append(record)

        out_file = output_dir / self.config["sft"]["output_filename"]
        self._write_jsonl(sft_records, out_file)
        logger.success(
            f"🎉 SFT Dataset exported: {len(sft_records)} records -> {out_file.name}"
        )

    def export_dpo_dataset(self, output_dir: Path):
        """DPO用（prompt, chosen, rejected スキーマ）のペア抽出"""
        min_diff = self.config["dpo"]["min_score_diff"]
        max_pairs = self.config["dpo"]["max_pairs_per_group"]

        items = self._fetch_base_items()

        groups = {}
        for item in items:
            group_key = item.get("dpo_pair_id") or item.get("doc_id")
            if not group_key:
                continue
            groups.setdefault(group_key, []).append(item)

        dpo_records = []

        for group_key, group_items in groups.items():
            if len(group_items) < 2:
                continue

            pairs = list(itertools.combinations(group_items, 2))
            valid_pairs = []

            for i1, i2 in pairs:
                s1, s2 = i1.get("s_total", 0), i2.get("s_total", 0)
                if s1 == s2 or i1["nazokake_text"] == i2["nazokake_text"]:
                    continue

                chosen, rejected = (i1, i2) if s1 > s2 else (i2, i1)
                score_diff = chosen.get("s_total", 0) - rejected.get("s_total", 0)

                if score_diff >= min_diff:
                    prompt_text = (
                        f"お題「{chosen['odai']}」でなぞかけを作成してください。"
                    )
                    valid_pairs.append(
                        {
                            "_diff": score_diff,
                            "prompt": prompt_text,
                            "chosen": chosen["nazokake_text"],
                            "rejected": rejected["nazokake_text"],
                        }
                    )

            valid_pairs.sort(key=lambda x: x["_diff"], reverse=True)
            for p in valid_pairs[:max_pairs]:
                del p["_diff"]
                dpo_records.append(p)

        out_file = output_dir / self.config["dpo"]["output_filename"]
        self._write_jsonl(dpo_records, out_file)
        logger.success(
            f"🎉 DPO Dataset exported: {len(dpo_records)} pairs -> {out_file.name}"
        )

    def _write_jsonl(self, records, file_path: Path):
        """JSONLの安全な書き出し"""
        with open(file_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        extractor = DatasetExtractor()
        data_dir = extractor.base_dir.parent / "data"
        data_dir.mkdir(exist_ok=True)

        logger.info("=== Starting Unified Extractor ===")
        extractor.export_sft_dataset(data_dir)
        extractor.export_dpo_dataset(data_dir)
        logger.info("=== Extraction Completed ===")
    except Exception:
        logger.opt(exception=True).error(
            "🚨 致命的なエラーが発生し、抽出が中断されました。"
        )
        sys.exit(1)
