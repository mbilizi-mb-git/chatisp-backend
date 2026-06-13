#!/bin/bash
set -e

echo "=== Starting ChatISP Backend ==="
echo "PORT: $PORT"
echo "DATABASE_URL: $DATABASE_URL"

# Attendre que PostgreSQL soit prêt (max 30 secondes)
echo "Waiting for PostgreSQL..."
timeout=30
counter=0
while ! python -c "
import asyncpg, asyncio, os
async def main():
    await asyncpg.connect(os.environ['DATABASE_URL'].replace('+asyncpg', ''))
asyncio.run(main())
" 2>/dev/null; do
    sleep 1
    counter=$((counter+1))
    if [ $counter -ge $timeout ]; then
        echo "ERROR: PostgreSQL not ready after $timeout seconds"
        exit 1
    fi
done
echo "PostgreSQL is ready."

# Lancer uvicorn
echo "Starting uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1