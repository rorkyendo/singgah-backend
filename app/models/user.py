from sqlalchemy import Column, String, Float, Integer
from app.db.base import Base
import uuid

class User(Base):
    __tablename__ = "sg_chat_session"
    session = Column(
        String(36),
        primary_key=True,
        index=True,
        unique=True,
        default=lambda: str(uuid.uuid4())
    )
    name = Column(String(25), index=True)
    phone = Column(String(15), unique=True, index=True)
    status_pernikahan = Column(String(15), index=True)
    budget_min = Column(Integer, index=True)
    budget_max = Column(Integer, index=True)
    lokasi = Column(String(100), index=True)
