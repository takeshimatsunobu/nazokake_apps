from pydantic import BaseModel, Field

class NazokakeEvaluationResult(BaseModel):
    reasoning: str = Field(description="推論プロセス")
    S_sur: float = Field(description="意外性")
    S_nat: float = Field(description="納得感")
    S_tech: float = Field(description="技巧性")
    S_emo: float = Field(description="情動的連関")
    S_rhy: float = Field(description="リズム")
    S_sensory: float = Field(description="身体性")
    S_visual: float = Field(description="視覚")
    S_ontology: float = Field(description="飛躍度")
    S_cultural: float = Field(description="文化")
    S_cm: float = Field(description="メタファー")
    S_prosody: float = Field(description="プロソディ")
    S_predict_human: float = Field(description="5段階予測")