"""Byggeklodser til syntetiske cvr.dev-svar i tests."""

from __future__ import annotations

from typing import Any

CVR = "12345674"


def adresse(
    gyldig_fra: str | None,
    gyldig_til: str | None = None,
    *,
    vejnavn: str | None = "Industrivej",
    vejkode: int | None = 1234,
    husnummer: int | None = 10,
    bogstav: str | None = None,
    etage: str | None = None,
    sidedoer: str | None = None,
    postnummer: int | None = 2600,
    postdistrikt: str = "Glostrup",
    kommunekode: int | None = 161,
    landekode: str | None = "DK",
    adresse_id: str | None = None,
    conavn: str | None = None,
    postboks: str | None = None,
    sidst_opdateret: str = "2020-01-01T00:00:00.000+01:00",
) -> dict[str, Any]:
    return {
        "adresseId": adresse_id,
        "bogstavFra": bogstav,
        "bogstavTil": None,
        "bynavn": None,
        "conavn": conavn,
        "etage": etage,
        "fritekst": None,
        "husnummerFra": husnummer,
        "husnummerTil": None,
        "kommune": (
            None if kommunekode is None else {"kommuneKode": kommunekode, "kommuneNavn": "X", "periode": {}}
        ),
        "landekode": landekode,
        "periode": {"gyldigFra": gyldig_fra, "gyldigTil": gyldig_til},
        "postboks": postboks,
        "postdistrikt": postdistrikt,
        "postnummer": postnummer,
        "sidedoer": sidedoer,
        "sidstOpdateret": sidst_opdateret,
        "sidstValideret": None,
        "vejkode": vejkode,
        "vejnavn": vejnavn,
    }


def virksomhed(
    adresser: list[dict[str, Any]],
    *,
    cvr: str = CVR,
    status: str | None = "Aktiv",
    ophoert: str | None = None,
    navn: str = "Test ApS",
) -> dict[str, Any]:
    return {
        "cvrNummer": int(cvr),
        "beliggenhedsadresse": adresser,
        "postadresse": [],
        "livsforloeb": [{"periode": {"gyldigFra": "2000-01-01", "gyldigTil": ophoert}}],
        "navne": [{"navn": navn, "periode": {"gyldigFra": "2000-01-01", "gyldigTil": None}}],
        "virksomhedMetadata": {
            "nyesteNavn": {"navn": navn},
            "sammensatStatus": status,
        },
    }
