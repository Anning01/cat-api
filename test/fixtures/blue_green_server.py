"""Real application with a local synthetic provider; never used for deployment."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
from main import app
from services import deployment
from services.platform import chat

deployment.release_commit=lambda:os.environ['BLUE_GREEN_TEST_SHA']


class Bytes(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"id":"synthetic","choices":[{"delta":{"content":"first"}}]}\n\n'
        if os.environ['BLUE_GREEN_TEST_SLOT']=='old':
            while not Path(os.environ['BLUE_GREEN_TEST_RELEASE']).exists():
                await asyncio.sleep(0.01)
        yield b'data: {"id":"synthetic","choices":[{"delta":{"content":"last"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
        yield b'data: [DONE]\n\n'


class Provider:
    def __init__(self):
        self.chat=SimpleNamespace(completions=SimpleNamespace(with_raw_response=self))
    async def create(self,**kwargs):
        with Path(os.environ['BLUE_GREEN_TEST_SUBMISSIONS']).open('a') as f:
            f.write(os.environ['BLUE_GREEN_TEST_SLOT']+'\n')
        return SimpleNamespace(http_response=httpx.Response(200,stream=Bytes()))
    async def close(self):pass


chat.provider_client=lambda _:Provider()
