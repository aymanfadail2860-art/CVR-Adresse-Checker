"""Parsing og normalisering af beliggenhedsadresser fra rå CVR-data.

En adressepost i CVR har bl.a. felterne vejkode, vejnavn, husnummerFra,
bogstavFra, husnummerTil, bogstavTil, etage, sidedoer, postnummer,
postdistrikt, landekode, kommune.kommuneKode og periode.gyldigFra/gyldigTil.

Den fysiske placering bestemmes af land, kommune, vej, husnummer og
postnummer. Etage, sidedør, c/o, postboks, adresseId og tidsstempler indgår
bevidst ikke, så interne flytninger og tekniske historikposter ikke ligner
en reel flytning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


class UgyldigtFormat(Exception):
    """Rå data har en struktur eller værdi, der ikke kan fortolkes."""


def normaliser_tekst(vaerdi: object) -> str:
    """Trim, saml mellemrum og ignorer store/små bogstaver. None bliver ''."""
    if vaerdi is None:
        return ""
    return " ".join(str(vaerdi).split()).casefold()


def _vis_tekst(vaerdi: object) -> str:
    return "" if vaerdi is None else " ".join(str(vaerdi).split())


def parse_dato(vaerdi: object, felt: str) -> date | None:
    """Parse en CVR-dato ('YYYY-MM-DD' evt. med tidsdel). None tilladt."""
    if vaerdi is None:
        return None
    if not isinstance(vaerdi, str) or len(vaerdi) < 10:
        raise UgyldigtFormat(f"{felt} har ugyldig værdi: {vaerdi!r}")
    try:
        return date.fromisoformat(vaerdi[:10])
    except ValueError as fejl:
        raise UgyldigtFormat(f"{felt} har ugyldig dato: {vaerdi!r}") from fejl


@dataclass(frozen=True)
class Adressepost:
    """Én post fra virksomhedens beliggenhedsadresse-historik."""

    gyldig_fra: date | None
    gyldig_til: date | None
    sidst_opdateret: str
    landekode: str
    kommunekode: str
    vejkode: str
    vejnavn: str
    husnummer_fra: str
    bogstav_fra: str
    husnummer_til: str
    bogstav_til: str
    postnummer: str
    etage: str
    sidedoer: str
    fritekst: str
    visning: str

    @property
    def er_aktuel(self) -> bool:
        return self.gyldig_til is None

    def manglende_felter(self) -> list[str]:
        """Felter der er nødvendige for at fastlægge den fysiske placering."""
        mangler: list[str] = []
        if not self.landekode:
            mangler.append("landekode")
            return mangler
        if self.landekode != "dk":
            # Udenlandske adresser er ofte kun fritekst; land + tekst skal findes.
            if not (self.fritekst or self.vejnavn):
                mangler.append("fritekst/vejnavn")
            return mangler
        if not self.kommunekode:
            mangler.append("kommuneKode")
        if not (self.vejkode or self.vejnavn):
            mangler.append("vejkode/vejnavn")
        if not self.husnummer_fra:
            mangler.append("husnummerFra")
        if not self.postnummer:
            mangler.append("postnummer")
        return mangler


def _kommunekode(post: dict[str, Any]) -> str:
    kommune = post.get("kommune")
    if kommune is None:
        return ""
    if not isinstance(kommune, dict):
        raise UgyldigtFormat("kommune er ikke et objekt")
    return normaliser_tekst(kommune.get("kommuneKode"))


def formater_adresse(post: dict[str, Any]) -> str:
    """Læsbar adresse, fx 'Industrivej 10A, 1. tv, 2600 Glostrup'."""
    vej = " ".join(
        d
        for d in (
            _vis_tekst(post.get("vejnavn")),
            _vis_tekst(post.get("husnummerFra")) + _vis_tekst(post.get("bogstavFra")),
        )
        if d
    )
    husnummer_til = _vis_tekst(post.get("husnummerTil")) + _vis_tekst(post.get("bogstavTil"))
    if husnummer_til:
        vej = f"{vej}-{husnummer_til}"
    etage = _vis_tekst(post.get("etage"))
    sidedoer = _vis_tekst(post.get("sidedoer"))
    placering = " ".join(d for d in (f"{etage}." if etage else "", sidedoer) if d)
    by = " ".join(d for d in (_vis_tekst(post.get("postnummer")), _vis_tekst(post.get("postdistrikt"))) if d)
    dele = [d for d in (vej, placering, by) if d]
    if not dele:
        dele = [_vis_tekst(post.get("fritekst"))]
    landekode = _vis_tekst(post.get("landekode")).upper()
    if landekode and landekode != "DK":
        dele.append(landekode)
    return ", ".join(d for d in dele if d)


def parse_adressepost(post: object) -> Adressepost:
    if not isinstance(post, dict):
        raise UgyldigtFormat("adressepost er ikke et objekt")
    periode = post.get("periode")
    if periode is None:
        periode = {}
    if not isinstance(periode, dict):
        raise UgyldigtFormat("periode er ikke et objekt")
    return Adressepost(
        gyldig_fra=parse_dato(periode.get("gyldigFra"), "gyldigFra"),
        gyldig_til=parse_dato(periode.get("gyldigTil"), "gyldigTil"),
        sidst_opdateret=_vis_tekst(post.get("sidstOpdateret")),
        landekode=normaliser_tekst(post.get("landekode")),
        kommunekode=_kommunekode(post),
        vejkode=normaliser_tekst(post.get("vejkode")),
        vejnavn=normaliser_tekst(post.get("vejnavn")),
        husnummer_fra=normaliser_tekst(post.get("husnummerFra")),
        bogstav_fra=normaliser_tekst(post.get("bogstavFra")),
        husnummer_til=normaliser_tekst(post.get("husnummerTil")),
        bogstav_til=normaliser_tekst(post.get("bogstavTil")),
        postnummer=normaliser_tekst(post.get("postnummer")),
        etage=normaliser_tekst(post.get("etage")),
        sidedoer=normaliser_tekst(post.get("sidedoer")),
        fritekst=normaliser_tekst(post.get("fritekst")),
        visning=formater_adresse(post),
    )


def samme_fysiske_adresse(a: Adressepost, b: Adressepost) -> bool | None:
    """Afgør om to poster beskriver samme fysiske placering.

    Returnerer None, hvis nødvendige felter mangler, så det ikke kan afgøres.
    Vejkode bruges frem for vejnavn, når begge poster har vejkode; så tæller
    en ren omdøbning af vejen ikke som flytning.
    """
    if a.manglende_felter() or b.manglende_felter():
        return None
    if a.landekode != b.landekode:
        return False
    if a.landekode != "dk":
        return (a.fritekst, a.vejnavn, a.husnummer_fra, a.postnummer) == (
            b.fritekst,
            b.vejnavn,
            b.husnummer_fra,
            b.postnummer,
        )
    if a.kommunekode != b.kommunekode:
        return False
    if a.vejkode and b.vejkode:
        samme_vej = a.vejkode == b.vejkode
    elif a.vejnavn and b.vejnavn:
        samme_vej = a.vejnavn == b.vejnavn
    else:
        return None
    return samme_vej and (
        a.husnummer_fra,
        a.bogstav_fra,
        a.husnummer_til,
        a.bogstav_til,
        a.postnummer,
    ) == (
        b.husnummer_fra,
        b.bogstav_fra,
        b.husnummer_til,
        b.bogstav_til,
        b.postnummer,
    )
