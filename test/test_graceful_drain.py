import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from auth.deps import AuthContext
from auth.models import BalanceTransaction, PlatformCallReceipt, User, UserWallet
from models.config import AiModelConfig
from models.usage_record import ModelUsageRecord
from services.platform import chat
from services.platform.calls import admit
from config import settings
from test_sdk_contract import sdk_api
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys


class SlowCompletion(httpx.AsyncByteStream):
    def __init__(self, delay):
        self.delay = delay
        self.reads = 0

    async def __aiter__(self):
        self.reads += 1
        yield b'data: {"id":"slow-result","choices":[{"delta":{"content":"first"}}]}\n\n'
        await asyncio.sleep(self.delay)
        yield b'data: {"id":"slow-result","choices":[{"delta":{"content":"last"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
        yield b'data: [DONE]\n\n'


async def make_stream(delay, lifetime):
    user = await User.create(username="drain-test")
    await UserWallet.create(user=user, balance=20)
    config = await AiModelConfig.create(name="drain-test",model="slow-model",task_type=7,is_active=True,
        base_url="https://synthetic.invalid/v1",api_key="synthetic",pricing={"type":"text","input_price_per_1m":1,"output_price_per_1m":2})
    _, receipt = await admit(AuthContext(user=user),f"nv-{config.id}",{},"only-once")
    provider = SlowCompletion(delay)
    client = SimpleNamespace(close=AsyncMock())
    stream = chat.ChatStream(client,httpx.Response(200,stream=provider),receipt,
                             asyncio.get_running_loop().time()+lifetime)
    return stream, provider, client, receipt


async def consume(stream):
    return b"".join([part async for part in stream.body_iterator])


async def test_shutdown_waits_for_valid_slow_stream_and_settles_once():
    # Reproduces the old fixed 15-second background-stream cancellation.
    stream, provider, client, receipt = await make_stream(delay=15.2,lifetime=20)
    reader = asyncio.create_task(consume(stream))
    await chat.stop_streams()
    content = await asyncio.wait_for(reader,timeout=2)
    assert b'"content":"last"' in content and b'"finish_reason":"stop"' in content
    assert content.endswith(b'data: [DONE]\n\n')
    assert provider.reads == 1
    client.close.assert_awaited_once()
    assert (await PlatformCallReceipt.get(id=receipt.id)).state == "completed"
    assert await ModelUsageRecord.all().count() == 1
    assert await BalanceTransaction.filter(type="consume").count() == 1
    assert (await UserWallet.get(user_id=receipt.user_id)).balance == Decimal('19.999982')


async def test_drain_rejects_admission_before_receipt_or_provider_and_keeps_reads(sdk_api,monkeypatch,tmp_path):
    from openai import APIStatusError
    from services.deployment import require_accepting
    marker=tmp_path/'draining'
    monkeypatch.setattr(settings,'DEPLOYMENT_DRAIN_FILE',str(marker))
    sdk,state,models=sdk_api
    # An accepted video remains readable, even with all new generation gated.
    video=await sdk.videos.create(model=f'nv-{models[2].id}',prompt='synthetic',seconds='4',size='1280x720')
    marker.touch()
    receipts=await PlatformCallReceipt.all().count()
    upstream=len(state.seen)
    for kind in ('text','image','video'):
        with pytest.raises(APIStatusError) as error:
            if kind=='text':await sdk.chat.completions.create(model='official-chat',messages=[{'role':'user','content':'test'}])
            elif kind=='image':await sdk.images.generate(model='official-image',prompt='test')
            else:await sdk.videos.create(model=f'nv-{models[2].id}',prompt='test',seconds='4',size='1280x720')
        assert error.value.status_code==503
        assert error.value.response.headers['retry-after']=='30'
    from services.platform.native import submit
    with pytest.raises(HTTPException) as error:
        await submit(AuthContext(user=await User.get(username='sdk-client')),'volcengine_ark',
                     {'model':f'nv-{models[2].id}','content':[]},key='native-during-drain')
    assert error.value.status_code==503
    assert len(state.seen)==upstream
    assert await PlatformCallReceipt.all().count()==receipts
    assert (await sdk.videos.retrieve(video.id)).status=='completed'
    marker.unlink()
    require_accepting()


async def test_drain_is_rechecked_after_admission_database_wait(monkeypatch,tmp_path):
    from services.platform import calls
    marker=tmp_path/'draining'
    monkeypatch.setattr(settings,'DEPLOYMENT_DRAIN_FILE',str(marker))
    user=await User.create(username='race')
    config=await AiModelConfig.create(name='race',model='race',task_type=7,is_active=True,
        base_url='https://synthetic.invalid',api_key='synthetic',
        pricing={'type':'text','input_price_per_1m':1,'output_price_per_1m':2})
    async def solvent(_):marker.touch()
    monkeypatch.setattr(calls,'ensure_solvent',solvent)
    with pytest.raises(HTTPException) as error:await admit(AuthContext(user=user),f'nv-{config.id}',{},'race')
    assert error.value.status_code==503
    assert await PlatformCallReceipt.all().count()==0


