"""Klient til cvr.dev og lokal cache af rå API-svar.

API-nøglen læses fra miljøvariablen CVR_DEV_API_KEY og sendes kun i
Authorization-headeren. Den logges, gemmes og vises aldrig.
"""

from __future__ import annotations

import http.client
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://api.cvr.dev/api/"
MILJOE_NOEGLE = "CVR_DEV_API_KEY"


@dataclass(frozen=True)
class HttpSvar:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str], float], HttpSvar]


class ApiFejl(Exception):
    """Fejl ved opslag af ét CVR-nummer."""


class IkkeFundet(ApiFejl):
    """cvr.dev kender ikke CVR-nummeret."""


class FatalApiFejl(ApiFejl):
    """Fejl der gælder alle opslag (fx ugyldig nøgle eller ingen credits)."""


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpSvar:
    """Standard-transport. Respekterer HTTPS_PROXY og SSL_CERT_FILE."""
    anmodning = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(anmodning, timeout=timeout) as svar:
            return HttpSvar(svar.status, dict(svar.headers.items()), svar.read())
    except urllib.error.HTTPError as fejl:
        return HttpSvar(fejl.code, dict(fejl.headers.items()), fejl.read())


class CvrDevKlient:
    def __init__(
        self,
        api_noegle: str | None,
        *,
        transport: Transport = urllib_transport,
        timeout: float = 30.0,
        max_forsoeg: int = 5,
        sov: Callable[[float], None] = time.sleep,
        base_url: str = BASE_URL,
    ) -> None:
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if api_noegle:
            self._headers["Authorization"] = api_noegle
        self._transport = transport
        self._timeout = timeout
        self._max_forsoeg = max(1, max_forsoeg)
        self._sov = sov
        self._base_url = base_url
        self.antal_kald = 0

    def __repr__(self) -> str:  # Sikrer at nøglen aldrig havner i logs via repr.
        return f"CvrDevKlient(base_url={self._base_url!r})"

    def test_noegle(self) -> None:
        """Gratis kontrol af nøglen: GET /api/test/apikey."""
        self._get("test/apikey")

    def hent_virksomhed(self, cvr_nummer: str) -> Any:
        """Hent rå virksomhedsdata. Returnerer det parsede JSON-svar (en liste)."""
        query = urllib.parse.urlencode({"cvr_nummer": cvr_nummer})
        body = self._get(f"cvr/virksomhed?{query}")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as fejl:
            raise ApiFejl("Ugyldigt response-format: svaret er ikke gyldig JSON") from fejl

    def _get(self, sti: str) -> bytes:
        url = self._base_url + sti
        sidste_fejl = ""
        for forsoeg in range(1, self._max_forsoeg + 1):
            ventetid: float | None = None
            try:
                self.antal_kald += 1
                svar = self._transport(url, self._headers, self._timeout)
            except (OSError, http.client.HTTPException) as fejl:
                sidste_fejl = f"netværksfejl ({type(fejl).__name__})"
            else:
                if svar.status == 200:
                    return svar.body
                if svar.status == 404:
                    raise IkkeFundet("Ikke fundet i CVR (HTTP 404)")
                if svar.status == 401:
                    raise FatalApiFejl("Ugyldig eller manglende API-nøgle (HTTP 401)")
                if svar.status == 402:
                    raise FatalApiFejl("Ikke nok credits hos cvr.dev (HTTP 402)")
                if svar.status == 403:
                    raise FatalApiFejl("Adgang nægtet (HTTP 403)")
                if svar.status != 429 and svar.status < 500:
                    raise ApiFejl(f"API-fejl (HTTP {svar.status})")
                sidste_fejl = f"HTTP {svar.status}"
                ventetid = _retry_after(svar.headers)
            if forsoeg < self._max_forsoeg:
                self._sov(ventetid if ventetid is not None else min(60.0, 2.0 * 2 ** (forsoeg - 1)))
        raise ApiFejl(f"{sidste_fejl} efter {self._max_forsoeg} forsøg")


def _retry_after(headers: Mapping[str, str]) -> float | None:
    for navn, vaerdi in headers.items():
        if navn.lower() == "retry-after":
            try:
                return min(120.0, max(0.0, float(vaerdi)))
            except ValueError:
                return None
    return None


def api_noegle_fra_miljoe() -> str | None:
    noegle = os.environ.get(MILJOE_NOEGLE, "").strip()
    return noegle or None


@dataclass(frozen=True)
class CacheIndgang:
    http_status: int
    data: Any
    hentet: datetime


class RaaCache:
    """Gemmer rå API-svar som JSON-filer: <mappe>/<cvr>.json."""

    def __init__(self, mappe: Path) -> None:
        self.mappe = mappe

    def _sti(self, cvr_nummer: str) -> Path:
        return self.mappe / f"{cvr_nummer}.json"

    def hent(self, cvr_nummer: str, max_alder: timedelta | None, nu: datetime) -> CacheIndgang | None:
        """Returnér cachet svar, hvis det findes og ikke er for gammelt."""
        sti = self._sti(cvr_nummer)
        try:
            indhold = json.loads(sti.read_text(encoding="utf-8"))
            hentet = datetime.fromisoformat(indhold["hentet"])
            indgang = CacheIndgang(int(indhold["http_status"]), indhold["data"], hentet)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            return None  # Ødelagt cachefil behandles som manglende.
        if max_alder is not None and nu - indgang.hentet > max_alder:
            return None
        return indgang

    def gem(self, cvr_nummer: str, http_status: int, data: Any, nu: datetime) -> None:
        self.mappe.mkdir(parents=True, exist_ok=True)
        indhold = {
            "cvr_nummer": cvr_nummer,
            "hentet": nu.isoformat(),
            "http_status": http_status,
            "data": data,
        }
        fd, midlertidig = tempfile.mkstemp(dir=self.mappe, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fil:
                json.dump(indhold, fil, ensure_ascii=False)
            os.replace(midlertidig, self._sti(cvr_nummer))
        except BaseException:
            Path(midlertidig).unlink(missing_ok=True)
            raise


def nu_utc() -> datetime:
    return datetime.now(timezone.utc)
