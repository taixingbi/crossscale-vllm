"""Real vLLM streaming runner and single-process experimental gateway."""
import asyncio
from collections import deque
import json
import os
from pathlib import Path
import time

from .core import quantile, workload, write_run
from .policy import decision


def aio():
    try:
        import aiohttp
        return aiohttp
    except ImportError as exc:
        raise SystemExit("Install live dependencies: python3 -m pip install -e '.[live]'") from exc


async def events(response):
    # aiohttp line iteration buffers arbitrary TCP splits. vLLM emits one data
    # JSON per SSE event; blank lines and comments carry no generation content.
    async for line in response.content:
        line = line.decode().strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                yield {"done": True}
            elif payload:
                yield json.loads(payload)


async def run(c, baseline, out, url, model, tokens_path):
    http = aio()
    rows = workload(c)
    token_ids = json.loads(Path(tokens_path).read_text())
    if not token_ids or any(type(x) is not int or x < 0 for x in token_ids):
        raise ValueError("tokens file must be a nonempty JSON array from the serving model tokenizer")
    if len(token_ids) < max((r["input_tokens"] for r in rows), default=0):
        raise ValueError("token corpus too short for sampled inputs; supply a larger tokenized corpus")
    begin = time.monotonic()
    wall = time.time()
    headers = {"Authorization": "Bearer " + os.environ["VLLM_API_KEY"]} if os.environ.get("VLLM_API_KEY") else {}
    async with http.ClientSession(timeout=http.ClientTimeout(total=c["request_timeout_s"]), connector=http.TCPConnector(limit=0), headers=headers) as session:
        async def send(r):
            scheduled = begin + r["offered_s"]
            await asyncio.sleep(max(0, scheduled-time.monotonic()))
            r["dispatch_lag_s"] = max(0, time.monotonic()-scheduled)
            first, last, count, done = None, None, None, False
            offset = r["id"] % (len(token_ids)-r["input_tokens"]+1)
            body = dict(model=model, prompt=token_ids[offset:offset+r["input_tokens"]], max_tokens=r["output_tokens"], stream=True, stream_options={"include_usage": True}, temperature=0, ignore_eos=True)
            try:
                async with session.post(url.rstrip("/")+"/v1/completions", json=body, headers={"X-Tenant": r["tenant"]}) as response:
                    r["http_status"] = response.status
                    r["admission_delay_s"] = float(response.headers.get("X-Admission-Delay", 0))
                    if response.status != 200:
                        r["status"] = "rejected" if response.status == 429 else "error"
                        return
                    async for event in events(response):
                        now = time.monotonic()
                        if event.get("done"):
                            done = True
                        if event.get("usage"):
                            count = event["usage"].get("completion_tokens")
                            r["actual_input_tokens"] = event["usage"].get("prompt_tokens")
                        if any(choice.get("text") for choice in event.get("choices", [])):
                            first = now if first is None else first
                            last = now
                    if not done or first is None or not count or count < 2:
                        r.update(status="error", error="missing terminal SSE, text, or usage >=2 tokens")
                    else:
                        r.update(status="completed", ttft_s=first-scheduled, tpot_s=(last-first)/(count-1), actual_output_tokens=count)
            except (asyncio.TimeoutError, http.ClientError, ValueError) as exc:
                r.update(status="timeout" if isinstance(exc, asyncio.TimeoutError) else "error", error=type(exc).__name__)
        tasks = [asyncio.create_task(send(r)) for r in rows]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=c["duration_s"]+c["drain_s"])
            for task in pending:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r, result in zip(rows, results):
                if isinstance(result, asyncio.CancelledError):
                    r["status"] = "timeout"
                elif isinstance(result, BaseException):
                    r.update(status="error", error=type(result).__name__)
    for r in rows:
        r.setdefault("status", "timeout")
    return write_run(out, c, rows, [], "live", baseline, {"start_unix_s": wall, "elapsed_s": time.monotonic()-begin, "model": model, "tpot_definition": "(last nonempty text arrival - first)/(usage completion_tokens - 1); SSE chunks may coalesce tokens"})


