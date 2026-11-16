import concurrent.futures
import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from scripts.switch_release import switch


def test_candidate_startup_does_not_run_migrations_and_rejects_missing_schema(tmp_path):
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':f'sqlite://{tmp_path / "app.db"}',
         'AUTH_PROVIDER':'password','SUPER_ADMIN_USERNAME':'','SUPER_ADMIN_PASSWORD':'',
         'STARTUP_MIGRATIONS_ENABLED':'false','DEPLOYMENT_DRAIN_FILE':str(tmp_path/'candidate-drain')}
    subprocess.run([sys.executable,'scripts/migrate.py','--apply'],cwd=root,env=env,check=True,capture_output=True)
    code='''
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
with patch('services.startup.initialize_database',side_effect=AssertionError('candidate executed DDL')) as migrate:
    with TestClient(app) as client:
        r=client.get('/api/health/ready')
        assert r.status_code==200 and len(r.json()['release'])==40
    migrate.assert_not_called()
'''
    subprocess.run([sys.executable,'-c',code],cwd=root,env=env,check=True,capture_output=True)
    import sqlite3
    with sqlite3.connect(tmp_path/'app.db') as c:
        c.execute('ALTER TABLE ai_model_configs DROP COLUMN reasoning_effort')
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True)
    assert result.returncode!=0 and b'reasoning_effort' in result.stderr
    with sqlite3.connect(tmp_path/'app.db') as c:
        assert 'reasoning_effort' not in [r[1] for r in c.execute('PRAGMA table_info(ai_model_configs)')]


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL).decode().strip()


class Instance:
    def __init__(self,release):
        self.release=release;self.ready=True;self.submissions=[];self.finish=threading.Event()
        self.instance=uuid4().hex
        self.startup_migrations=False
        self.old_stream_started=threading.Event()
        instance=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def reply(self,body,status=200):
                raw=json.dumps(body).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                self.reply({'status':'ready' if instance.ready else 'draining','release':instance.release,
                            'instance':instance.instance,'startup_migrations':instance.startup_migrations},200 if instance.ready else 503)
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0'))).decode()
                instance.submissions.append(body)
                if self.path!='/stream':return self.reply({'accepted':True,'release':instance.release})
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Transfer-Encoding','chunked');self.end_headers()
                def chunk(data):
                    self.wfile.write(f'{len(data):x}\r\n'.encode()+data+b'\r\n');self.wfile.flush()
                chunk(b'data: first\n\n');instance.old_stream_started.set()
                instance.finish.wait(20)
                chunk(b'data: last\n\ndata: [DONE]\n\n');self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def close(self):
        self.finish.set();self.server.shutdown();self.server.server_close();self.thread.join()


