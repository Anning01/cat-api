"""Manage only this checkout's dedicated PostgreSQL instance on localhost:15432."""
import asyncio
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import asyncpg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CLUSTER = ROOT / 'data' / 'postgres-local'
ADMIN_PASSWORD = ROOT / 'data' / '.postgres-local-password'
SOCKET = ROOT / 'data' / 'postgres-socket'
ADMIN = 'cat_api_local_admin'


def binary(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in (Path('/opt/homebrew/opt/postgresql@14/bin'), Path('/usr/local/opt/postgresql@14/bin')):
        if (directory / name).exists():
            return str(directory / name)
    raise SystemExit(f'PostgreSQL tool {name} is not installed. Install PostgreSQL or provide your own DATABASE_URL.')


def configured_database():
    load_dotenv(ROOT / '.env')
    url = urlsplit(os.environ.get('DATABASE_URL', ''))
    if url.scheme not in {'postgres', 'postgresql'}:
        raise SystemExit('Local development requires a PostgreSQL DATABASE_URL; SQLite is not used by this launcher.')
    if (url.hostname, url.port, url.username, url.path) != ('127.0.0.1', 15432, 'cat_api', '/cat_api'):
        return None
    if not url.password or unquote(url.password) == 'change-me':
        raise SystemExit('Set a private local database password in .env before starting PostgreSQL.')
    return url


async def ensure_database(url):
    connection = await asyncpg.connect(host='127.0.0.1', port=15432, database='postgres',
                                       user=ADMIN, password=ADMIN_PASSWORD.read_text().strip())
    try:
        if not await connection.fetchval('SELECT 1 FROM pg_roles WHERE rolname=$1', 'cat_api'):
            password = unquote(url.password).replace("'", "''")
            await connection.execute(f"CREATE ROLE cat_api LOGIN PASSWORD '{password}'")
        if not await connection.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', 'cat_api'):
            await connection.execute('CREATE DATABASE cat_api OWNER cat_api')
    finally:
        await connection.close()
    check = await asyncpg.connect(host='127.0.0.1', port=15432, database='cat_api',
                                  user='cat_api', password=unquote(url.password))
    await check.close()


def main():
    url = configured_database()
    if url is None:
        print('Using the configured external PostgreSQL instance; no local instance managed.')
        return
    command = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if command not in {'start', 'stop', 'status'}:
        raise SystemExit('Usage: local_postgres.py [start|stop|status]')
    pg_ctl = binary('pg_ctl')
    running = subprocess.run([pg_ctl, '-D', str(CLUSTER), 'status'], capture_output=True).returncode == 0
    if command == 'status':
        print('Local PostgreSQL is running.' if running else 'Local PostgreSQL is stopped.')
        return
    if command == 'stop':
        if running:
            subprocess.run([pg_ctl, '-D', str(CLUSTER), '-m', 'fast', '-w', 'stop'], check=True)
        return
    (ROOT / 'data').mkdir(exist_ok=True)
    (ROOT / 'logs').mkdir(exist_ok=True)
    SOCKET.mkdir(exist_ok=True, mode=0o700)
    if not (CLUSTER / 'PG_VERSION').exists():
        if not ADMIN_PASSWORD.exists():
            descriptor = os.open(ADMIN_PASSWORD, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'w') as target:
                target.write(secrets.token_urlsafe(32))
        subprocess.run([binary('initdb'), '-D', str(CLUSTER), '-U', ADMIN,
                        '--pwfile=' + str(ADMIN_PASSWORD), '--auth=scram-sha-256',
                        '--encoding=UTF8', '--locale=C'], check=True)
    if not running:
        subprocess.run([pg_ctl, '-D', str(CLUSTER), '-l', str(ROOT / 'logs' / 'local-postgres.log'),
                        '-o', f'-h 127.0.0.1 -p 15432 -k "{SOCKET}"', '-w', 'start'], check=True)
    asyncio.run(ensure_database(url))
    print('Project PostgreSQL ready on 127.0.0.1:15432 (database cat_api).')


if __name__ == '__main__':
    main()