async def gateway(c, baseline, state_path, upstream, host, port):
    http = aio()
    from aiohttp import web
    active = {t: 0 for t in c["tenants"]}
    samples = {t: deque(maxlen=10000) for t in c["tenants"]}
    session = http.ClientSession(timeout=http.ClientTimeout(total=c["request_timeout_s"]), connector=http.TCPConnector(limit=0))

    def state():
        s = json.loads(Path(state_path).read_text())
        if time.time()-s["observed_unix_s"] > 10:
            raise ValueError("capacity state older than 10s")
        return s

    async def metrics(_):
        now = time.monotonic()
        values = []
        for t, q in samples.items():
            recent = [r for r in q if now-r[0] <= 30]
            if recent:
                spec = c["tenants"][t]
                values.append(max(quantile([r[1] for r in recent], .9)/spec["ttft_s"], quantile([r[2] for r in recent], .9)/spec["tpot_s"]))
        lines = [f'crossscale_active{{tenant="{t}"}} {v}' for t, v in active.items()]
        # No samples => absent metric. KEDA must not treat missing as zero.
        if values:
            lines.append(f"crossscale_slo_saturation {max(values)}")
        return web.Response(text="\n".join(lines)+"\n", content_type="text/plain")

    async def proxy(request):
        tenant = request.headers.get("X-Tenant", "")
        if tenant not in c["tenants"]:
            raise web.HTTPBadRequest(text="valid X-Tenant required")
        body = await request.json()
        if not body.get("stream") or not isinstance(body.get("prompt"), list):
            raise web.HTTPBadRequest(text="experimental gateway requires stream=true and token-ID prompt")
        body["stream_options"] = {"include_usage": True}
        begin = time.monotonic()
        r = dict(tenant=tenant, offered_s=begin, input_tokens=len(body["prompt"]))
        while True:
            now = time.monotonic()
            try:
                s = state()
            except (OSError, ValueError, KeyError):
                raise web.HTTPServiceUnavailable(text="capacity observation unavailable or stale")
            etas = [now+max(0, x-time.time()) for x in s.get("pending_eta_unix_s", [])]
            action = decision(c, baseline, r, now, s["ready"], s["desired"], active, etas)
            if action == "reject":
                raise web.HTTPTooManyRequests(headers={"X-Admission-Delay": str(now-begin)})
            if action == "admit":
                active[tenant] += 1  # no await between decision and reservation
                break
            await asyncio.sleep(c["fast_interval_s"])
        delay = time.monotonic()-begin
        headers = {}
        if os.environ.get("VLLM_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["VLLM_API_KEY"]
        try:
            async with session.post(upstream.rstrip("/")+"/v1/completions", json=body, headers=headers) as response:
                out = web.StreamResponse(status=response.status, headers={"Content-Type": response.headers.get("Content-Type", "text/event-stream"), "X-Admission-Delay": str(delay)})
                await out.prepare(request)
                first, last, count = None, None, None
                async for line in response.content:
                    now = time.monotonic()
                    if line.startswith(b"data:") and line[5:].strip() != b"[DONE]":
                        event = json.loads(line[5:])
                        if event.get("usage"):
                            count = event["usage"].get("completion_tokens")
                        if any(ch.get("text") for ch in event.get("choices", [])):
                            first = now if first is None else first
                            last = now
                    await out.write(line)
                await out.write_eof()
                if response.status == 200 and first is not None and count and count > 1:
                    samples[tenant].append((time.monotonic(), first-begin, (last-first)/(count-1)))
                return out
        finally:
            active[tenant] -= 1

    app = web.Application(client_max_size=4*1024**2)
    app.router.add_post("/v1/completions", proxy)
    app.router.add_get("/metrics", metrics)
    async def close(_):
        await session.close()
    app.on_cleanup.append(close)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
