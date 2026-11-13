import subprocess
import sys
import os


def test_standalone_startup_and_route_boundaries(tmp_path):
    script = """
from fastapi.testclient import TestClient
from main import app
for _ in range(2):
    with TestClient(app) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/api/auth/status').json()['data']['deployment_role'] == 'platform'
        assert client.get('/v1/models').status_code == 401
        assert '/chat/completions' in client.get('/v1/openapi.json').json()['paths']
        assert client.get('/api/novel').json()['code'] == 404
"""
    subprocess.run([sys.executable, "-c", script], check=True, env={
        **os.environ, "DATABASE_URL": f"sqlite://{tmp_path / 'test.db'}",
        "AUTH_PROVIDER": "password", "SUPER_ADMIN_USERNAME": "", "SUPER_ADMIN_PASSWORD": "",
    })
