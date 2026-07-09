import torch
import torch._inductor.config  # 念のための安全装置
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

# 設定
max_seq_length = 2048
dtype = None
load_in_4bit = True

# 👑 Gemma 4 E4B (Tier 1 ローカルモデル)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/gemma-4-e4b-it-bnb-4bit",
    max_seq_length = max_seq_length,
    dtype = dtype,
    load_in_4bit = load_in_4bit,
)

# LoRA設定
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = "unsloth",
)

# データの読み込み
dataset = load_dataset("json", data_files="data/sft_dataset_formatted.jsonl", split="train")

# 学習の実行
trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset,
    dataset_text_field = "text",
    max_seq_length = max_seq_length,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 5,
        max_steps = 60,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        output_dir = "outputs",
    ),
)
trainer.train()

# 保存
model.save_pretrained("gemma4_e4b_nazokake_model")
tokenizer.save_pretrained("gemma4_e4b_nazokake_model")
print("🎉 なぞかけ専用 Gemma 4 E4B が誕生しました！")
