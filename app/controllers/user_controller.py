import uuid
from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.user import UserCreate

def create_user(db: Session, data: UserCreate):
    existing_user = db.query(User).filter(User.phone == data.phone).first()
    if existing_user:
        existing_user.name = data.name
        existing_user.status_pernikahan = data.status_pernikahan
        existing_user.budget_min = data.budget_min
        existing_user.budget_max = data.budget_max
        existing_user.lokasi = data.lokasi
        db.commit()
        db.refresh(existing_user)
        return {"session": existing_user.session}

    session_id = str(uuid.uuid4())
    user = User(
        session=session_id,
        name=data.name,
        phone=data.phone,
        status_pernikahan=data.status_pernikahan,
        budget_min=data.budget_min,
        budget_max=data.budget_max,
        lokasi=data.lokasi
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"session": session_id}

def get_user(db: Session, session_id: str):
    user = db.query(User).filter(User.session == session_id).first()
    if not user:
        return None
    return {
        "session": user.session,
        "name": user.name,
        "phone": user.phone,
        "status_pernikahan": user.status_pernikahan,
        "budget_min": user.budget_min,
        "budget_max": user.budget_max,
        "lokasi": user.lokasi
    }
