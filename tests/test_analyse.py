from __future__ import annotations

import unittest
from datetime import date
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

    def test_andet_postnummer_er_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", postnummer=2605)])
        self.assertEqual(r.status, Status.MATCH)

    def test_anden_kommune_er_match(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-08-31"), adresse("2026-09-01", kommunekode=101)])
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


class TestUtilstraekkeligeData(unittest.TestCase):
    def test_ingen_adresser(self) -> None:
        self.assertEqual(analyser([]).status, Status.UTILSTRAEKKELIGE_DATA)

    def test_tidligere_post_mangler_husnummer(self) -> None:
        r = analyser([adresse("2015-01-01", "2026-09-11", husnummer=None), adresse("2026-09-12")])
        self.assertEqual(r.status, Status.UTILSTRAEKKELIGE_DATA)
        self.assertIn("husnummerFra", r.note)

    def test_aktuel_adresse_mangler_postnummer(self) -> None:
        r = analyser([adresse("2026-09-12", postnummer=None)])
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
        self.assertIn("Overlappende", r.note)

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
