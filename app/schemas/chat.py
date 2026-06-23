from pydantic import BaseModel, Field

class ChatHistory(BaseModel):
    is_user: str
    session: str
    message: str
    read: str
    replied: str
    language: str = Field(default="id", pattern="^(id|en)$")
