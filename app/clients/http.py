import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_RETRY = retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
)


class HTTPClient:
    """Thin async wrapper around httpx with retries and a shared session."""

    def __init__(self, base_url: str = "", headers: dict[str, str] | None = None, timeout: float = 15.0):
        self._client = httpx.AsyncClient(base_url=base_url, headers=headers or {}, timeout=timeout)

    @_RETRY
    async def get(self, path: str, **kwargs) -> httpx.Response:
        r = await self._client.get(path, **kwargs)
        r.raise_for_status()
        return r

    @_RETRY
    async def post(self, path: str, **kwargs) -> httpx.Response:
        r = await self._client.post(path, **kwargs)
        r.raise_for_status()
        return r

    async def aclose(self) -> None:
        await self._client.aclose()
