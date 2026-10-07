"""Ende-til-ende: input → (falsk) API → analyse → CSV-filer."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cvr_adresse_checker import cli
from cvr_adresse_checker.analyse import Status
from cvr_adresse_checker.api import CvrDevKlient, HttpSvar, RaaCache
from cvr_adresse_checker.filer import laes_input, normaliser_cvr, skriv_csv
from cvr_adresse_checker.koersel import Indstillinger, analyser_alle
from tests.hjaelpere import adresse, virksomhed
from tests.test_api import FalskTransport, ok

IDAG = date(2026, 10, 7)
NU = datetime(2026, 10, 7, 10, tzinfo=timezone.utc)
AKTIV_FLYTTET = "11111111"
OPHOERT_FLYTTET = "22222222"
UFLYTTET = "33333333"
API_FEJL = "44444444"


def flytning(cvr: str, **kw: Any) -> list[dict[str, Any]]:
    return [
        virksomhed(
            [adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", vejnavn="Parkvej", vejkode=9)],
            cvr=cvr,
            **kw,
        )
    ]


def laes_csv(sti: Path) -> list[dict[str, str]]:
    with sti.open(encoding="utf-8-sig", newline="") as fil:
        return list(csv.DictReader(fil, delimiter=";"))


class TestInput(unittest.TestCase):
    def test_normaliser_cvr(self) -> None:
        self.assertEqual(normaliser_cvr(" DK 1234 5674 "), "12345674")
        self.assertEqual(normaliser_cvr('"12345674"'), "12345674")
        self.assertIsNone(normaliser_cvr("1234567"))
        self.assertIsNone(normaliser_cvr("01234567"))
        self.assertIsNone(normaliser_cvr("12345abc"))

    def test_txt_med_dubletter_og_kommentarer(self) -> None:
        with tempfile.TemporaryDirectory() as mappe:
            sti = Path(mappe) / "in.txt"
            sti.write_text("# liste\n12345674\n\nDK12345674\nabc\n87654321\n", encoding="utf-8")
            indhold = laes_input(sti)
        self.assertEqual([p.cvr_nummer for p in indhold.poster], ["12345674", None, "87654321"])
        self.assertEqual(indhold.dubletter, 1)

    def test_csv_med_overskrift(self) -> None:
        with tempfile.TemporaryDirectory() as mappe:
            sti = Path(mappe) / "in.csv"
            sti.write_bytes("Navn;CVR-nr\nFirma Æ;12345674\nFirma B;87654321\n".encode("cp1252"))
            indhold = laes_input(sti)
        self.assertEqual([p.cvr_nummer for p in indhold.poster], ["12345674", "87654321"])


class TestKoersel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.mappe = Path(self._tmp.name)
        self.cache = RaaCache(self.mappe / "cache")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def koer(self, cvr_liste: list[str], transport: FalskTransport) -> list[Any]:
        sti = self.mappe / "in.txt"
        sti.write_text("\n".join(cvr_liste), encoding="utf-8")
        klient = CvrDevKlient("k", transport=transport, sov=lambda _s: None, max_forsoeg=2)
        ind = Indstillinger(idag=IDAG, nu=NU, max_cache_alder=timedelta(hours=24))
        resultater, _ = analyser_alle(laes_input(sti).poster, klient, self.cache, ind)
        return resultater

    def test_samlet_kørsel_og_output(self) -> None:
        transport = FalskTransport(
            [
                ok(flytning(AKTIV_FLYTTET)),
                ok(flytning(OPHOERT_FLYTTET, status="Ophørt", ophoert="2026-09-30")),
                ok([virksomhed([adresse("2015-01-01")], cvr=UFLYTTET)]),
                HttpSvar(500, {}, b""),
                HttpSvar(500, {}, b""),
            ]
        )
        resultater = self.koer([AKTIV_FLYTTET, OPHOERT_FLYTTET, UFLYTTET, API_FEJL, "1234"], transport)
        status = {r.cvr_nummer: r.status for r in resultater}
        self.assertEqual(status[AKTIV_FLYTTET], Status.MATCH)
        self.assertEqual(status[OPHOERT_FLYTTET], Status.MATCH)
        self.assertEqual(status[UFLYTTET], Status.IKKE_MATCH)
        self.assertEqual(status[API_FEJL], Status.FEJL, "API-fejl skal give FEJL")
        self.assertEqual(status["1234"], Status.FEJL, "ugyldigt CVR skal give FEJL")
        self.assertEqual(len(transport.kald), 5, "ugyldigt CVR må ikke give API-kald")

        skriv_csv(self.mappe / "alle.csv", resultater)
        skriv_csv(self.mappe / "matches.csv", [r for r in resultater if r.er_aktivt_match])
        matches = laes_csv(self.mappe / "matches.csv")
        self.assertEqual([m["cvr_nummer"] for m in matches], [AKTIV_FLYTTET])
        alle = {r["cvr_nummer"]: r for r in laes_csv(self.mappe / "alle.csv")}
        self.assertEqual(len(alle), 5)
        self.assertEqual(alle[OPHOERT_FLYTTET]["aktiv"], "NEJ")
        self.assertIn("udelukket fra matches.csv", alle[OPHOERT_FLYTTET]["note"])
        self.assertEqual(alle[AKTIV_FLYTTET]["adresseskift_dato"], "2026-09-12")
        self.assertEqual(alle[AKTIV_FLYTTET]["dage_siden_adresseskift"], "25")

    def test_cache_genbruges_uden_nyt_api_kald(self) -> None:
        self.koer([AKTIV_FLYTTET], FalskTransport([ok(flytning(AKTIV_FLYTTET))]))
        anden = FalskTransport([])
        resultater = self.koer([AKTIV_FLYTTET], anden)
        self.assertEqual(anden.kald, [])
        self.assertEqual(resultater[0].status, Status.MATCH)
        self.assertEqual(resultater[0].kilde, "cache")

    def test_ikke_fundet_er_fejl_og_caches(self) -> None:
        r = self.koer([AKTIV_FLYTTET], FalskTransport([HttpSvar(404, {}, b"")]))
        self.assertEqual(r[0].status, Status.FEJL)
        r = self.koer([AKTIV_FLYTTET], FalskTransport([]))
        self.assertEqual(r[0].status, Status.FEJL)

    def test_fatal_fejl_stopper_videre_api_kald(self) -> None:
        transport = FalskTransport([HttpSvar(402, {}, b"")])
        r = self.koer([AKTIV_FLYTTET, UFLYTTET], transport)
        self.assertEqual([x.status for x in r], [Status.FEJL, Status.FEJL])
        self.assertEqual(len(transport.kald), 1)
        self.assertIn("API-kald stoppet", r[1].note)

    def test_tomt_svar_er_fejl(self) -> None:
        r = self.koer([AKTIV_FLYTTET], FalskTransport([ok([])]))
        self.assertEqual(r[0].status, Status.FEJL)


class TestCli(unittest.TestCase):
    def test_kun_cache_kørsel_skriver_begge_filer(self) -> None:
        with tempfile.TemporaryDirectory() as mappe_navn:
            mappe = Path(mappe_navn)
            RaaCache(mappe / "cache").gem(AKTIV_FLYTTET, 200, flytning(AKTIV_FLYTTET), NU)
            (mappe / "in.txt").write_text(f"{AKTIV_FLYTTET}\n{UFLYTTET}\n", encoding="utf-8")
            ud, fejl = io.StringIO(), io.StringIO()
            with redirect_stdout(ud), redirect_stderr(fejl):
                kode = cli.main(
                    [
                        str(mappe / "in.txt"),
                        "--kun-cache",
                        "--cache-mappe",
                        str(mappe / "cache"),
                        "-o",
                        str(mappe / "ud"),
                        "--dato",
                        "2026-10-07",
                    ]
                )
            self.assertEqual(kode, 0)
            self.assertEqual(len(laes_csv(mappe / "ud" / "matches.csv")), 1)
            alle = laes_csv(mappe / "ud" / "alle_resultater.csv")
            self.assertEqual([r["status"] for r in alle], ["MATCH", "FEJL"])
            self.assertIn("[2/2]", fejl.getvalue())
            json.dumps(alle)  # rækkerne er rene strenge


if __name__ == "__main__":
    unittest.main()
