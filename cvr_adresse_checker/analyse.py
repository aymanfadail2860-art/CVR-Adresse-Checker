"""Matchlogik: har virksomheden reelt skiftet beliggenhedsadresse for nylig?

Fremgangsmåde:
1. Parse alle poster i ``beliggenhedsadresse`` og sorter dem efter gyldigFra.
2. Start i den aktuelle post (gyldigTil = null) og gå baglæns.
   Fortløbende poster med samme fysiske adresse er ét segment; de tæller
   aldrig som flytning (etage/dør, adresseId, vejnavnstekst, c/o osv.).
3. Første tidligere post med en anden fysisk adresse er den gamle adresse.
   Flyttedatoen er gyldigFra for det aktuelle segments første post.
4. MATCH hvis flyttedatoen ligger i [i dag minus 3 kalendermåneder; i dag]
   OG seneste månedlige årsværk (erstMaanedsbeskaeftigelse) er <= 15.

Overlap, modstridende eller manglende data, der påvirker afgørelsen, giver
UTILSTRÆKKELIGE_DATA. Systemet gætter ikke.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from cvr_adresse_checker.adresse import (
    Adressepost,
    UgyldigtFormat,
    parse_adressepost,
    parse_dato,
    samme_fysiske_adresse,
)

AKTIVE_STATUSSER = frozenset({"aktiv", "normal"})
MAX_AARSVAERK = Decimal("15")


class Status(str, Enum):
    MATCH = "MATCH"
    IKKE_MATCH = "IKKE_MATCH"
    UTILSTRAEKKELIGE_DATA = "UTILSTRÆKKELIGE_DATA"
    FEJL = "FEJL"


@dataclass(frozen=True)
class Resultat:
    cvr_nummer: str
    status: Status
    note: str = ""
    virksomhedsnavn: str = ""
    gammel_adresse: str = ""
    ny_adresse: str = ""
    adresseskift_dato: date | None = None
    dage_siden_adresseskift: int | None = None
    virksomhedsstatus: str = ""
    aktiv: bool | None = None
    seneste_aarsvaerk: Decimal | None = None
    aarsvaerk_periode: str = ""
    kilde: str = field(default="", compare=False)

    @property
    def er_aktivt_match(self) -> bool:
        return self.status is Status.MATCH and self.aktiv is True


def fejl(cvr_nummer: str, note: str) -> Resultat:
    return Resultat(cvr_nummer=cvr_nummer, status=Status.FEJL, note=note)


def minus_kalendermaaneder(dag: date, maaneder: int) -> date:
    """Træk kalendermåneder fra; dagen klemmes til månedens sidste dag."""
    total = dag.year * 12 + (dag.month - 1) - maaneder
    aar, maaned = divmod(total, 12)
    maaned += 1
    sidste_dag = calendar.monthrange(aar, maaned)[1]
    return date(aar, maaned, min(dag.day, sidste_dag))


def _objekt(vaerdi: object, navn: str) -> dict[str, Any]:
    if vaerdi is None:
        return {}
    if not isinstance(vaerdi, dict):
        raise UgyldigtFormat(f"{navn} er ikke et objekt")
    return vaerdi


def _liste(vaerdi: object, navn: str) -> list[Any]:
    if vaerdi is None:
        return []
    if not isinstance(vaerdi, list):
        raise UgyldigtFormat(f"{navn} er ikke en liste")
    return vaerdi


def _virksomhedsnavn(virksomhed: dict[str, Any]) -> str:
    metadata = _objekt(virksomhed.get("virksomhedMetadata"), "virksomhedMetadata")
    nyeste = _objekt(metadata.get("nyesteNavn"), "nyesteNavn")
    navn = nyeste.get("navn")
    if isinstance(navn, str) and navn.strip():
        return navn.strip()
    for post in reversed(_liste(virksomhed.get("navne"), "navne")):
        post = _objekt(post, "navne[]")
        if isinstance(post.get("navn"), str):
            return str(post["navn"]).strip()
    return ""


def bestem_virksomhedsstatus(virksomhed: dict[str, Any]) -> tuple[str, bool | None]:
    """Returnér (statustekst, aktiv). aktiv er None, hvis status er ukendt.

    Kun en eksplicit aktiv status ('Aktiv'/'Normal') uden afsluttet
    livsforløb tæller som aktiv. Konkurs, likvidation, ophør osv. er ikke aktive.
    """
    metadata = _objekt(virksomhed.get("virksomhedMetadata"), "virksomhedMetadata")
    sammensat = metadata.get("sammensatStatus")
    sammensat_tekst = sammensat.strip() if isinstance(sammensat, str) else ""

    livsforloeb = _liste(virksomhed.get("livsforloeb"), "livsforloeb")
    ophoersdato: date | None = None
    if livsforloeb:
        perioder = [
            _objekt(_objekt(p, "livsforloeb[]").get("periode"), "livsforloeb.periode") for p in livsforloeb
        ]
        slutdatoer = [parse_dato(p.get("gyldigTil"), "livsforloeb.gyldigTil") for p in perioder]
        if all(d is not None for d in slutdatoer):
            ophoersdato = max(d for d in slutdatoer if d is not None)

    if ophoersdato is not None:
        tekst = f"Ophørt {ophoersdato.isoformat()}"
        if sammensat_tekst and sammensat_tekst.casefold() not in AKTIVE_STATUSSER:
            tekst = f"{sammensat_tekst} (livsforløb slut {ophoersdato.isoformat()})"
        return tekst, False
    if not sammensat_tekst:
        return "Ukendt", None
    return sammensat_tekst, sammensat_tekst.casefold() in AKTIVE_STATUSSER


def _aarsvaerk_tal(vaerdi: object) -> Decimal | None:
    if isinstance(vaerdi, bool) or vaerdi is None:
        return None
    if isinstance(vaerdi, (int, float, str)):
        try:
            tal = Decimal(str(vaerdi).strip().replace(",", "."))
        except InvalidOperation:
            return None
        return tal if tal.is_finite() and tal >= 0 else None
    return None


def seneste_maanedlige_aarsvaerk(virksomhed: dict[str, Any]) -> tuple[Decimal | None, str]:
    """Seneste månedlige årsværk fra erstMaanedsbeskaeftigelse: (værdi, 'YYYY-MM').

    Den ældre serie ``maanedsbeskaeftigelse`` stoppede i 2019 og bruges ikke.
    Kvartals-, års- og ansattal bruges heller ikke. Værdien er None, hvis den
    seneste måned ikke har en gyldig numerisk antalAarsvaerk; der falder ikke
    tilbage til ældre måneder.
    """
    poster: list[tuple[int, int, object]] = []
    for post in _liste(virksomhed.get("erstMaanedsbeskaeftigelse"), "erstMaanedsbeskaeftigelse"):
        post = _objekt(post, "erstMaanedsbeskaeftigelse[]")
        aar, maaned = post.get("aar"), post.get("maaned")
        if isinstance(aar, int) and isinstance(maaned, int) and 1 <= maaned <= 12:
            poster.append((aar, maaned, post.get("antalAarsvaerk")))
    if not poster:
        metadata = _objekt(virksomhed.get("virksomhedMetadata"), "virksomhedMetadata")
        nyeste = _objekt(metadata.get("nyesteErstMaanedsbeskaeftigelse"), "nyesteErstMaanedsbeskaeftigelse")
        aar, maaned = nyeste.get("aar"), nyeste.get("maaned")
        if not (isinstance(aar, int) and isinstance(maaned, int) and 1 <= maaned <= 12):
            return None, ""
        poster.append((aar, maaned, nyeste.get("antalAarsvaerk")))
    aar, maaned, vaerdi = max(poster, key=lambda p: (p[0], p[1]))
    return _aarsvaerk_tal(vaerdi), f"{aar:04d}-{maaned:02d}"


def _vurder_aarsvaerk(resultat: Resultat) -> Resultat:
    """Størrelseskrav for MATCH: seneste månedlige årsværk <= 15."""
    if resultat.status is not Status.MATCH:
        return resultat
    if resultat.seneste_aarsvaerk is None:
        periode = f" (seneste periode {resultat.aarsvaerk_periode})" if resultat.aarsvaerk_periode else ""
        return replace(
            resultat,
            status=Status.UTILSTRAEKKELIGE_DATA,
            note=_saml(
                resultat.note,
                "Reel flytning inden for 3 måneder, men ingen gyldig månedlig årsværksværdi"
                f"{periode} - kan ikke bekræfte højst 15 årsværk",
            ),
        )
    if resultat.seneste_aarsvaerk > MAX_AARSVAERK:
        return replace(
            resultat,
            status=Status.IKKE_MATCH,
            note=_saml(
                resultat.note,
                "Reel flytning inden for 3 måneder, men årsværk overstiger 15 "
                f"({resultat.seneste_aarsvaerk} i {resultat.aarsvaerk_periode})",
            ),
        )
    return resultat


def _beskriv_teknisk_aendring(aeldre: Adressepost, nyere: Adressepost) -> str:
    if (aeldre.etage, aeldre.sidedoer) != (nyere.etage, nyere.sidedoer):
        return "kun etage/sidedør ændret"
    if aeldre.vejnavn != nyere.vejnavn:
        return "kun vejnavnstekst ændret (samme vejkode)"
    return "teknisk historikpost uden fysisk ændring"


def _utilstraekkelig(basis: Resultat, note: str) -> Resultat:
    return replace(basis, status=Status.UTILSTRAEKKELIGE_DATA, note=note)


def analyser_virksomhed(cvr_nummer: str, raa: object, idag: date) -> Resultat:
    """Analysér ét virksomhedsobjekt fra cvr.dev's /cvr/virksomhed."""
    try:
        return _analyser(cvr_nummer, raa, idag)
    except UgyldigtFormat as fejlen:
        return fejl(cvr_nummer, f"Ugyldigt response-format: {fejlen}")


