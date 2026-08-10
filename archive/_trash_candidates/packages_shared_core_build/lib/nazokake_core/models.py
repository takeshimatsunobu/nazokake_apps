from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class TriggerStateORM(Base):
    __tablename__ = 'trigger_states'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger_name = Column(String, unique=True, nullable=False)
    # 負債解消: String型での保存を廃止し、DateTime型で厳密な比較を担保する
    last_triggered_at = Column(DateTime, nullable=True)

class ResearchArticleORM(Base):
    __tablename__ = 'research_articles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    # 負債解消: 文字列比較による時限爆弾を排除
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