@pytest.fixture
def setup_switch(tmp_path):
    binary=os.environ.get('CADDY_TEST_BINARY')
    if not binary:pytest.skip('Set CADDY_TEST_BINARY to run real Caddy cutover tests')
    root=tmp_path/'candidate';root.mkdir()
    git(root,'init','-b','main');(root/'.gitignore').write_text('web/dist/\n')
    (root/'README.md').write_text('synthetic candidate')
    git(root,'add','.');git(root,'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
    bare=tmp_path/'origin.git';subprocess.run(['git','init','--bare',str(bare)],check=True,capture_output=True)
    git(root,'remote','add','origin',str(bare));git(root,'push','-u','origin','main')
    commit=git(root,'rev-parse','HEAD')
    assets=root/'web/dist';(assets/'assets').mkdir(parents=True)
    (assets/'index.html').write_text('<script src="/assets/app.js"></script>')
    (assets/'assets/app.js').write_text('// candidate asset')
    (assets/'.build-commit').write_text(commit)
    old_assets=tmp_path/'old-assets';old_assets.mkdir();(old_assets/'index.html').write_text('old')
    (old_assets/'.build-commit').write_text('0'*40)
    old=Instance('0'*40);new=Instance(commit)
    public_port,admin_port=port(),port();origin=f'http://127.0.0.1:{public_port}'
    active=tmp_path/'active.caddy';candidate=tmp_path/'candidate.caddy'
    def config(instance,static):
        return f'''{{
 admin 127.0.0.1:{admin_port}
 auto_https off
 persist_config off
 storage file_system {{
  root "{tmp_path / 'caddy-storage'}"
 }}
}}
{origin} {{
 @api path /api/* /generate /stream
 handle @api {{
  reverse_proxy {instance.url} {{
   stream_close_delay 660s
  }}
 }}
 handle {{
  root * "{static}"
  file_server
 }}
}}
'''
    active.write_text(config(old,old_assets));candidate.write_text(config(new,assets))
    log=(tmp_path/'caddy.log').open('w')
    process=subprocess.Popen([binary,'run','--config',str(active),'--adapter','caddyfile'],stdout=log,stderr=subprocess.STDOUT)
    args=dict(root=root,commit=commit,candidate_url=new.url,public_url=origin,candidate_config=candidate,
              active_config=active,state_dir=tmp_path/'state',web_user=getpass.getuser(),caddy=binary,
              admin=f'127.0.0.1:{admin_port}',timeout=1)
    try:
        with httpx.Client(timeout=1,trust_env=False) as client:
            for _ in range(100):
                if process.poll() is not None:pytest.fail((tmp_path/'caddy.log').read_text())
                try:
                    if client.get(origin+'/api/health/ready').status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(0.05)
            else:pytest.fail('Isolated Caddy failed to start')
        yield args,old,new,config,old_assets
    finally:
        old.finish.set();new.finish.set()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        log.close();old.close();new.close()


def test_new_requests_succeed_before_old_stream_finishes(setup_switch):
    args,old,new,_,_=setup_switch
    with httpx.Client(timeout=10,trust_env=False) as client, concurrent.futures.ThreadPoolExecutor() as pool:
        with client.stream('POST',args['public_url']+'/stream',content='old-job') as response:
            lines=response.iter_lines();assert next(lines)=='data: first'
            future=pool.submit(switch,**args)
            start=time.monotonic()
            while client.get(args['public_url']+'/api/health/ready').json()['release']!=args['commit']:
                assert time.monotonic()-start<5;time.sleep(0.02)
            reply=client.post(args['public_url']+'/generate',content='new-job')
            assert reply.status_code==200 and reply.json()['release']==args['commit']
            assert not old.finish.is_set()
            for _ in range(10):assert client.get(args['public_url']+'/api/health/ready').status_code==200
            old.finish.set()
            rest='\n'.join(lines);assert 'data: last' in rest and 'data: [DONE]' in rest
        future.result(timeout=10)
    assert old.submissions==['old-job'] and new.submissions==['new-job']


@pytest.mark.parametrize('failure',['unready','version','dirty','bad-config','startup-ddl'])
def test_failed_candidate_never_disturbs_old_instance(setup_switch,failure):
    args,old,new,_,_=setup_switch
    original=args['active_config'].read_bytes()
    if failure=='unready':new.ready=False
    elif failure=='version':new.release='f'*40
    elif failure=='dirty':(args['root']/'README.md').write_text('uncommitted')
    elif failure=='startup-ddl':new.startup_migrations=True
    else:args['candidate_config'].write_text('not valid caddy config !!!')
    with pytest.raises(Exception):switch(**args)
    assert args['active_config'].read_bytes()==original
    with httpx.Client(trust_env=False) as client:
        assert client.post(args['public_url']+'/generate',content='still-old').json()['release']==old.release
    assert new.submissions==[]


def test_bad_frontend_after_cutover_restores_previous_route(setup_switch):
    args,old,new,config,old_assets=setup_switch
    original=args['active_config'].read_bytes()
    args['candidate_config'].write_text(config(new,old_assets))
    with pytest.raises(RuntimeError,match='restored'):switch(**args)
    assert args['active_config'].read_bytes()==original
    with httpx.Client(trust_env=False) as client:
        assert client.post(args['public_url']+'/generate',content='rollback-job').json()['release']==old.release
        assert client.get(new.url+'/api/health/ready').status_code==200


def test_same_commit_still_requires_switching_to_the_candidate_instance(setup_switch):
    args,old,new,config,old_assets=setup_switch
    old.release=args['commit'];(old_assets/'.build-commit').write_text(args['commit'])
    args['candidate_config'].write_text(config(old,old_assets))
    with pytest.raises(RuntimeError,match='restored'):switch(**args)
    assert old.instance!=new.instance and new.submissions==[]


def test_real_app_cutover_preserves_stream_and_shared_billing_once(setup_switch,tmp_path):
    import sqlite3
    args,_,_,config,old_assets=setup_switch
    project=Path(__file__).resolve().parents[1]
    db=tmp_path/'shared.db';release=tmp_path/'finish-old';submissions=tmp_path/'provider-submissions'
    env={**os.environ,'PYTHONPATH':str(project),'DATABASE_URL':f'sqlite://{db}',
         'AUTH_PROVIDER':'password','SUPER_ADMIN_USERNAME':'','SUPER_ADMIN_PASSWORD':'',
         'STARTUP_MIGRATIONS_ENABLED':'false','BLUE_GREEN_TEST_RELEASE':str(release),
         'BLUE_GREEN_TEST_SUBMISSIONS':str(submissions)}
    subprocess.run([sys.executable,'scripts/migrate.py','--apply'],cwd=project,env=env,check=True,capture_output=True)
    seed='''
import asyncio,os
from tortoise import Tortoise
from auth.models import User,UserWallet,PlatformApiKey
from auth.security import hash_token
from models.config import AiModelConfig
async def main():
 await Tortoise.init(db_url=os.environ['DATABASE_URL'],modules={'models':['auth.models','models.config','models.usage_record']})
 user=await User.create(username='isolated-blue-green')
 await UserWallet.create(user=user,balance=20)
 await PlatformApiKey.create(user=user,name='test',token_hash=hash_token('nv_blue_green_synthetic'),preview='test')
 await AiModelConfig.create(name='shared-model',model='shared-model',task_type=7,concurrency=4,is_active=True,base_url='https://synthetic.invalid',api_key='test',pricing={'type':'text','input_price_per_1m':1,'output_price_per_1m':2})
 await Tortoise.close_connections()
asyncio.run(main())
'''
    subprocess.run([sys.executable,'-c',seed],cwd=project,env=env,check=True,capture_output=True)
    processes=[];logs=[];instances={}
    try:
        for slot,sha in [('old','0'*40),('new',args['commit'])]:
            number=port();instances[slot]=f'http://127.0.0.1:{number}'
            log=(tmp_path/(slot+'.log')).open('w');logs.append(log)
            processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','blue_green_server:app',
                '--app-dir',str(project/'test/fixtures'),'--host','127.0.0.1','--port',str(number),
                '--timeout-graceful-shutdown','5'],cwd=project,env={**env,'BLUE_GREEN_TEST_SLOT':slot,
                    'BLUE_GREEN_TEST_SHA':sha,'DEPLOYMENT_DRAIN_FILE':str(tmp_path/(slot+'-drain'))},stdout=log,stderr=subprocess.STDOUT))
        with httpx.Client(timeout=10,trust_env=False) as client, concurrent.futures.ThreadPoolExecutor() as pool:
            for slot in instances:
                for _ in range(100):
                    try:
                        if client.get(instances[slot]+'/api/health/ready').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(0.05)
                else:pytest.fail('Real isolated app did not start')
            # The production config routes /v1/* as well as /api/*.
            def real_config(url,assets):
                return config(SimpleNamespace(url=url),assets).replace('/api/* /generate /stream','/api/* /v1/* /generate /stream')
            args['active_config'].write_text(real_config(instances['old'],old_assets))
            subprocess.run([args['caddy'],'reload','--config',str(args['active_config']),
                '--adapter','caddyfile','--address',args['admin']],check=True,capture_output=True)
            args['candidate_config'].write_text(real_config(instances['new'],args['root']/'web/dist'))
            args['candidate_url']=instances['new'];args['timeout']=5
            endpoint=args['public_url']+'/v1/chat/completions'
            body={'model':'shared-model','messages':[{'role':'user','content':'synthetic'}],'stream':True}
            auth={'Authorization':'Bearer nv_blue_green_synthetic'}
            with client.stream('POST',endpoint,headers={**auth,'Idempotency-Key':'old-job'},json=body) as response:
                assert response.status_code==200
                chunks=response.iter_lines();assert 'first' in next(chunks)
                future=pool.submit(switch,**args)
                for _ in range(100):
                    try:
                        if client.get(args['public_url']+'/api/health/ready').json().get('release')==args['commit']:break
                    except httpx.HTTPError:
                        # A reload can retire an idle keep-alive connection. Only the
                        # read-only readiness probe is retried, never a generation POST.
                        pass
                    time.sleep(0.02)
                else:pytest.fail('Public route did not change')
                duplicate=client.post(endpoint,headers={**auth,'Idempotency-Key':'old-job'},json=body)
                assert duplicate.status_code==409
                new=client.post(endpoint,headers={**auth,'Idempotency-Key':'new-job'},json=body)
                assert new.status_code==200 and '[DONE]' in new.text
                assert not release.exists()
                processes[0].terminate()
                release.touch()
                old='\n'.join(chunks);assert 'last' in old and '[DONE]' in old
            future.result(timeout=10)
        assert processes[0].wait(timeout=10) in (0,-15)
        assert submissions.read_text().splitlines()==['old','new']
        with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as c:
            assert c.execute('select count(*) from model_usage_records').fetchone()[0]==2
            assert c.execute("select count(*) from account_balance_transactions where type='consume'").fetchone()[0]==2
            assert c.execute("select count(*) from account_call_receipts where state='completed'").fetchone()[0]==2
    finally:
        release.touch()
        for process in processes:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        for log in logs:log.close()
