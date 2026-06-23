# Singgah Backend API

Backend for **Singgah SmartAdvisor** — a chat-based AI assistant that helps users find kost and kontrakan (rental houses) across multiple Indonesian property platforms at once.

Built with **FastAPI** + **Selenium** (headless Chromium) + **OpenRouter LLM**.

## Features

- Natural-language chat via the Mbok Yem persona
- Parallel scraping from Rumah123, Pinhome, Lamudi, Mamikost, and 99.co
- AI intent classification, location expansion, and recommendation text
- Budget, location, and property-type filtering
- Docker + Docker Compose support

## Project Structure

```
singgah-backend/
├── main.py                    # FastAPI entry point
├── Dockerfile                 # Backend container
├── docker-compose.yml         # Local orchestration
├── deploy.bat / deploy.sh     # Deployment scripts
├── .env.example               # Local env template
├── .env.production            # Production env template
├── requirements.txt
├── app/
│   ├── agents/                # Property scrapers (Rumah123, Pinhome, Lamudi, Mamikost, 99.co)
│   ├── controllers/           # inbound_controller, orchestrator_controller, user_controller
│   ├── services/              # HousingAgent orchestrator
│   ├── models/                # User, Chat, SavedProperty
│   ├── schemas/               # Pydantic schemas
│   ├── routes/                # API routes
│   ├── db/                    # SQLAlchemy setup
│   └── core/                  # Settings & prompt config
└── prompts_config.yaml        # LLM prompts
```

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | MySQL connection string |
| `API_KEY` | OpenRouter API key |
| `LLM_MODEL` | LLM model, e.g. `openai/gpt-3.5-turbo` |
| `LLM_URL` | OpenRouter API URL |
| `PROJECT_NAME` | App name |
| `CORS_ORIGINS` | Comma-separated allowed origins (`*` for local dev) |

See `.env.example` (local) and `.env.production` (production) for templates.

## Local Development

```bash
pip install -r requirements.txt

# Create .env from the local template
cp .env.example .env
# Edit .env with your API key and database credentials

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Server runs at `http://localhost:8000`.

## Docker Deployment

### Local

```bash
# From singgah-backend
cp .env.example .env
# Fill in .env
docker compose up -d --build
```

### Production

1. Copy `.env.production` to `.env` and fill in the real secrets.
2. Set `CORS_ORIGINS=https://your-frontend-domain.com`.
3. Deploy the backend container (e.g. via Docker Compose, Kubernetes, or a VPS).
4. Ensure the MySQL database is reachable from the container.

Example production build:

```bash
docker build -t singgah-backend .
docker run -d --name singgah-backend --env-file .env -p 8000:8000 singgah-backend
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/message/send` | Send a chat message |
| `POST` | `/message/property-detail` | Get full property details |
| `POST` | `/message/save-property` | Save a favorite property |
| `GET`  | `/message/history/{session_id}` | Chat history |
| `GET`  | `/message/saved/{session_id}` | Saved properties |
| `POST` | `/user/register` | Register or update user profile |
| `GET`  | `/user/{session_id}` | Get user data |

**Example `/message/send` request:**

```json
{
  "session": "user-abc-123",
  "message": "Mbok, cari kost di Jakarta Selatan budget 1.5 juta",
  "is_user": "Y",
  "replied": "N",
  "read": "N",
  "language": "id"
}
```

## Data Sources

- **Rumah123**
- **Pinhome**
- **Lamudi**
- **Mamikost**
- **99.co**

## Notes

- Selenium uses a headless Chromium instance; make sure the server has enough RAM.
- Set `CORS_ORIGINS` to your frontend domain in production. `*` is fine for local development only.
- Database tables are created automatically on startup.
- WhatsApp notifications are optional; if WA credentials are not set, the feature is skipped.
