from pydantic import BaseModel

class ChatHistory(BaseModel):
    is_user: str
    session: str
    message: str
    read: str
    replied: str
