from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

from cvr_adresse_checker.analyse import (
    Resultat,
    Status,
    analyser_virksomhed,
    minus_kalendermaaneder,
)
from tests.hjaelpere import CVR, adresse, virksomhed

IDAG = date(2026, 10, 7)


def analyser(adresser: list[dict[str, Any]], **kw: Any) -> Resultat:
    return analyser_virksomhed(CVR, virksomhed(adresser, **kw), IDAG)


class TestKalendermaaneder(unittest.TestCase):
    def test_almindelig(self) -> None:
        self.assertEqual(minus_kalendermaaneder(date(2026, 10, 7), 3), date(2026, 7, 7))

    def test_aarsskifte(self) -> None:
        self.assertEqual(minus_kalendermaaneder(date(2026, 2, 15), 3), date(2025, 11, 15))

    def test_maanedsslut_klemmes(self) -> None:
        self.assertEqual(minus_kalendermaaneder(date(2026, 5, 31), 3), date(2026, 2, 28))


class TestReelFlytning(unittest.TestCase):
    def test_eksempel_a_flytning_inden_for_3_maaneder_er_match(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11"),
                adresse("2026-09-12", vejnavn="Parkvej", vejkode=5678, husnummer=4),
            ]
        )
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 9, 12))
        self.assertEqual(r.dage_siden_adresseskift, 25)
        self.assertEqual(r.gammel_adresse, "Industrivej 10, 2600 Glostrup")
        self.assertEqual(r.ny_adresse, "Parkvej 4, 2600 Glostrup")
        self.assertTrue(r.er_aktivt_match)

    def test_eksempel_d_flytning_for_5_maaneder_siden_er_ikke_match(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-05-06"),
                adresse("2026-05-07", vejnavn="Parkvej", vejkode=5678, husnummer=4),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 5, 7))
        self.assertIn("ældre end 3 måneder", r.note)

    def test_graensen_praecis_3_maaneder_er_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-07-06"), adresse("2026-07-07", husnummer=12)])
        self.assertEqual(r.status, Status.MATCH)

    def test_dagen_foer_graensen_er_ikke_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-07-05"), adresse("2026-07-06", husnummer=12)])
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_andet_husnummer_bogstav_er_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", bogstav="B")])
        self.assertEqual(r.status, Status.MATCH)

    def test_nyt_husnummer_og_nyt_postnummer_er_match(self) -> None:
        r = analyser(
            [adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", husnummer=12, postnummer=2605)]
        )
        self.assertEqual(r.status, Status.MATCH)

    def test_ny_vej_samme_postnummer_er_match(self) -> None:
        r = analyser(
            [adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", vejnavn="Parkvej", vejkode=None)]
        )
        self.assertEqual(r.status, Status.MATCH)

    def test_andet_land_er_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", landekode="SE")])
        self.assertEqual(r.status, Status.MATCH)

    def test_teknisk_post_efter_flytning_flytter_ikke_datoen(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-08-31"),
                adresse("2026-09-01", "2026-09-20", vejnavn="Parkvej", vejkode=5678),
                adresse("2026-09-21", vejnavn="Parkvej", vejkode=5678, adresse_id="abc"),
            ]
        )
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 9, 1))

    def test_kun_seneste_reelle_flytning_taeller(self) -> None:
        r = analyser(
            [
                adresse("2010-01-01", "2026-08-31", husnummer=1),
                adresse("2026-09-01", "2026-09-30", husnummer=2),
                adresse("2026-10-01", husnummer=1),
            ]
        )
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 10, 1))
        self.assertEqual(r.gammel_adresse, "Industrivej 2, 2600 Glostrup")

    def test_fremtidig_flytning_er_ikke_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-10-31"), adresse("2026-11-01", husnummer=12)])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("endnu ikke trådt i kraft", r.note)


