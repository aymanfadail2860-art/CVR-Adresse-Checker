from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cvr_adresse_checker.api import (
    ApiFejl,
    CvrDevKlient,
    FatalApiFejl,
    HttpSvar,
    IkkeFundet,
    RaaCache,
)

HEMMELIG = "hemmelig-test-noegle-123"


class FalskTransport:
    """Returnerer forudbestemte svar og husker kaldene."""

    def __init__(self, svar: list[HttpSvar | Exception]) -> None:
        self.svar = list(svar)
        self.kald: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str], timeout: float) -> HttpSvar:
        self.kald.append((url, dict(headers)))
        naeste = self.svar.pop(0)
        if isinstance(naeste, Exception):
            raise naeste
        return naeste


def ok(data: object) -> HttpSvar:
    return HttpSvar(200, {}, json.dumps(data).encode())


def klient(transport: FalskTransport, ventetider: list[float] | None = None) -> CvrDevKlient:
    sov = (ventetider.append) if ventetider is not None else (lambda _s: None)
    return CvrDevKlient(HEMMELIG, transport=transport, sov=sov, max_forsoeg=3)


class TestKlient(unittest.TestCase):
    def test_url_og_authorization_header(self) -> None:
        t = FalskTransport([ok([{"cvrNummer": 12345674}])])
        data = klient(t).hent_virksomhed("12345674")
        self.assertEqual(data, [{"cvrNummer": 12345674}])
        url, headers = t.kald[0]
        self.assertEqual(url, "https://api.cvr.dev/api/cvr/virksomhed?cvr_nummer=12345674")
        self.assertEqual(headers["Authorization"], HEMMELIG)

    def test_ingen_noegle_ingen_header(self) -> None:
        t = FalskTransport([ok([])])
        CvrDevKlient(None, transport=t).hent_virksomhed("12345674")
        self.assertNotIn("Authorization", t.kald[0][1])

    def test_noeglen_er_ikke_i_repr(self) -> None:
        self.assertNotIn(HEMMELIG, repr(klient(FalskTransport([]))))

    def test_retry_ved_429_med_retry_after(self) -> None:
        ventetider: list[float] = []
        t = FalskTransport([HttpSvar(429, {"Retry-After": "7"}, b""), ok([])])
        self.assertEqual(klient(t, ventetider).hent_virksomhed("12345674"), [])
        self.assertEqual(ventetider, [7.0])

    def test_retry_ved_5xx_og_netvaerksfejl_med_backoff(self) -> None:
        ventetider: list[float] = []
        t = FalskTransport([HttpSvar(503, {}, b""), TimeoutError(), ok([])])
        klient(t, ventetider).hent_virksomhed("12345674")
        self.assertEqual(ventetider, [2.0, 4.0])

    def test_429_efter_retries_giver_fejl(self) -> None:
        t = FalskTransport([HttpSvar(429, {}, b"")] * 3)
        with self.assertRaisesRegex(ApiFejl, "HTTP 429 efter 3 forsøg"):
            klient(t).hent_virksomhed("12345674")
        self.assertEqual(len(t.kald), 3)

    def test_5xx_efter_retries_giver_fejl(self) -> None:
        t = FalskTransport([HttpSvar(500, {}, b"")] * 3)
        with self.assertRaisesRegex(ApiFejl, "HTTP 500"):
            klient(t).hent_virksomhed("12345674")

    def test_404_giver_ikke_fundet_uden_retry(self) -> None:
        t = FalskTransport([HttpSvar(404, {}, b"")])
        with self.assertRaises(IkkeFundet):
            klient(t).hent_virksomhed("12345674")
        self.assertEqual(len(t.kald), 1)

    def test_401_og_402_er_fatale(self) -> None:
        for kode in (401, 402):
            with self.subTest(kode=kode), self.assertRaises(FatalApiFejl):
                klient(FalskTransport([HttpSvar(kode, {}, b"")])).hent_virksomhed("12345674")

    def test_ugyldig_json(self) -> None:
        t = FalskTransport([HttpSvar(200, {}, b"<html>")])
        with self.assertRaisesRegex(ApiFejl, "response-format"):
            klient(t).hent_virksomhed("12345674")

    def test_fejlbesked_indeholder_ikke_noeglen(self) -> None:
        t = FalskTransport([HttpSvar(401, {}, b"")])
        with self.assertRaises(FatalApiFejl) as ctx:
            klient(t).hent_virksomhed("12345674")
        self.assertNotIn(HEMMELIG, str(ctx.exception))


class TestCache(unittest.TestCase):
    def test_gem_og_hent(self) -> None:
        nu = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as mappe:
            cache = RaaCache(Path(mappe))
            cache.gem("12345674", 200, [{"a": 1}], nu)
            indgang = cache.hent("12345674", timedelta(hours=24), nu + timedelta(hours=1))
            self.assertIsNotNone(indgang)
            assert indgang is not None
            self.assertEqual(indgang.data, [{"a": 1}])
            self.assertIsNone(cache.hent("12345674", timedelta(hours=24), nu + timedelta(days=2)))
            self.assertIsNotNone(cache.hent("12345674", None, nu + timedelta(days=200)))

    def test_oedelagt_cachefil_ignoreres(self) -> None:
        with tempfile.TemporaryDirectory() as mappe:
            (Path(mappe) / "12345674.json").write_text("{ikke json", encoding="utf-8")
            nu = datetime.now(timezone.utc)
            self.assertIsNone(RaaCache(Path(mappe)).hent("12345674", None, nu))


if __name__ == "__main__":
    unittest.main()
