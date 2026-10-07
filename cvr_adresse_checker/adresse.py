"""Parsing og normalisering af beliggenhedsadresser fra rå CVR-data.

En adressepost i CVR har bl.a. felterne vejkode, vejnavn, husnummerFra,
bogstavFra, husnummerTil, bogstavTil, etage, sidedoer, postnummer,
postdistrikt, landekode, kommune.kommuneKode og periode.gyldigFra/gyldigTil.

Den fysiske placering bestemmes af land, vej og husnummer (inkl. bogstav og
husnummerTil). Ændres kun ét af postnummer, kommunekode eller vejkode, er det
samme adresse (fx omlagte postnumre). Ændres både postnummer og kommunekode,
er det en anden by og dermed en reel flytning, selv med samme vejnavn og
husnummer (fx Stationsvej 1, 4000 Roskilde -> Stationsvej 1, 8000 Aarhus).
Etage, sidedør, c/o, postboks, adresseId og tidsstempler indgår slet ikke.
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


def normaliser_vejnavn(vaerdi: str) -> str:
    """Sammenligningsnøgle for vejnavn: 'Aa' = 'Å', og punktum/bindestreg/mellemrum ignoreres.

    Fx er 'Aastvej' og 'Åstvej' samme vej, og 'J.C. Jacobsens Gade' = 'J. C. Jacobsens Gade'.
    """
    tekst = normaliser_tekst(vaerdi).replace("å", "aa")
    return "".join(t for t in tekst if t not in ".-' ")


def _kode(vaerdi: object) -> str:
    """Normaliseret kode; 0 betyder 'ukendt' i CVR og behandles som manglende."""
    tekst = normaliser_tekst(vaerdi)
    return "" if tekst.strip("0") == "" else tekst


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
        if not (self.vejnavn or (self.vejkode and self.kommunekode)):
            mangler.append("vejnavn")
        if not self.husnummer_fra:
            mangler.append("husnummerFra")
        return mangler


def _kommunekode(post: dict[str, Any]) -> str:
    kommune = post.get("kommune")
    if kommune is None:
        return ""
    if not isinstance(kommune, dict):
        raise UgyldigtFormat("kommune er ikke et objekt")
    return _kode(kommune.get("kommuneKode"))


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
        vejkode=_kode(post.get("vejkode")),
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

    Samme vej, hvis det normaliserede vejnavn er ens, eller hvis vejkoden er
    ens i samme kommune (ren omdøbning). Derefter skal husnummer og bogstav
    (fra/til) være ens. Postnummer, kommunekode eller vejkode alene giver
    ikke en flytning, men postnummer OG kommunekode ændret samtidig gør.
    Returnerer None, hvis det ikke kan afgøres.
    """
    if a.manglende_felter() or b.manglende_felter():
        return None
    if a.landekode != b.landekode:
        return False
    if a.landekode != "dk":
        return (a.fritekst, normaliser_vejnavn(a.vejnavn), a.husnummer_fra) == (
            b.fritekst,
            normaliser_vejnavn(b.vejnavn),
            b.husnummer_fra,
        )
    samme_vejnavn = bool(a.vejnavn and b.vejnavn) and (
        normaliser_vejnavn(a.vejnavn) == normaliser_vejnavn(b.vejnavn)
    )
    samme_vejkode = bool(a.vejkode and a.kommunekode) and (
        (a.kommunekode, a.vejkode) == (b.kommunekode, b.vejkode)
    )
    if samme_vejnavn or samme_vejkode:
        samme_vej = True
    elif a.vejnavn and b.vejnavn:
        samme_vej = False
    else:
        return None
    if not samme_vej or (a.husnummer_fra, a.bogstav_fra, a.husnummer_til, a.bogstav_til) != (
        b.husnummer_fra,
        b.bogstav_fra,
        b.husnummer_til,
        b.bogstav_til,
    ):
        return False
    return _samme_by(a, b)


def _samme_by(a: Adressepost, b: Adressepost) -> bool | None:
    """Samme by, medmindre både postnummer og kommunekode er ændret.

    Mangler et af felterne, mens det andet er ændret, kan det ikke afgøres.
    """
    post_kendt = bool(a.postnummer and b.postnummer)
    kommune_kendt = bool(a.kommunekode and b.kommunekode)
    nyt_post = post_kendt and a.postnummer != b.postnummer
    ny_kommune = kommune_kendt and a.kommunekode != b.kommunekode
    if nyt_post and ny_kommune:
        return False
    if (nyt_post and not kommune_kendt) or (ny_kommune and not post_kendt):
        return None
    return True
