from sqlalchemy import Column, Integer, String, Text, DateTime
from app.db.base import Base
from datetime import datetime


class SavedProperty(Base):
    __tablename__ = "sg_saved_properties"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session = Column(String(36), index=True)
    nama_tempat = Column(String(255))
    tipe = Column(String(50))
    harga = Column(String(100))
    lokasi = Column(String(255))
    sumber = Column(String(100))
    url = Column(Text)
    image = Column(Text)
    saved_at = Column(DateTime, default=datetime.now)
