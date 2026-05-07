import pandas as pd

EVAL_AXES = [
    ("S_sur", "意外性", "w_1"), ("S_tech", "技巧性", "w_2"), ("S_emo", "情動的連関", "w_3"),
    ("S_rhy", "リズム・語感", "w_4"), ("S_sensory", "身体ギャップ", "w_5"), ("S_visual", "視覚類似度", "w_6"),
    ("S_ontology", "オントロジー飛躍", "w_7"), ("S_cultural", "文化適合度", "w_8"), 
    ("S_cm", "概念メタファー", "w_9"), ("S_prosody", "プロソディ一致", "w_10")
]

def get_preset_weights():
    return {
        "バランス型 (すべて1.0)": {axis[2]: 1.0 for axis in EVAL_AXES},
        "意味的飛躍重視 (意外性・オントロジー)": {**{axis[2]: 1.0 for axis in EVAL_AXES}, "w_1": 2.5, "w_7": 2.0},
        "リズム・語感重視 (プロソディ)": {**{axis[2]: 1.0 for axis in EVAL_AXES}, "w_4": 2.0, "w_10": 2.5},
    }

def calculate_dynamic_score(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    if df.empty:
        return df
        
    df_calc = df.copy()
    weighted_sum = sum(df_calc.get(axis_col, 0.0) * weights[weight_key] for axis_col, _, weight_key in EVAL_AXES)
    total_weight = sum(weights.values())
    
    if total_weight > 0:
        df_calc["S_total"] = df_calc.get("S_nat", 1.0) * (weighted_sum / total_weight)
    else:
        df_calc["S_total"] = 0.0
        
    return df_calc.sort_values(by="S_total", ascending=False).reset_index(drop=True)