def _analyser(cvr_nummer: str, raa: object, idag: date) -> Resultat:
    if not isinstance(raa, dict):
        raise UgyldigtFormat("virksomhed er ikke et objekt")
    if str(raa.get("cvrNummer")) != cvr_nummer:
        raise UgyldigtFormat(f"cvrNummer {raa.get('cvrNummer')!r} matcher ikke {cvr_nummer}")
    if "beliggenhedsadresse" not in raa:
        raise UgyldigtFormat("feltet beliggenhedsadresse mangler")

    statustekst, aktiv = bestem_virksomhedsstatus(raa)
    aarsvaerk, aarsvaerk_periode = seneste_maanedlige_aarsvaerk(raa)
    basis = Resultat(
        cvr_nummer=cvr_nummer,
        status=Status.IKKE_MATCH,
        virksomhedsnavn=_virksomhedsnavn(raa),
        virksomhedsstatus=statustekst,
        aktiv=aktiv,
        seneste_aarsvaerk=aarsvaerk,
        aarsvaerk_periode=aarsvaerk_periode,
    )
    resultat = _vurder_aarsvaerk(_vurder_adressehistorik(basis, raa, idag))
    if resultat.status is Status.MATCH and aktiv is not True:
        resultat = replace(
            resultat,
            note=_saml(resultat.note, f"Ikke aktiv ({statustekst}) - udelukket fra matches.csv"),
        )
    return resultat


