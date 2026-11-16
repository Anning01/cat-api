"""Switch a prepared Caddy release without stopping either API process.

Host-specific configs/backups belong outside Git. Schema compatibility must be
reviewed before this tool is used; it never applies migrations or retries jobs.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlsplit

import httpx


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def readable(path, user):
    if pwd.getpwnam(user).pw_uid == os.geteuid():
        if not os.access(path, os.R_OK):
            raise RuntimeError('Web user cannot read a public asset')
    else:
        run('sudo', '-n', '-u', user, '--', 'test', '-r', str(path))


def preflight(root, commit, web_user):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a full Git commit')
    if run('git', '-C', str(root), 'rev-parse', 'HEAD').stdout.strip() != commit:
        raise RuntimeError('Candidate Git version differs')
    if run('git', '-C', str(root), 'rev-parse', 'origin/main').stdout.strip() != commit:
        raise RuntimeError('Candidate does not match fetched origin/main')
    if run('git', '-C', str(root), 'status', '--porcelain').stdout:
        raise RuntimeError('Candidate checkout is not clean')
    assets = root / 'web/dist'
    if (assets / '.build-commit').read_text().strip() != commit:
        raise RuntimeError('Frontend build version differs')
    for path in assets.rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Unexpected symlink in public build')
        if path.is_file():
            readable(path, web_user)
    readable(assets / 'index.html', web_user)


def ready(client, origin):
    response = client.get(origin.rstrip('/') + '/api/health/ready', headers={'Cache-Control':'no-cache'})
    response.raise_for_status()
    data = response.json()
    if data.get('status') != 'ready':
        raise RuntimeError('API instance is not ready')
    return data


def verify_public(client, origin, commit, instance):
    status = ready(client, origin)
    if status.get('release') != commit or status.get('instance') != instance:
        raise RuntimeError('Public API has not switched to candidate')
    version = client.get(origin.rstrip('/') + '/.build-commit', headers={'Cache-Control':'no-cache'})
    version.raise_for_status()
    if version.text.strip() != commit:
        raise RuntimeError('Public frontend version differs')
    home = client.get(origin)
    home.raise_for_status()
    for asset in re.findall(r'(?:src|href)="([^" ]+\.(?:js|css))"', home.text):
        url = urljoin(origin.rstrip('/')+'/', asset)
        if urlsplit(url).netloc != urlsplit(origin).netloc:
            continue
        client.get(url).raise_for_status()


def atomic_write(path, data):
    mode = path.stat().st_mode & 0o777
    fd, temporary = tempfile.mkstemp(prefix='.release-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data);out.flush();os.fsync(out.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def switch(root, commit, candidate_url, public_url, candidate_config, active_config,
           state_dir, web_user, caddy='caddy', admin='localhost:2019', timeout=30):
    """Only switch routing. Old processes and their in-flight work remain alive."""
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir/'switch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(root, commit, web_user)
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            candidate_status = ready(client, candidate_url)
            if candidate_status.get('release') != commit or not candidate_status.get('instance'):
                raise RuntimeError('Candidate API version differs')
            if candidate_status.get('startup_migrations') is not False:
                raise RuntimeError('Candidate must disable startup migrations')
            previous_status = ready(client, public_url)
            run(caddy, 'validate', '--config', str(candidate_config), '--adapter', 'caddyfile')
            previous = active_config.read_bytes()
            replacement = candidate_config.read_bytes()
            backup = state_dir / f'before-{time.time_ns()}.caddy'
            with backup.open('xb') as out:
                os.chmod(backup, 0o600);out.write(previous)
            with (state_dir/'reload.log').open('ab') as log:
                os.chmod(state_dir/'reload.log',0o600)
                started = time.monotonic()
                try:
                    atomic_write(active_config, replacement)
                    reload = subprocess.Popen([caddy,'reload','--config',str(active_config),
                        '--adapter','caddyfile','--address',admin],stdout=log,stderr=subprocess.STDOUT)
                    deadline = time.monotonic()+timeout
                    while True:
                        try:
                            verify_public(client, public_url, commit, candidate_status['instance'])
                            break
                        except (httpx.HTTPError, ValueError, RuntimeError):
                            if reload.poll() not in (None,0) or time.monotonic() >= deadline:
                                raise RuntimeError('Cutover verification failed') from None
                            time.sleep(0.2)
                except Exception:
                    atomic_write(active_config, previous)
                    rollback = subprocess.Popen([caddy,'reload','--config',str(active_config),
                        '--adapter','caddyfile','--address',admin],stdout=log,stderr=subprocess.STDOUT)
                    if rollback.wait(timeout=1350) != 0:
                        raise RuntimeError('Rollback needs operator attention; keep both API processes running') from None
                    restored = ready(client, public_url)
                    if (restored.get('release'),restored.get('instance')) != (previous_status.get('release'),previous_status.get('instance')):
                        raise RuntimeError('Previous route could not be verified; keep both API processes running') from None
                    raise RuntimeError('Routing restored to previous release; neither API process was stopped') from None
                print(json.dumps({'status':'switched','commit':commit,'old_process_kept':True,
                                  'verified_ms':round((time.monotonic()-started)*1000)}),flush=True)
                # Waiting here does not block new public traffic. Never kill the old API.
                try:
                    code = reload.wait(timeout=1350)
                except subprocess.TimeoutExpired:
                    raise RuntimeError('New route is live; reload cleanup needs attention. Keep both API processes running') from None
                if code != 0:
                    raise RuntimeError('New route was verified but reload reported failure; inspect before stopping either API')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','commit','candidate-url','public-url','candidate-config','active-config','state-dir','web-user'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--caddy',default='caddy')
    parser.add_argument('--admin',default='localhost:2019')
    args=vars(parser.parse_args())
    for name in ('root','candidate_config','active_config','state_dir'):args[name]=Path(args[name]).resolve()
    switch(**args)
