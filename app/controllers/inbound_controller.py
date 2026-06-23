import asyncio
import logging
from datetime import datetime
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
from app.models.chat import History
from app.models.saved_property import SavedProperty
from app.schemas.chat import ChatHistory
from app.schemas.property import SavePropertyRequest
from app.controllers.user_controller import get_user
from app.controllers.orchestrator_controller import (
    greetingsMessage, checkRecomendatationResultMessage,
    consultationMessages, checkIntenMessage, recommendationMessages,
    extractSearchParams
)
from app.services.agent import HousingAgent, sanitize_text
from app.services.wa_service import notify_property_saved
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
    logger.info("Intent: %s", intent)
    get_user_data = get_user(db, data.session)
    response = {}

    if intent == "rekomendasi":
        agent = HousingAgent()
        search_params = extractSearchParams(data.message, get_user_data or {}, language)
        try:
            response = await agent.run(
                user_message=data.message,
                user_info=search_params,
                language=language,
            )
        except Exception as e:
            logger.exception("Agent scraping failed: %s, falling back to LLM", e)
            details = {
                'message': data.message,
                'user_information': get_user_data
            }
            llm_response = sanitize_text(recommendationMessages(json.dumps(details), language))
            logger.info("rekomendasi (fallback): %s", llm_response)
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
            check_result = sanitize_text(checkRecomendatationResultMessage(json.dumps(details_check), language))

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
        consultation = sanitize_text(consultationMessages(json.dumps(details), language))
        response = {
            "rc": "200",
            "messages": [line for line in consultation.splitlines() if line.strip()],
            "is_product": False,
            "product": []
        }
    else:
        response = {
            "rc": "200",
            "messages": [line for line in sanitize_text(greetingsMessage(data.message, language)).splitlines() if line.strip()],
            "is_product": False,
            "product": []
        }

    logger.info("[FINAL RESPONSE] %s", json.dumps(response, ensure_ascii=False, default=str))
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
        "property_type": detail.property_type,
        "bedrooms": detail.bedrooms,
        "bathrooms": detail.bathrooms,
        "land_area": detail.land_area,
        "building_area": detail.building_area,
        "facilities": detail.facilities,
    }

async def save_property(db: Session, data: SavePropertyRequest):
    user = get_user(db, data.session)
    visitor_name = (user or {}).get("name", "Pengunjung") if isinstance(user, dict) else (
        getattr(user, "name", "Pengunjung") if user else "Pengunjung"
    )
    visitor_phone = (user or {}).get("phone", "") if isinstance(user, dict) else (
        getattr(user, "phone", "") if user else ""
    )

    record = SavedProperty(
        session=data.session,
        nama_tempat=data.nama_tempat,
        tipe=data.tipe,
        harga=data.harga,
        lokasi=data.lokasi,
        sumber=data.sumber,
        url=data.url,
        image=data.image,
        saved_at=datetime.now(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    wa_results = {"owner_sent": False, "visitor_sent": False}
    if visitor_phone:
        try:
            wa_results = await notify_property_saved(
                visitor_name=visitor_name,
                visitor_phone=visitor_phone,
                property_data=data.model_dump(),
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("WA notify failed: %s", e)

    return {
        "rc": "200",
        "message": "Properti berhasil disimpan",
        "id": record.id,
        "wa_owner_sent": wa_results.get("owner_sent", False),
        "wa_visitor_sent": wa_results.get("visitor_sent", False),
    }


def get_saved_properties(db: Session, session: str):
    records = db.query(SavedProperty).filter(SavedProperty.session == session).order_by(SavedProperty.saved_at.desc()).all()
    return [
        {
            "id": r.id,
            "nama_tempat": r.nama_tempat,
            "tipe": r.tipe,
            "harga": r.harga,
            "lokasi": r.lokasi,
            "sumber": r.sumber,
            "url": r.url,
            "image": r.image,
            "saved_at": r.saved_at.isoformat() if r.saved_at else None,
        }
        for r in records
    ]


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