def _saml(*noter: str) -> str:
    return "; ".join(n for n in noter if n)


def _vurder_adressehistorik(basis: Resultat, raa: dict[str, Any], idag: date) -> Resultat:
    poster = [parse_adressepost(p) for p in _liste(raa["beliggenhedsadresse"], "beliggenhedsadresse")]
    if not poster:
        return _utilstraekkelig(basis, "Ingen beliggenhedsadresse i CVR-data")
    if any(p.gyldig_fra is None for p in poster):
        return _utilstraekkelig(basis, "Adressepost uden periode.gyldigFra")
    for p in poster:
        if p.gyldig_til is not None and p.gyldig_til < _dato(p):
            return _utilstraekkelig(basis, f"Adressepost med gyldigTil før gyldigFra ({p.visning})")

    poster.sort(key=lambda p: (_dato(p), p.gyldig_til or date.max))
    aktuel = poster[-1]
    if not aktuel.er_aktuel:
        if any(p.er_aktuel for p in poster):
            return _utilstraekkelig(
                basis, "Modstridende historik: den aktuelle adressepost er ikke den seneste"
            )
        return _utilstraekkelig(basis, "Ingen aktuel beliggenhedsadresse (alle poster er afsluttet)")
    basis = replace(basis, ny_adresse=aktuel.visning)
    mangler = aktuel.manglende_felter()
    if mangler:
        return _utilstraekkelig(basis, f"Aktuel adresse mangler {', '.join(mangler)}")

    cutoff = minus_kalendermaaneder(idag, 3)
    stoej: list[str] = []
    segment_start = aktuel
    gammel: Adressepost | None = None
    for aeldre in reversed(poster[:-1]):
        samme = samme_fysiske_adresse(aeldre, segment_start)
        if samme is None:
            felter = aeldre.manglende_felter() or ["vejkode/vejnavn kan ikke sammenlignes"]
            return _utilstraekkelig(
                basis,
                f"Kan ikke afgøre om adressen er ændret pr. {segment_start.gyldig_fra}: "
                f"tidligere adressepost mangler {', '.join(felter)}",
            )
        overlap = aeldre.gyldig_til is None or aeldre.gyldig_til >= _dato(segment_start)
        if samme:
            if _dato(segment_start) >= cutoff and aeldre != segment_start:
                stoej.append(
                    f"{_beskriv_teknisk_aendring(aeldre, segment_start)} pr. {segment_start.gyldig_fra}"
                )
            segment_start = aeldre
            continue
        if overlap:
            return _utilstraekkelig(
                basis,
                "Overlappende adresseposter med forskellige adresser "
                f"({aeldre.visning} / {segment_start.visning})",
            )
        gammel = aeldre
        break

    stoej_note = _saml(*(f"Ikke flytning: {s}" for s in reversed(stoej)))
    if gammel is None:
        note = "Ingen reel ændring af beliggenhedsadressen i historikken"
        return replace(basis, status=Status.IKKE_MATCH, note=_saml(note, stoej_note))

    flyttedato = _dato(segment_start)
    dage = (idag - flyttedato).days
    resultat = replace(
        basis,
        gammel_adresse=gammel.visning,
        adresseskift_dato=flyttedato,
        dage_siden_adresseskift=dage,
    )
    hul_note = ""
    if gammel.gyldig_til is not None and gammel.gyldig_til + timedelta(days=1) < flyttedato:
        hul_note = f"Hul i adressehistorikken mellem {gammel.gyldig_til} og {flyttedato}"

    if flyttedato > idag:
        note = f"Fremtidigt adresseskift pr. {flyttedato} er endnu ikke trådt i kraft"
        return replace(resultat, status=Status.IKKE_MATCH, note=_saml(note, hul_note, stoej_note))
    if flyttedato >= cutoff:
        return replace(resultat, status=Status.MATCH, note=_saml(hul_note, stoej_note))
    note = f"Seneste reelle adresseskift er ældre end 3 måneder (før {cutoff})"
    return replace(resultat, status=Status.IKKE_MATCH, note=_saml(note, hul_note, stoej_note))


def _dato(post: Adressepost) -> date:
    if post.gyldig_fra is None:  # pragma: no cover - tjekket før brug
        raise UgyldigtFormat("gyldigFra mangler")
    return post.gyldig_fra
