import logging
import httpx

logger = logging.getLogger(__name__)

WA_GW_URL = "https://wagw.cvmedandigitalinovasi.com"
WA_TOKEN = "xxjeTURtRoAOHthVorlPPxeOZaifsE"
WA_SENDER = "6282276648478"
OWNER_NUMBER = "6282276648478"


def _normalize_phone(phone: str) -> str:
    phone = str(phone).strip()
    if phone.startswith("0"):
        phone = "62" + phone[1:]
    elif phone.startswith("+"):
        phone = phone[1:]
    return phone


async def _send_text(client: httpx.AsyncClient, number: str, message: str) -> bool:
    try:
        resp = await client.post(
            f"{WA_GW_URL}/send-message",
            json={
                "api_key": WA_TOKEN,
                "sender": WA_SENDER,
                "number": number,
                "message": message,
            },
            timeout=15,
        )
        logger.info("[WA] send-message to %s status=%s", number, resp.status_code)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("[WA] send-message failed: %s", e)
        return False


async def _send_media(
    client: httpx.AsyncClient,
    number: str,
    caption: str,
    media_url: str,
    media_type: str = "image",
) -> bool:
    try:
        resp = await client.post(
            f"{WA_GW_URL}/send-media",
            json={
                "api_key": WA_TOKEN,
                "sender": WA_SENDER,
                "number": number,
                "media_type": media_type,
                "caption": caption,
                "url": media_url,
            },
            timeout=15,
        )
        logger.info("[WA] send-media to %s status=%s", number, resp.status_code)
        return resp.status_code == 200
    except Exception as e:
        logger.warning("[WA] send-media failed: %s", e)
        return False


async def notify_property_saved(
    visitor_name: str,
    visitor_phone: str,
    property_data: dict,
) -> dict:
    """Send WA notifications to owner and visitor when a property is saved."""
    visitor_number = _normalize_phone(visitor_phone)
    nama = property_data.get("nama_tempat", "-")
    tipe = property_data.get("tipe", "-")
    harga = property_data.get("harga", "-")
    lokasi = property_data.get("lokasi", "-")
    sumber = property_data.get("sumber", "-")
    url = property_data.get("url", "")
    image = property_data.get("image", "")

    owner_caption = (
        f"📌 *Properti Baru Disimpan*\n\n"
        f"👤 *Pengunjung:* {visitor_name}\n"
        f"📞 *No. WA:* {visitor_phone}\n\n"
        f"🏠 *Properti:* {nama}\n"
        f"🏷️ *Tipe:* {tipe}\n"
        f"💰 *Harga:* {harga}\n"
        f"📍 *Lokasi:* {lokasi}\n"
        f"🌐 *Sumber:* {sumber}\n"
        f"🔗 *Link:* {url if url else '-'}"
    )

    visitor_caption = (
        f"Halo Kak *{visitor_name}*! 👋\n\n"
        f"Terima kasih sudah menyimpan properti berikut melalui *Singgah*:\n\n"
        f"🏠 *{nama}*\n"
        f"🏷️ {tipe} — {harga}\n"
        f"📍 {lokasi}\n\n"
        f"Tim kami akan segera menghubungi Kakak untuk informasi lebih lanjut terkait properti ini. "
        f"Ditunggu ya Kak! 😊"
    )

    results = {"owner_sent": False, "visitor_sent": False}

    async with httpx.AsyncClient() as client:
        if image:
            results["owner_sent"] = await _send_media(client, OWNER_NUMBER, owner_caption, image)
        else:
            results["owner_sent"] = await _send_text(client, OWNER_NUMBER, owner_caption)

        if visitor_number and visitor_number != _normalize_phone(OWNER_NUMBER):
            if image:
                results["visitor_sent"] = await _send_media(client, visitor_number, visitor_caption, image)
            else:
                results["visitor_sent"] = await _send_text(client, visitor_number, visitor_caption)

    return results
