import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.chat import History
from app.schemas.chat import ChatHistory
from app.controllers.user_controller import get_user
from app.controllers.orchestrator_controller import (
    greetingsMessage, checkRecomendatationResultMessage,
    consultationMessages, checkIntenMessage, recommendationMessages
)
from app.services.agent import HousingAgent
import json

async def send_message(db: Session, data: ChatHistory):
    Now = datetime.now()
    history = History(
        session=data.session,
        is_user=data.is_user,
        message=data.message,
        replied=data.replied,
        read=data.read,
        chattime=Now
    )
    db.add(history)
    db.commit()
    db.refresh(history)

    language = data.language or "id"
    intent = checkIntenMessage(data.message, language)
    print("Intent: ", intent)
    get_user_data = get_user(db, data.session)
    response = {}

    if intent == "rekomendasi":
        agent = HousingAgent()
        try:
            response = await agent.run(
                user_message=data.message,
                user_info=get_user_data or {},
                language=language,
            )
        except Exception as e:
            print(f"Agent scraping failed: {e}, falling back to LLM")
            details = {
                'message': data.message,
                'user_information': get_user_data
            }
            llm_response = recommendationMessages(json.dumps(details), language)
            print("rekomendasi (fallback): " + llm_response)
            tempat_list = llm_response.split(",")

            products = []
            for tempat in tempat_list:
                tempat_name = tempat.strip()
                product = {
                    "nama_tempat": tempat_name,
                    "tipe": "Kost" if "kost" in tempat_name.lower() else "Kontrakan",
                    "harga": "Sesuai budget",
                    "lokasi": get_user_data.get("lokasi", "") if get_user_data else ""
                }
                products.append(product)

            details_check = {
                'tempat_rekomendasi': [{"nama": p["nama_tempat"], "tipe": p["tipe"]} for p in products],
                'user_information': get_user_data
            }
            check_result = checkRecomendatationResultMessage(json.dumps(details_check), language)

            response = {
                "rc": "200",
                "messages": [line for line in check_result.splitlines() if line.strip()],
                "is_product": True,
                "product": products
            }
    elif intent == "konsultasi":
        details = {
            'message': data.message,
            'user_information': get_user_data
        }
        consultation = consultationMessages(json.dumps(details), language)
        response = {
            "rc": "200",
            "messages": [line for line in consultation.splitlines() if line.strip()],
            "is_product": False,
            "product": []
        }
    else:
        response = {
            "rc": "200",
            "messages": [line for line in greetingsMessage(data.message, language).splitlines() if line.strip()],
            "is_product": False,
            "product": []
        }

    print(response)
    return response

async def get_property_detail(url: str, source: str):
    agent = HousingAgent()
    detail = await agent.get_detail(url, source)
    return {
        "rc": "200",
        "title": detail.title,
        "price": detail.price,
        "location": detail.location,
        "description": detail.description,
        "images": detail.images,
        "source": detail.source,
        "url": detail.url,
    }

def delete_message(db: Session, message_id: int):
    history = db.query(History).filter(History.chat_id == message_id).first()
    if history:
        db.delete(history)
        db.commit()
        return True
    return False

def update_message(db: Session, message_id: int, data: ChatHistory):
    history = db.query(History).filter(History.chat_id == message_id).first()
    if not history:
        return None
    history.message = data.message
    history.replied = data.replied
    history.read = data.read
    history.session = data.session
    db.commit()
    db.refresh(history)
    return history

def get_chat_history_by_session(db: Session, session_id: str):
    return db.query(History).filter(History.session == session_id).order_by(History.chattime.asc()).all()