class TestIngenReelFlytning(unittest.TestCase):
    def test_eksempel_b_kun_etage_aendret(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", etage="st"), adresse("2026-09-12", etage="1")])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("kun etage/sidedør ændret", r.note)
        self.assertIsNone(r.adresseskift_dato)

    def test_kun_sidedoer_aendret(self) -> None:
        r = analyser(
            [adresse("2015-01-01", "2026-09-11", sidedoer="tv"), adresse("2026-09-12", sidedoer="th")]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("kun etage/sidedør ændret", r.note)

    def test_eksempel_c_kun_adresse_id_aendret(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", adresse_id="2b7a2d3b")])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("teknisk historikpost", r.note)

    def test_teknisk_historik_som_i_rigtigt_cvr_svar(self) -> None:
        # Svarer til mønstret i cvr.dev-svaret for CVR 10103940: tre poster,
        # én af dem gælder én dag, kun adresseId/tidsstempler ændres.
        r = analyser(
            [
                adresse("1914-01-01", "2026-09-25", sidst_opdateret="2026-09-26T20:30:07.000+02:00"),
                adresse("2026-09-26", "2026-09-26", sidst_opdateret="2026-09-27T20:30:04.000+02:00"),
                adresse("2026-09-27", adresse_id="2b7a2d3b", sidst_opdateret="2026-09-27T20:30:04.000+02:00"),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.note.count("teknisk historikpost"), 2)

    def test_kun_vejnavnstekst_aendret_med_samme_vejkode(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", vejnavn="Industrivej Nord")])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("vejnavnstekst", r.note)

    def test_store_smaa_bogstaver_og_mellemrum_ignoreres(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11", vejkode=None, bogstav="b"),
                adresse("2026-09-12", vejkode=None, vejnavn="  INDUSTRIVEJ ", bogstav="B "),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_kun_co_og_postboks_aendret(self) -> None:
        r = analyser(
            [adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", conavn="Revisor", postboks="12")]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_kun_en_adressepost(self) -> None:
        r = analyser([adresse("2015-01-01")])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.ny_adresse, "Industrivej 10, 2600 Glostrup")

    def test_etage_aendring_efter_gammel_flytning(self) -> None:
        r = analyser(
            [
                adresse("2010-01-01", "2020-12-31", husnummer=2),
                adresse("2021-01-01", "2026-09-11", etage="st"),
                adresse("2026-09-12", etage="2"),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.adresseskift_dato, date(2021, 1, 1))


class TestKodeskiftErIkkeFlytning(unittest.TestCase):
    """Beslutning 2: postnummer/kommuneKode/vejkode alene er ikke en flytning."""

    def test_kun_postnummer_aendret(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", postnummer=2605)])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("kun postnummer ændret", r.note)

    def test_kun_kommunekode_aendret(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", kommunekode=101)])
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_kun_vejkode_aendret_samme_vejnavn(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11"), adresse("2026-09-12", vejkode=9999)])
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_kommune_og_vejkode_aendret_samme_postnummer(self) -> None:
        # Kommunalreform-mønster (som LEGO 2007): ny kommune, vejkode og stavemåde Aa -> Å.
        r = analyser(
            [
                adresse(
                    "2015-01-01",
                    "2026-09-11",
                    vejnavn="Aastvej",
                    vejkode=9890,
                    kommunekode=551,
                    postnummer=7190,
                ),
                adresse("2026-09-12", vejnavn="Åstvej", vejkode=4, kommunekode=530, postnummer=7190),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIsNone(r.adresseskift_dato)

    def test_punktum_og_mellemrum_i_vejnavn_ignoreres(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11", vejnavn="J.C. Jacobsens Gade", vejkode=None),
                adresse("2026-09-12", vejnavn="J. C. Jacobsens Gade", vejkode=None),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_gammel_kodeaendring_skjuler_ikke_reel_flytning_bagved(self) -> None:
        r = analyser(
            [
                adresse("2000-01-01", "2006-12-31", husnummer=2),
                adresse("2007-01-01", "2026-09-11", kommunekode=101, vejkode=7777),
                adresse("2026-09-12", kommunekode=101, vejkode=7777, postnummer=2605),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.adresseskift_dato, date(2007, 1, 1))
        self.assertEqual(r.gammel_adresse, "Industrivej 2, 2600 Glostrup")

    def test_vejkode_0_behandles_som_manglende(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", vejnavn=None, vejkode=0), adresse("2026-09-12")])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)


class TestPostnummerOgKommuneSamtidig(unittest.TestCase):
    """Samme vej og husnummer, men både nyt postnummer og ny kommune = anden by."""

    def stationsvej(self, gyldig_fra: str, gyldig_til: str | None = None, **kw: Any) -> dict[str, Any]:
        return adresse(gyldig_fra, gyldig_til, vejnavn="Stationsvej", husnummer=1, **kw)

    def test_1_stationsvej_roskilde_til_aarhus_er_match(self) -> None:
        r = analyser(
            [
                self.stationsvej("2015-01-01", "2026-09-11", postnummer=4000, kommunekode=265, vejkode=100),
                self.stationsvej("2026-09-12", postnummer=8000, kommunekode=751, vejkode=200),
            ],
            aarsvaerk=8,
        )
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 9, 12))

    def test_1b_stationsvej_men_over_15_aarsvaerk_er_ikke_match(self) -> None:
        r = analyser(
            [
                self.stationsvej("2015-01-01", "2026-09-11", postnummer=4000, kommunekode=265),
                self.stationsvej("2026-09-12", postnummer=8000, kommunekode=751),
            ],
            aarsvaerk=16,
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_1c_stationsvej_for_laengere_end_3_maaneder_siden_er_ikke_match(self) -> None:
        r = analyser(
            [
                self.stationsvej("2015-01-01", "2026-05-01", postnummer=4000, kommunekode=265),
                self.stationsvej("2026-05-02", postnummer=8000, kommunekode=751),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.adresseskift_dato, date(2026, 5, 2))

    def test_2_esplanaden_kun_postnummer_aendret_er_ikke_match(self) -> None:
        r = analyser(
            [
                adresse(
                    "2015-01-01",
                    "2026-09-11",
                    vejnavn="Esplanaden",
                    husnummer=50,
                    postnummer=1098,
                    kommunekode=101,
                    postdistrikt="København K",
                ),
                adresse(
                    "2026-09-12",
                    vejnavn="Esplanaden",
                    husnummer=50,
                    postnummer=1263,
                    kommunekode=101,
                    postdistrikt="København K",
                ),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("kun postnummer ændret", r.note)

    def test_3_kun_kommunekode_aendret_er_ikke_match(self) -> None:
        r = analyser(
            [adresse("2015-01-01", "2026-09-11", kommunekode=165), adresse("2026-09-12", kommunekode=161)]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_4_postnummer_og_kommunekode_aendret_er_reel_flytning(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11", postnummer=2600, kommunekode=161),
                adresse("2026-09-12", postnummer=4000, kommunekode=265),
            ]
        )
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.gammel_adresse, "Industrivej 10, 2600 Glostrup")

    def test_kommune_aendret_men_postnummer_mangler_er_utilstraekkelig(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11", postnummer=None, kommunekode=165),
                adresse("2026-09-12", kommunekode=161),
            ]
        )
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_kun_etage_aendret_samtidig_med_postnummer_er_ikke_match(self) -> None:
        r = analyser(
            [
                adresse("2015-01-01", "2026-09-11", etage="st"),
                adresse("2026-09-12", etage="1", postnummer=2605),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)


class TestUfuldstaendigAeldreHistorik(unittest.TestCase):
    """Beslutning 1: usikkerhed før 3-månedersgrænsen giver IKKE_MATCH."""

    def test_novo_moenster_gammel_post_uden_husnummer(self) -> None:
        r = analyser([adresse("1931-11-28", "2002-10-04", husnummer=None), adresse("2002-10-05")])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("Ufuldstændig ældre adressehistorik", r.note)

    def test_gammelt_overlap_mellem_forskellige_adresser(self) -> None:
        r = analyser([adresse("2010-01-01", "2016-06-30"), adresse("2016-01-01", husnummer=4)])
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("Ufuldstændig ældre adressehistorik", r.note)

    def test_usikkerhed_inden_for_3_maaneder_er_utilstraekkelig(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", husnummer=None), adresse("2026-09-12")])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_gammel_start_men_overlap_ind_i_vinduet_er_utilstraekkelig(self) -> None:
        r = analyser([adresse("2010-01-01", "2026-08-01"), adresse("2026-01-01", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_aaben_gammel_post_med_anden_adresse_er_utilstraekkelig(self) -> None:
        r = analyser([adresse("2010-01-01"), adresse("2016-01-01", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_usikkerhed_efter_teknisk_post_i_vinduet(self) -> None:
        # Aktuelt segment startede før grænsen; en teknisk post i vinduet ændrer ikke det.
        r = analyser(
            [
                adresse("1990-01-01", "2005-12-31", husnummer=None),
                adresse("2006-01-01", "2026-09-11"),
                adresse("2026-09-12", adresse_id="x"),
            ]
        )
        self.assertEqual(r.status, Status.IKKE_MATCH)


class TestUtilstraekkeligeData(unittest.TestCase):
    def test_ingen_adresser(self) -> None:
        self.assertEqual(analyser([]).status, Status.UTILSTRAEKKELIGE_DATA)

    def test_tidligere_post_mangler_husnummer(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", husnummer=None), adresse("2026-09-12")])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)
        self.assertIn("husnummerFra", r.note)

    def test_aktuel_adresse_mangler_husnummer(self) -> None:
        r = analyser([adresse("2026-09-12", husnummer=None)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_ingen_aktuel_adresse(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11")])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_manglende_gyldig_fra(self) -> None:
        r = analyser([adresse(None, "2026-09-11"), adresse("2026-09-12", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_overlap_mellem_forskellige_adresser(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-20"), adresse("2026-09-12", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)
        self.assertIn("overlappende poster", r.note)

    def test_to_aktuelle_forskellige_adresser(self) -> None:
        r = analyser([adresse("2015-01-01"), adresse("2026-09-12", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_samme_gyldig_fra_forskellige_adresser(self) -> None:
        r = analyser([adresse("2026-09-12", "2026-09-12"), adresse("2026-09-12", husnummer=4)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_vejkode_mod_vejnavn_kan_ikke_sammenlignes(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", vejnavn=None), adresse("2026-09-12", vejkode=None)])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_overlap_med_samme_adresse_er_ok(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-20"), adresse("2026-09-12", adresse_id="x")])
        self.assertEqual(r.status, Status.IKKE_MATCH)


class TestAarsvaerk(unittest.TestCase):
    FLYTNING: ClassVar[list[dict[str, Any]]] = [
        adresse("2015-01-01", "2026-09-11"),
        adresse("2026-09-12", husnummer=4),
    ]

    def test_flytning_og_5_aarsvaerk_er_match(self) -> None:
        r = analyser(self.FLYTNING, aarsvaerk=5)
        self.assertEqual(r.status, Status.MATCH)
        self.assertEqual(r.seneste_aarsvaerk, Decimal("5"))
        self.assertEqual(r.aarsvaerk_periode, "2026-07")

    def test_praeciserede_eksempler(self) -> None:
        # Reel flytning + 4 = MATCH, + 15 = MATCH, + 16 = IKKE_MATCH; ingen flytning + 4 = IKKE_MATCH.
        self.assertEqual(analyser(self.FLYTNING, aarsvaerk=4).status, Status.MATCH)
        self.assertEqual(analyser(self.FLYTNING, aarsvaerk=15).status, Status.MATCH)
        self.assertEqual(analyser(self.FLYTNING, aarsvaerk=16).status, Status.IKKE_MATCH)
        self.assertEqual(analyser([adresse("2015-01-01")], aarsvaerk=4).status, Status.IKKE_MATCH)

    def test_udvikling_i_aarsvaerk_paavirker_ikke_resultatet(self) -> None:
        # Kraftigt fald (99 -> 4) eller stigning (1 -> 4) betyder intet; kun seneste værdi tæller.
        for aeldre in (99, 1):
            data = virksomhed(self.FLYTNING, aarsvaerk=4)
            data["erstMaanedsbeskaeftigelse"][0]["antalAarsvaerk"] = aeldre
            self.assertEqual(analyser_virksomhed(CVR, data, IDAG).status, Status.MATCH)

    def test_flytning_og_praecis_15_aarsvaerk_er_match(self) -> None:
        self.assertEqual(analyser(self.FLYTNING, aarsvaerk=15).status, Status.MATCH)
        self.assertEqual(analyser(self.FLYTNING, aarsvaerk=15.0).status, Status.MATCH)

    def test_flytning_og_15_01_aarsvaerk_er_ikke_match(self) -> None:
        r = analyser(self.FLYTNING, aarsvaerk=15.01)
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("årsværk overstiger 15", r.note)

    def test_flytning_og_23_aarsvaerk_er_ikke_match(self) -> None:
        r = analyser(self.FLYTNING, aarsvaerk=23)
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertIn("Reel flytning inden for 3 måneder, men årsværk overstiger 15", r.note)
        self.assertEqual(r.adresseskift_dato, date(2026, 9, 12))

    def test_flytning_uden_aarsvaerksdata_er_utilstraekkelig(self) -> None:
        r = analyser(self.FLYTNING, uden_aarsvaerk=True)
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)
        self.assertIn("kan ikke bekræfte", r.note)

    def test_flytning_med_ikke_numerisk_aarsvaerk_er_utilstraekkelig(self) -> None:
        for vaerdi in (None, "ukendt", True, -1):
            with self.subTest(vaerdi=vaerdi):
                r = analyser(self.FLYTNING, aarsvaerk=vaerdi)
                self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)

    def test_seneste_maaned_bruges_ikke_gennemsnit_eller_aeldre_maaned(self) -> None:
        # Helperen indeholder en ældre måned med 99 årsværk og gamle serier med 1.
        r = analyser(self.FLYTNING, aarsvaerk=12, aarsvaerk_maaned=(2026, 8))
        self.assertEqual(r.seneste_aarsvaerk, Decimal("12"))
        self.assertEqual(r.aarsvaerk_periode, "2026-08")

    def test_lille_virksomhed_uden_nylig_flytning_er_ikke_match(self) -> None:
        r = analyser([adresse("2015-01-01")], aarsvaerk=3)
        self.assertEqual(r.status, Status.IKKE_MATCH)
        self.assertEqual(r.seneste_aarsvaerk, Decimal("3"))

    def test_lille_virksomhed_med_gammel_flytning_er_ikke_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-01-01"), adresse("2026-01-02", husnummer=4)], aarsvaerk=3)
        self.assertEqual(r.status, Status.IKKE_MATCH)

    def test_manglende_aarsvaerk_uden_flytning_forbliver_ikke_match(self) -> None:
        r = analyser([adresse("2015-01-01")], uden_aarsvaerk=True)
        self.assertEqual(r.status, Status.IKKE_MATCH)


class TestStatusOgFormat(unittest.TestCase):
    FLYTNING: ClassVar[list[dict[str, Any]]] = [
        adresse("2015-01-01", "2026-09-11"),
        adresse("2026-09-12", husnummer=4),
    ]

    def test_ophoert_virksomhed_er_ikke_aktivt_match(self) -> None:
        r = analyser(self.FLYTNING, status="Ophørt", ophoert="2026-09-30")
        self.assertEqual(r.status, Status.MATCH)
        self.assertIs(r.aktiv, False)
        self.assertFalse(r.er_aktivt_match)
        self.assertIn("udelukket fra matches.csv", r.note)

    def test_konkurs_er_ikke_aktiv(self) -> None:
        r = analyser(self.FLYTNING, status="UnderKonkurs")
        self.assertFalse(r.er_aktivt_match)

    def test_ukendt_status_er_ikke_aktiv(self) -> None:
        r = analyser(self.FLYTNING, status=None)
        self.assertIsNone(r.aktiv)
        self.assertFalse(r.er_aktivt_match)

    def test_forkert_cvr_i_svar_er_fejl(self) -> None:
        r = analyser_virksomhed("87654321", virksomhed(self.FLYTNING), IDAG)
        self.assertEqual(r.status, Status.FEJL)

    def test_manglende_beliggenhedsadresse_felt_er_fejl(self) -> None:
        data = virksomhed(self.FLYTNING)
        del data["beliggenhedsadresse"]
        self.assertEqual(analyser_virksomhed(CVR, data, IDAG).status, Status.FEJL)

    def test_ugyldig_dato_er_fejl(self) -> None:
        r = analyser([adresse("12/09/2026")])
        self.assertEqual(r.status, Status.FEJL)

    def test_ikke_objekt_er_fejl(self) -> None:
        self.assertEqual(analyser_virksomhed(CVR, ["x"], IDAG).status, Status.FEJL)


if __name__ == "__main__":
    unittest.main()
