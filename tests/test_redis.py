import asyncio
import os
import sys

# Ensure project root is on sys.path when running this script directly
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.config import settings
import redis.asyncio as redis


async def main() -> int:
    dsn = settings.redis.dsn
    print(f"Redis DSN: {dsn}")
    try:
        client = redis.from_url(dsn, encoding="utf-8", decode_responses=True)
        pong = await client.ping()
        print(f"PING result: {pong}")
        await client.close()
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
