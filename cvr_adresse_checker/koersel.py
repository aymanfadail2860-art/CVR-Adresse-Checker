"""Kører analysen for en liste af CVR-numre: cache → API → matchlogik."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any

from cvr_adresse_checker.analyse import Resultat, Status, analyser_virksomhed, fejl
from cvr_adresse_checker.api import ApiFejl, CvrDevKlient, FatalApiFejl, IkkeFundet, RaaCache
from cvr_adresse_checker.filer import InputPost


@dataclass(frozen=True)
class Indstillinger:
    idag: date
    nu: datetime
    max_cache_alder: timedelta | None
    kun_cache: bool = False


@dataclass
class Statistik:
    api_opslag: int = 0
    cache_hits: int = 0
    afbrudt_aarsag: str = ""


def _vaelg_virksomhed(cvr_nummer: str, data: Any) -> Any:
    if not isinstance(data, list):
        raise ApiFejl("Ugyldigt response-format: forventede en liste")
    for v in data:
        if isinstance(v, dict) and str(v.get("cvrNummer")) == cvr_nummer:
            return v
    if not data:
        raise IkkeFundet("Ikke fundet i CVR")
    raise ApiFejl("Ugyldigt response-format: svaret indeholder ikke det ønskede CVR-nummer")


def analyser_alle(
    poster: list[InputPost],
    klient: CvrDevKlient | None,
    cache: RaaCache,
    indstillinger: Indstillinger,
    fremskridt: Callable[[int, int, Resultat], None] = lambda i, n, r: None,
) -> tuple[list[Resultat], Statistik]:
    statistik = Statistik()
    resultater: list[Resultat] = []
    for i, post in enumerate(poster, start=1):
        resultat = _analyser_en(post, klient, cache, indstillinger, statistik)
        resultater.append(resultat)
        fremskridt(i, len(poster), resultat)
    return resultater, statistik


def _analyser_en(
    post: InputPost,
    klient: CvrDevKlient | None,
    cache: RaaCache,
    ind: Indstillinger,
    statistik: Statistik,
) -> Resultat:
    cvr_nummer = post.cvr_nummer
    if cvr_nummer is None:
        return fejl(post.raa, "Ugyldigt CVR-nummer (skal være 8 cifre og ikke starte med 0)")

    indgang = cache.hent(cvr_nummer, ind.max_cache_alder, ind.nu)
    kilde = "cache"
    try:
        if indgang is not None:
            statistik.cache_hits += 1
            if indgang.http_status == 404:
                raise IkkeFundet("Ikke fundet i CVR (cachet svar)")
            data = indgang.data
        elif ind.kun_cache or klient is None:
            return fejl(cvr_nummer, "Intet (gyldigt) cachet råsvar, og API-kald er slået fra")
        elif statistik.afbrudt_aarsag:
            return fejl(cvr_nummer, f"Ikke hentet: API-kald stoppet ({statistik.afbrudt_aarsag})")
        else:
            kilde = "api"
            statistik.api_opslag += 1
            try:
                data = klient.hent_virksomhed(cvr_nummer)
            except IkkeFundet:
                cache.gem(cvr_nummer, 404, None, ind.nu)
                raise
            cache.gem(cvr_nummer, 200, data, ind.nu)
        virksomhed = _vaelg_virksomhed(cvr_nummer, data)
    except FatalApiFejl as fejlen:
        statistik.afbrudt_aarsag = str(fejlen)
        return replace(fejl(cvr_nummer, str(fejlen)), kilde=kilde)
    except ApiFejl as fejlen:
        return replace(fejl(cvr_nummer, str(fejlen)), kilde=kilde)

    return replace(analyser_virksomhed(cvr_nummer, virksomhed, ind.idag), kilde=kilde)


def opsummer(resultater: list[Resultat]) -> dict[str, int]:
    antal = {s.value: 0 for s in Status}
    for r in resultater:
        antal[r.status.value] += 1
    antal["MATCH (aktive, i matches.csv)"] = sum(r.er_aktivt_match for r in resultater)
    return antal
