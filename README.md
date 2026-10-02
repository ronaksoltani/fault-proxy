# Mock Fault-Tolerant Proxy

A local HTTP reverse proxy that forwards requests to one configured upstream while injecting controlled delay or server errors. Use it to observe how a development client handles slow and unreliable upstream responses.

## Quick start

```bash
python -m venv .venv
python -m pip install -e .
copy .env.example .env  # Windows PowerShell: Copy-Item .env.example .env
uvicorn fault_proxy.app:app --reload --port 8080
```

Set `UPSTREAM_BASE_URL` to a test service you control, then point the client under test at `http://127.0.0.1:8080`. Defaults inject a 10% HTTP 500 rate and a 20% chance of up to 200 ms delay. `/__health` reports whether the local proxy process is responding.

## Safety and limits

The proxy accepts only a fixed upstream from environment configuration, which avoids turning it into an open proxy. Keep it bound to localhost, never place production credentials in test requests, and use only a service you are authorized to test. Bodies are capped at 10 MiB; hop-by-hop headers are removed.

## Learning notes

The app combines an async FastAPI route, a reusable `httpx.AsyncClient`, environment-backed settings, and injectable fault selection. This makes the failure behavior small enough to understand and deterministic enough to test.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

## License

MIT. See [LICENSE](LICENSE).
