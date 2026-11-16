"""Synthetic provider used only by the local SIGTERM integration test."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
import httpx
from tortoise import Tortoise

from auth.deps import AuthContext
from auth.models import User, UserWallet
from models.config import AiModelConfig
from schemas.platform_chat import ChatRequest
from services.platform import chat


class ProviderBytes(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"id":"local-signal-test","choices":[{"delta":{"content":"first"}}]}\n\n'
        while not Path(os.environ['DRAIN_TEST_RELEASE']).exists():
            await asyncio.sleep(0.01)
        yield b'data: {"id":"local-signal-test","choices":[{"delta":{"content":"last"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
        yield b'data: [DONE]\n\n'


class Provider:
    def __init__(self):
        self.chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=self))

    async def create(self, **kwargs):
        with Path(os.environ['DRAIN_TEST_SUBMISSIONS']).open('a') as f:
            f.write('submitted\n')
        return SimpleNamespace(http_response=httpx.Response(200,stream=ProviderBytes()))

    async def close(self):
        pass


@asynccontextmanager
async def lifespan(app):
    await Tortoise.init(db_url=os.environ['DATABASE_URL'],modules={'models':['auth.models','models.config','models.usage_record']})
    await Tortoise.generate_schemas()
    user=await User.create(username='signal-test')
    await UserWallet.create(user=user,balance=20)
    app.state.ctx=AuthContext(user=user)
    app.state.config=await AiModelConfig.create(name='signal-test',model='signal-test',task_type=7,
        base_url='https://synthetic.invalid',api_key='synthetic',
        is_active=True,pricing={'type':'text','input_price_per_1m':1,'output_price_per_1m':2})
    chat.provider_client=lambda _:Provider()
    try:
        yield
    finally:
        await chat.stop_streams()
        await Tortoise.close_connections()


app=FastAPI(lifespan=lifespan)


@app.get('/health')
async def health():
    return {'status':'ok'}


@app.post('/generate')
async def generate():
    return await chat.complete(app.state.ctx,ChatRequest(model=f'nv-{app.state.config.id}',
        messages=[{'role':'user','content':'synthetic test'}],stream=True),'same-request')
