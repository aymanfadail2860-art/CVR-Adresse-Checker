"""Kommandolinje: python -m cvr_adresse_checker <inputfil> [valgmuligheder]."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from cvr_adresse_checker.analyse import Resultat
from cvr_adresse_checker.api import (
    MILJOE_NOEGLE,
    ApiFejl,
    CvrDevKlient,
    RaaCache,
    api_noegle_fra_miljoe,
    nu_utc,
)
from cvr_adresse_checker.filer import laes_input, skriv_csv
from cvr_adresse_checker.koersel import Indstillinger, analyser_alle, opsummer


def dagens_dato() -> date:
    """Dagens dato i dansk tid (falder tilbage til systemets lokale dato)."""
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:  # pragma: no cover
        return date.today()
    try:
        return nu_utc().astimezone(ZoneInfo("Europe/Copenhagen")).date()
    except ZoneInfoNotFoundError:
        return date.today()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cvr-adresse-checker",
        description=(
            "Finder virksomheder, der reelt har skiftet beliggenhedsadresse "
            "inden for de seneste 3 kalendermåneder (data fra cvr.dev)."
        ),
    )
    p.add_argument("input", nargs="?", type=Path, help="TXT/CSV-fil med CVR-numre")
    p.add_argument(
        "-o",
        "--output-mappe",
        type=Path,
        help="Mappe til matches.csv og alle_resultater.csv (standard: resultater/<dato>)",
    )
    p.add_argument("--cache-mappe", type=Path, default=Path("cache"), help="Standard: cache")
    p.add_argument(
        "--max-cache-alder-timer",
        type=float,
        default=24.0,
        help="Genbrug cachede råsvar, der er yngre end dette (standard: 24). 0 = hent altid nyt",
    )
    p.add_argument(
        "--kun-cache",
        action="store_true",
        help="Lav ingen API-kald; brug kun cachede råsvar (uanset alder)",
    )
    p.add_argument("--dato", type=date.fromisoformat, help="Analysedato YYYY-MM-DD (standard: i dag)")
    p.add_argument("--separator", default=";", help="CSV-separator i output (standard: ';')")
    p.add_argument("--timeout", type=float, default=30.0, help="HTTP-timeout i sekunder")
    p.add_argument(
        "--test-noegle",
        action="store_true",
        help="Test kun API-nøglen mod /api/test/apikey og stop",
    )
    return p


def _fremskridt(i: int, n: int, r: Resultat) -> None:
    kilde = f" ({r.kilde})" if r.kilde else ""
    print(f"[{i}/{n}] {r.cvr_nummer}: {r.status.value}{kilde}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    noegle = api_noegle_fra_miljoe()
    if noegle is None and not args.kun_cache:
        print(
            f"Bemærk: {MILJOE_NOEGLE} er ikke sat - sender uden Authorization-header "
            "(virker kun hvis en proxy tilføjer nøglen).",
            file=sys.stderr,
        )
    klient = None if args.kun_cache else CvrDevKlient(noegle, timeout=args.timeout)

    if args.test_noegle:
        if klient is None:
            print("--test-noegle kan ikke kombineres med --kun-cache", file=sys.stderr)
            return 2
        try:
            klient.test_noegle()
        except ApiFejl as fejl:
            print(f"Test af API-nøgle fejlede: {fejl}", file=sys.stderr)
            return 1
        print("API-nøglen virker (HTTP 200).")
        return 0

    if args.input is None:
        _parser().error("inputfil mangler")
    try:
        indhold = laes_input(args.input)
    except OSError as fejl:
        print(f"Kan ikke læse inputfil: {fejl}", file=sys.stderr)
        return 2

    idag = args.dato or dagens_dato()
    output_mappe = args.output_mappe or Path("resultater") / idag.isoformat()
    max_alder = None if args.kun_cache else timedelta(hours=max(0.0, args.max_cache_alder_timer))
    indstillinger = Indstillinger(idag=idag, nu=nu_utc(), max_cache_alder=max_alder, kun_cache=args.kun_cache)
    print(
        f"{len(indhold.poster)} unikke CVR-numre ({indhold.dubletter} dubletter fjernet). "
        f"Analysedato {idag}.",
        file=sys.stderr,
    )

    resultater, statistik = analyser_alle(
        indhold.poster, klient, RaaCache(args.cache_mappe), indstillinger, _fremskridt
    )

    skriv_csv(output_mappe / "alle_resultater.csv", resultater, args.separator)
    skriv_csv(output_mappe / "matches.csv", [r for r in resultater if r.er_aktivt_match], args.separator)

    print("\nResultat:")
    for navn, antal in opsummer(resultater).items():
        print(f"  {navn}: {antal}")
    print(f"  API-opslag: {statistik.api_opslag}, genbrugt fra cache: {statistik.cache_hits}")
    print(f"Filer skrevet til: {output_mappe}")
    if statistik.afbrudt_aarsag:
        print(f"ADVARSEL: API-kald blev stoppet: {statistik.afbrudt_aarsag}", file=sys.stderr)
        return 1
    return 0
