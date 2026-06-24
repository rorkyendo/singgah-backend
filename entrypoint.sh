#!/bin/sh
set -e

# Run database migration (create tables if they do not exist).
python - <<'PY'
from app.db.base import Base
from app.db.session import engine
import app.models.saved_property  # noqa: F401 — registers table with Base.metadata

print("Running database migration...")
Base.metadata.create_all(bind=engine)
print("Database migration completed.")
PY

# Start the FastAPI server.
exec uvicorn main:app --host 0.0.0.0 --port 8000
