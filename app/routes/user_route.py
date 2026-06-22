from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.schemas.user import UserCreate
from app.controllers.user_controller import create_user, get_user
from app.db.session import get_db

router = APIRouter(prefix="/user")

@router.post("/create")
def register_user_route(data: UserCreate, db: Session = Depends(get_db)):
    return create_user(db, data)

@router.get("/id/{session_id}")
def get_user_route(session_id: str, db: Session = Depends(get_db)):
    userInfo = get_user(db, session_id)
    return userInfo
