"""Prepare a reviewed schema separately from starting a blue/green instance."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings
from tortoise import Tortoise
from services.startup import check_database_schema, initialize_database


async def run(apply):
    await Tortoise.init(db_url=settings.DATABASE_URL, modules={
        'models':['auth.models','models.config','models.usage_record']}, timezone=settings.TIMEZONE)
    try:
        if apply:
            await initialize_database()
        await check_database_schema()
        print('Mapped database schema is ready.')
    finally:
        await Tortoise.close_connections()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true', help='Only after reviewing backward compatibility and backup')
    asyncio.run(run(parser.parse_args().apply))
