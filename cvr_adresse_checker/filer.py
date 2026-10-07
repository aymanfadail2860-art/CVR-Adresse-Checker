"""Indlæsning af CVR-numre (CSV/TXT) og skrivning af resultat-CSV'er."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cvr_adresse_checker.analyse import Resultat

_SEPARATORER = re.compile(r"[;,\t]")
_CVR = re.compile(r"[1-9]\d{7}")

KOLONNER = (
    "cvr_nummer",
    "virksomhedsnavn",
    "gammel_adresse",
    "ny_adresse",
    "adresseskift_dato",
    "dage_siden_adresseskift",
    "virksomhedsstatus",
    "aktiv",
    "status",
    "note",
    "datakilde",
)


@dataclass(frozen=True)
class InputPost:
    """Én linje fra inputfilen. cvr_nummer er None, hvis værdien er ugyldig."""

    raa: str
    cvr_nummer: str | None


@dataclass(frozen=True)
class Input:
    poster: list[InputPost]
    dubletter: int


def normaliser_cvr(vaerdi: str) -> str | None:
    """Returnér et gyldigt 8-cifret CVR-nummer eller None.

    Tillader mellemrum, anførselstegn og præfikset 'DK' (fx 'DK 1234 5678').
    """
    renset = "".join(vaerdi.strip().strip("\"'").split())
    if renset[:2].upper() == "DK":
        renset = renset[2:]
    return renset if _CVR.fullmatch(renset) else None


def _laes_tekst(sti: Path) -> str:
    data = sti.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")  # Typisk for CSV gemt fra dansk Excel.


def laes_input(sti: Path) -> Input:
    """Læs CVR-numre fra en TXT- eller CSV-fil.

    - TXT: ét CVR-nummer pr. linje.
    - CSV: hvis første linje er en overskrift med en kolonne, der indeholder
      'cvr', bruges den kolonne; ellers første kolonne.
    Tomme linjer og linjer der starter med '#' ignoreres. Dubletter fjernes.
    """
    kolonne = 0
    foerste = True
    poster: list[InputPost] = []
    sete: set[str] = set()
    dubletter = 0
    for linje in _laes_tekst(sti).splitlines():
        if not linje.strip() or linje.lstrip().startswith("#"):
            continue
        felter = [f.strip().strip("\"'") for f in _SEPARATORER.split(linje)]
        if foerste:
            foerste = False
            overskrift = [i for i, f in enumerate(felter) if "cvr" in f.casefold()]
            if overskrift and not any(normaliser_cvr(f) for f in felter):
                kolonne = overskrift[0]
                continue
        raa = felter[kolonne] if kolonne < len(felter) else ""
        cvr_nummer = normaliser_cvr(raa)
        noegle = cvr_nummer or f"ugyldig:{raa}"
        if noegle in sete:
            dubletter += 1
            continue
        sete.add(noegle)
        poster.append(InputPost(raa=raa, cvr_nummer=cvr_nummer))
    return Input(poster=poster, dubletter=dubletter)


def _aktiv_tekst(aktiv: bool | None, har_data: bool) -> str:
    if not har_data:
        return ""
    if aktiv is None:
        return "UKENDT"
    return "JA" if aktiv else "NEJ"


def resultat_raekke(r: Resultat) -> dict[str, str]:
    har_data = bool(r.virksomhedsstatus)
    return {
        "cvr_nummer": r.cvr_nummer,
        "virksomhedsnavn": r.virksomhedsnavn,
        "gammel_adresse": r.gammel_adresse,
        "ny_adresse": r.ny_adresse,
        "adresseskift_dato": r.adresseskift_dato.isoformat() if r.adresseskift_dato else "",
        "dage_siden_adresseskift": (
            "" if r.dage_siden_adresseskift is None else str(r.dage_siden_adresseskift)
        ),
        "virksomhedsstatus": r.virksomhedsstatus,
        "aktiv": _aktiv_tekst(r.aktiv, har_data),
        "status": r.status.value,
        "note": r.note,
        "datakilde": r.kilde,
    }


def skriv_csv(sti: Path, resultater: Iterable[Resultat], separator: str = ";") -> None:
    """Skriv CSV med BOM (utf-8-sig), så Excel viser æ/ø/å korrekt."""
    sti.parent.mkdir(parents=True, exist_ok=True)
    with sti.open("w", encoding="utf-8-sig", newline="") as fil:
        skriver = csv.DictWriter(fil, fieldnames=KOLONNER, delimiter=separator)
        skriver.writeheader()
        for r in resultater:
            skriver.writerow(resultat_raekke(r))
