from pydantic import BaseModel, Field
from typing import List

class TargetContext(BaseModel):
    target_url: str = Field(description="標的となるSNSスレッドのURL")
    conflict_structure: str = Field(description="対立構造（A vs B）の客観的要約")
    sunk_cost: str = Field(description="当事者が抱えているサンクコスト（引っ込みがつかない理由）")
    defensive_pride: str = Field(description="防衛的自尊心の所在（何を守ろうとして攻撃的になっているか）")

class WarheadCOA(BaseModel):
    coa_type: str = Field(description="作戦案の種類 ('O-1 徹甲弾', 'O-2 EMP弾', 'O-3 照明弾')")
    nazokake_text: str = Field(description="なぞかけ本文（必ず『〇〇とかけて、××と解く。その心は、どちらも△△でしょう』の形式。かつ△△に指揮官自身の自虐を含むこと）")
    tactical_intent: str = Field(description="この弾頭の狙い・メタ認知誘発のメカニズム")
    damage_prediction: str = Field(description="被弾予測（相手がどのように武装解除されるか、あるいは反発するか）")

class WarheadForgingResult(BaseModel):
    coas: List[WarheadCOA] = Field(description="生成された3つの作戦案", min_length=3, max_length=3)

class CommissarAuditResult(BaseModel):
    preachiness_score: float = Field(description="説教臭さ・啓蒙欲求のスコア (0.0〜1.0)。高いほど上から目線。", ge=0.0, le=1.0)
    warning_message: str = Field(description="スコアに応じたコミッサールAIからの耳の痛い警告文（トースト通知用）")
