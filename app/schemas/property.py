from pydantic import BaseModel
from typing import Optional


class SavePropertyRequest(BaseModel):
    session: str
    nama_tempat: str
    tipe: Optional[str] = ""
    harga: Optional[str] = ""
    lokasi: Optional[str] = ""
    sumber: Optional[str] = ""
    url: Optional[str] = ""
    image: Optional[str] = ""
