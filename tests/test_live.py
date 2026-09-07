import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    import aiohttp
    from aiohttp import web
except ImportError:
    aiohttp = None

from crossscale.core import config
from crossscale.live import run, gateway


@unittest.skipIf(aiohttp is None, 'install .[live] for HTTP integration tests')
class Streaming(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = config('configs/default.json')
        self.c.update(duration_s=.2, drain_s=.5, request_timeout_s=.2)
        self.c['phases'] = [self.c['phases'][0]]
        (self.root/'tokens.json').write_text(json.dumps([100]*100))
        self.runners = []

    async def asyncTearDown(self):
        for runner in self.runners:
            await runner.cleanup()
        self.tmp.cleanup()

    async def serve(self, handler):
        app = web.Application()
        app.router.add_post('/v1/completions', handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        self.runners.append(runner)
        return 'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])

    def trace(self, n=1):
        return [dict(id=i, tenant='A', offered_s=i*.01, input_tokens=10, output_tokens=4) for i in range(n)]

    async def test_split_sse_uses_usage_not_chunk_count(self):
        async def handler(request):
            body = await request.json()
            self.assertEqual(len(body['prompt']), 10)
            response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
            await response.prepare(request)
            await response.write(b'data: {"choices": [{"te')
            await response.write(b'xt":"ab"}]}\n\n')
            await asyncio.sleep(.03)
            await response.write(b'data: {"choices": [{"text":"cd"}]}\n\n')
            await response.write(b'data: {"usage":{"completion_tokens":4,"prompt_tokens":10}}\n\ndata: [DONE]\n\n')
            return response
        url = await self.serve(handler)
        with patch('crossscale.live.workload', return_value=self.trace()):
            await run(self.c, 'B0', self.root/'run', url, 'fake', self.root/'tokens.json')
        row = json.loads((self.root/'run/requests.jsonl').read_text())
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['actual_output_tokens'], 4)
        self.assertLess(row['tpot_s'], .03)
        self.assertGreater(row['tpot_s'], .007)

    async def test_rejection_and_drain_cancellation_are_counted(self):
        async def handler(_):
            return web.Response(status=429)
        url = await self.serve(handler)
        with patch('crossscale.live.workload', return_value=self.trace(2)):
            result = await run(self.c, 'B4', self.root/'reject', url, 'fake', self.root/'tokens.json')
        self.assertEqual(result['tenants']['A']['offered'], 2)
        self.assertEqual(result['tenants']['A']['rejected'], 2)
        self.assertEqual(result['tenants']['A']['goodput'], 0)

    async def test_gateway_does_not_forward_pending_capacity(self):
        calls = []
        async def handler(_):
            calls.append(1)
            return web.Response(text='data: [DONE]\n\n')
        upstream = await self.serve(handler)
        state = self.root/'state.json'
        state.write_text(json.dumps(dict(observed_unix_s=time.time(), ready=0, desired=4, pending_eta_unix_s=[time.time()+60])))
        # Capture the actual ephemeral listening port without reserving a socket.
        original = web.TCPSite.start
        sites = []
        async def start(site):
            await original(site)
            sites.append(site)
        with patch.object(web.TCPSite, 'start', start):
            task = asyncio.create_task(gateway(self.c, 'B6', state, upstream, '127.0.0.1', 0))
            try:
                for _ in range(100):
                    if sites:
                        break
                    await asyncio.sleep(.01)
                port = sites[0]._server.sockets[0].getsockname()[1]
                async with aiohttp.ClientSession() as session:
                    async with session.post(f'http://127.0.0.1:{port}/v1/completions', json={'prompt':[100]*10,'stream':True}, headers={'X-Tenant':'A'}) as response:
                        self.assertEqual(response.status, 429)
                self.assertEqual(calls, [])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


if __name__ == '__main__':
    unittest.main()
