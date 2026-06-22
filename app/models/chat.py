from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db.base import Base

class History(Base):
    __tablename__ = "sg_chat_history"
    chat_id = Column(Integer, primary_key=True, index=True)
    session = Column(
        String(36),
        index=True,
    )
    message = Column(Text, index=True)
    is_user = Column(String(1), index=True)
    read = Column(String(1), index=True)
    replied = Column(String(1), index=True)
    chattime = Column(DateTime, index=True)
