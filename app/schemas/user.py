from pydantic import BaseModel

class UserCreate(BaseModel):
    name: str
    phone: str
    status_pernikahan: str
    budget_min: int
    budget_max: int
    lokasi: str
