from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.schemas.chat import ChatHistory
from app.controllers.inbound_controller import (
    send_message, delete_message, update_message, get_chat_history_by_session,
    get_property_detail, save_property, get_saved_properties
)
from app.schemas.property import SavePropertyRequest
from app.db.session import get_db
import json

router = APIRouter(prefix="/message")

@router.post("/send")
async def send_message_route(data: ChatHistory, db: Session = Depends(get_db)):
    return await send_message(db, data)

@router.delete("/delete/{message_id}")
def delete_message_route(message_id: int, db: Session = Depends(get_db)):
    success = delete_message(db, message_id)
    if not success:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"detail": "Message deleted successfully"}

@router.put("/update/{message_id}")
def update_message_route(message_id: int, data: ChatHistory, db: Session = Depends(get_db)):
    updated = update_message(db, message_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found")
    return updated

@router.get("/history/{session_id}")
def get_history_route(session_id: str, db: Session = Depends(get_db)):
    history = get_chat_history_by_session(db, session_id)
    return history

@router.post("/property-detail")
async def property_detail_route(data: dict):
    return await get_property_detail(data.get("url", ""), data.get("source", ""))

@router.post("/save-property")
async def save_property_route(data: SavePropertyRequest, db: Session = Depends(get_db)):
    return await save_property(db, data)


@router.get("/saved/{session_id}")
def get_saved_route(session_id: str, db: Session = Depends(get_db)):
    return get_saved_properties(db, session_id)


@router.websocket("/ws/send")
async def websocket_send_message(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            data_dict = json.loads(data)
            chat_data = ChatHistory(**data_dict)
            with next(get_db()) as db:
                response = await send_message(db, chat_data)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        pass