async def test_shutdown_does_not_extend_original_deadline():
    stream,provider,client,receipt=await make_stream(delay=10,lifetime=0.05)
    reader=asyncio.create_task(consume(stream))
    await asyncio.wait_for(chat.stop_streams(),timeout=1)
    content=await reader
    assert b'[DONE]' not in content and b'"error"' in content
    assert (await PlatformCallReceipt.get(id=receipt.id)).state=='review'
    assert not await ModelUsageRecord.all().exists()
    assert provider.reads==1
    client.close.assert_awaited_once()


async def test_disconnected_consumer_does_not_cancel_provider_settlement():
    stream,provider,client,receipt=await make_stream(delay=0.05,lifetime=2)
    # Equivalent to the response's ASGI finally block on a disconnected browser.
    stream.detach()
    await chat.stop_streams()
    assert (await PlatformCallReceipt.get(id=receipt.id)).state=='completed'
    assert await BalanceTransaction.filter(type='consume').count()==1
    assert provider.reads==1
    client.close.assert_awaited_once()


async def test_expired_stream_with_blocked_output_cannot_hang_shutdown(monkeypatch):
    monkeypatch.setattr(chat,'STREAM_FINALIZE_SECONDS',0.05)
    stream,_,client,receipt=await make_stream(delay=10,lifetime=0.02)
    for _ in range(32):stream.queue.put_nowait(b'blocked')
    await asyncio.wait_for(chat.stop_streams(),timeout=1)
    assert not chat._streams
    assert (await PlatformCallReceipt.get(id=receipt.id)).state=='review'
    client.close.assert_awaited_once()


async def test_readiness_reports_503_but_liveness_stays_available(monkeypatch,tmp_path):
    from main import app
    marker=tmp_path/'draining'
    monkeypatch.setattr(settings,'DEPLOYMENT_DRAIN_FILE',str(marker))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        assert (await client.get('/api/health/ready')).status_code==200
        marker.touch()
        response=await client.get('/api/health/ready')
        assert response.status_code==503 and response.json()['status']=='draining'
        assert (await client.get('/health')).status_code==200
        marker.unlink()
        assert (await client.get('/api/health/ready')).status_code==200


def test_operator_drain_marker_survives_restart_and_refuses_unknown_files(tmp_path):
    root=Path(__file__).resolve().parents[1]
    marker=tmp_path/'draining'
    env={**os.environ,'DEPLOYMENT_DRAIN_FILE':str(marker)}
    def run(action):
        return subprocess.run([sys.executable,str(root/'scripts/drain.py'),action],env=env,
                              cwd=root,capture_output=True,text=True)
    assert run('begin').returncode==0
    assert 'draining:' in run('status').stdout
    assert run('begin').returncode==0
    assert run('end').returncode==0 and not marker.exists()
    marker.write_text('not-owned-by-deployment')
    assert run('begin').returncode!=0 and run('end').returncode!=0
    assert marker.read_text()=='not-owned-by-deployment'


async def test_real_sigterm_preserves_http_stream_and_does_not_resubmit(tmp_path):
    root=Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    db=tmp_path/'signal.db';release=tmp_path/'release';submissions=tmp_path/'submissions'
    marker=tmp_path/'draining'
    env={**os.environ,'PYTHONPATH':str(root),'DATABASE_URL':f'sqlite://{db}',
         'DEPLOYMENT_DRAIN_FILE':str(marker),'DRAIN_TEST_RELEASE':str(release),
         'DRAIN_TEST_SUBMISSIONS':str(submissions)}
    with (tmp_path/'server.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','graceful_server:app',
            '--app-dir',str(root/'test/fixtures'),'--host','127.0.0.1','--port',str(port),
            '--timeout-graceful-shutdown','2'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',timeout=5,trust_env=False) as client:
                for _ in range(100):
                    assert process.poll() is None,(tmp_path/'server.log').read_text()
                    try:
                        if (await client.get('/health')).status_code==200:break
                    except httpx.ConnectError:pass
                    await asyncio.sleep(0.05)
                else:pytest.fail('Synthetic server did not become ready')
                async with client.stream('POST','/generate') as response:
                    assert response.status_code==200
                    chunks=response.aiter_bytes()
                    first=await anext(chunks)
                    assert b'first' in first
                    marker.touch()
                    rejected=await client.post('/generate')
                    assert rejected.status_code==503 and rejected.headers['retry-after']=='30'
                    process.send_signal(signal.SIGTERM)
                    await asyncio.sleep(0.2)
                    assert process.poll() is None
                    release.touch()
                    content=first+b''.join([part async for part in chunks])
                    assert b'"content":"last"' in content and b'"finish_reason":"stop"' in content
                    assert content.endswith(b'data: [DONE]\n\n')
            # Uvicorn re-raises the captured TERM after graceful cleanup on newer versions.
            assert await asyncio.to_thread(process.wait,timeout=8) in (0,-signal.SIGTERM)
            assert 'Application shutdown complete' in (tmp_path/'server.log').read_text()
            assert submissions.read_text().splitlines()==['submitted']
            with sqlite3.connect(f'file:{db}?mode=ro',uri=True) as connection:
                assert connection.execute('select count(*) from model_usage_records').fetchone()[0]==1
                assert connection.execute("select count(*) from account_balance_transactions where type='consume'").fetchone()[0]==1
                assert connection.execute('select state from account_call_receipts').fetchone()[0]=='completed'
        finally:
            if process.poll() is None:
                process.kill();await asyncio.to_thread(process.wait,timeout=5)
