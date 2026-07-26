.PHONY: extract-data train-model mlops-pipeline

extract-data:
	uv run python tools/extract_training_data.py

train-model:
	uv run python tools/train_local_model.py --dry-run

mlops-pipeline: extract-data train-model
