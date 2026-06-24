#!/bin/bash
set -e

DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
DB_NAME="${DB_NAME:-singgah_chat}"
DB_USER="${DB_USER:-root}"
DB_HOST="localhost"
DB_PORT="3306"

export DATABASE_URL="mysql+pymysql://${DB_USER}:${DB_ROOT_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

echo "=== Starting MariaDB ==="

# Initialize the MariaDB data directory if it is empty.
if [ -z "$(ls -A /var/lib/mysql)" ]; then
    echo "Initializing MariaDB data directory..."
    mysql_install_db --user=mysql --datadir=/var/lib/mysql > /dev/null 2>&1
fi

# Start MariaDB in the background.
mysqld --user=mysql --datadir=/var/lib/mysql --socket=/var/run/mysqld/mysqld.sock &
MYSQL_PID=$!

# Wait until MariaDB is ready to accept connections (password may be empty or already set).
wait_for_mariadb() {
    local password="$1"
    if [ -z "$password" ]; then
        mysqladmin ping -h "${DB_HOST}" -u root --silent 2>/dev/null
    else
        mysqladmin ping -h "${DB_HOST}" -u root -p"${password}" --silent 2>/dev/null
    fi
}

echo "Waiting for MariaDB to be ready..."
until wait_for_mariadb "" || wait_for_mariadb "${DB_ROOT_PASSWORD}"; do
    sleep 1
done

# If we can connect without a password, set the root password now.
if wait_for_mariadb ""; then
    echo "Setting MariaDB root password..."
    mysql -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASSWORD}'; FLUSH PRIVILEGES;" || true
fi

# Create the application database if it does not exist.
mysql -u root -p"${DB_ROOT_PASSWORD}" -e "CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\`;" || true

echo "=== Running backend migration ==="
python - <<PY
from app.db.base import Base
from app.db.session import engine
import app.models.saved_property  # noqa: F401 — registers table with Base.metadata

print("Creating database tables...")
Base.metadata.create_all(bind=engine)
print("Migration completed.")
PY

echo "=== Starting FastAPI backend ==="
# Keep MariaDB running in the background; if it dies the container will exit.
exec uvicorn main:app --host 0.0.0.0 --port 8000
