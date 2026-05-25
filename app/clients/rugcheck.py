"""RugCheck safety scoring.

API: https://api.rugcheck.xyz/swagger/index.html

We pull /tokens/{mint}/report/summary which returns a numeric score plus
boolean flags (mint authority present, freeze authority present, top-holder
concentration, LP burned, etc).
"""

from typing import Any

from app.clients.http import HTTPClient
from app.config import get_settings


class RugCheckClient:
    def __init__(self) -> None:
        s = get_settings()
        self._http = HTTPClient(base_url=s.rugcheck_base_url)

    async def summary(self, mint: str) -> dict[str, Any] | None:
        try:
            r = await self._http.get(f"/tokens/{mint}/report/summary")
            return r.json()
        except Exception:
            return None

    async def aclose(self) -> None:
        await self._http.aclose()
