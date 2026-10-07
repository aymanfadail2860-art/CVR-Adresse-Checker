# CVR Adresse Checker

Finder **aktive** virksomheder med **højst 15 årsværk**, der **reelt** har
skiftet fysisk beliggenhedsadresse inden for de seneste 3 kalendermåneder.
Data kommer fra [cvr.dev](https://cvr.dev).
Værktøjet er kun Python-standardbibliotek: ingen database, ingen frontend og
ingen eksterne pakker.

## Kom i gang

```bash
# Python 3.10+ – ingen afhængigheder at installere
export CVR_DEV_API_KEY="din-nøgle"     # Windows PowerShell: $env:CVR_DEV_API_KEY="din-nøgle"
python -m cvr_adresse_checker --test-noegle          # gratis test af nøglen
python -m cvr_adresse_checker cvr_liste.txt          # kør analysen
```

Nøglen læses kun fra miljøvariablen `CVR_DEV_API_KEY`. Den logges, gemmes og
skrives aldrig ud. Hvis variablen ikke er sat, sendes kaldet uden nøgle. Det
virker kun i miljøer, hvor en proxy selv tilføjer nøglen.

## Input

En `.txt`- eller `.csv`-fil:

- **TXT:** ét CVR-nummer pr. linje.
- **CSV:** hvis første linje er en overskrift med en kolonne, der indeholder
  "cvr" (fx `CVR-nr`), bruges den kolonne. Ellers bruges første kolonne.
  Separatoren kan være `;`, `,` eller tab.
- Formater som `DK12345678` og `1234 5678` accepteres.
- Tomme linjer og linjer der starter med `#` springes over.
- Dubletter fjernes.
- Ugyldige numre kommer med i outputtet som `FEJL`, og der laves intet API-kald
  for dem.

Se `eksempel_input.csv`.

## Output

Filerne skrives til `resultater/<dato>/`. Det kan ændres med `-o`.

| Fil | Indhold |
|---|---|
| `matches.csv` | Kun **aktive** virksomheder med status `MATCH` |
| `alle_resultater.csv` | Alle analyserede CVR-numre |

Kolonner: `cvr_nummer`, `virksomhedsnavn`, `gammel_adresse`, `ny_adresse`,
`adresseskift_dato`, `dage_siden_adresseskift`, `virksomhedsstatus`, `aktiv`
(JA/NEJ/UKENDT), `seneste_aarsvaerk`, `aarsvaerk_periode` (YYYY-MM), `status`,
`note` og `datakilde` (api/cache). Årsværk skrives med decimalkomma, fx `15,01`.

Filerne bruger `;` som separator og UTF-8 med BOM, så de kan åbnes direkte i
dansk Excel. Separatoren kan ændres med `--separator ","`.

### Status

| Status | Betydning |
|---|---|
| `MATCH` | Reelt adresseskift med `gyldigFra` inden for [i dag − 3 kalendermåneder; i dag] **og** seneste månedlige årsværk ≤ 15 |
| `IKKE_MATCH` | Intet reelt skift, skiftet er ældre end 3 måneder eller ligger i fremtiden, eller årsværk > 15 |
| `UTILSTRÆKKELIGE_DATA` | Data kan ikke afgøre det sikkert (overlap, manglende felter, ingen aktuel adresse, eller reel flytning uden gyldigt månedligt årsværk) |
| `FEJL` | Ugyldigt CVR, ikke fundet, API-fejl, 429/5xx efter retries, ugyldigt response-format |

Ophørte virksomheder kan have status `MATCH`. De er markeret `aktiv=NEJ` med en
note og kommer aldrig i `matches.csv`. Det samme gælder virksomheder under
konkurs, likvidation eller med ukendt status. Kun `sammensatStatus`
"Aktiv"/"Normal" med et åbent livsforløb tæller som aktiv.

## Matchlogik

Kun `beliggenhedsadresse` bruges. `postadresse` indgår ikke.

1. **Samme fysiske adresse:** samme land, samme vej og samme husnummer
   (husnummerFra, bogstavFra, husnummerTil og bogstavTil).
   - **Samme vej:** det normaliserede vejnavn er ens, eller vejkoden er ens i
     samme kommune (ren omdøbning af vejen). Ved normaliseringen ignoreres
     store/små bogstaver, punktum, bindestreg og mellemrum, og "Aa" tæller
     som "Å".
   - **Ændrer ikke adressen:** et skift i ét af felterne postnummer,
     kommuneKode eller vejkode alene, fx et omlagt postnummer eller
     kommunalreformen 2007 med samme postnummer.
   - **Anden by:** skifter **både** postnummer og kommuneKode, er det en reel
     flytning, også med samme vejnavn og husnummer (fx Stationsvej 1,
     4000 Roskilde → Stationsvej 1, 8000 Aarhus). Er det ene felt ændret,
     mens det andet mangler, kan det ikke afgøres.
   - **Indgår slet ikke:** etage, sidedør, c/o, postboks, adresseId,
     sidstOpdateret og DAR-validering.
   - **Reel flytning kræver:** ny vej, nyt husnummer, nyt husbogstav, et
     andet land, eller nyt postnummer og ny kommune samtidig.
2. **Sortering:** posterne sorteres efter `periode.gyldigFra`.
3. **Segmenter:** fra den aktuelle post (`gyldigTil = null`) går værktøjet
   baglæns. Fortløbende poster med samme fysiske adresse er ét segment, så
   tekniske historikposter og interne flytninger aldrig tæller.
4. **Flytning:** den første tidligere post med en anden fysisk adresse er den
   gamle adresse. Flyttedatoen er `gyldigFra` for det aktuelle segments første
   post.
5. **Resultat:** `MATCH` hvis `flyttedato >= i dag − 3 kalendermåneder` og
   flyttedatoen ikke ligger i fremtiden.

Systemet gætter ikke. Ved usikker historik afgøres status sådan:

- **IKKE_MATCH med note om ufuldstændig ældre historik:** usikkerheden ligger
  med sikkerhed før 3-månedersgrænsen. Det gælder, når både den aktuelle
  adresse har været uændret siden før grænsen, og den usikre post sluttede
  før grænsen.
- **UTILSTRÆKKELIGE_DATA:** usikkerheden berører de seneste 3 måneder.
  Usikkerheden kan fx være overlappende poster med forskellige adresser,
  manglende vejnavn eller husnummer, eller en post med vejkode uden vejnavn.
- **UTILSTRÆKKELIGE_DATA altid:** manglende `gyldigFra`, ingen aktuel adresse
  og en aktuel adresse uden vejnavn eller husnummer.

### Årsværk (størrelseskrav)

- **Kilde:** `erstMaanedsbeskaeftigelse` i det samme råsvar, så der er intet
  ekstra API-kald. Værktøjet bruger `antalAarsvaerk` fra den seneste måned
  (højeste år og måned).
- **Bruges ikke:** den gamle serie `maanedsbeskaeftigelse` (som stoppede i
  2019), gennemsnit, kvartals- og årsdata samt antal ansatte.
- **Grænse:** `antalAarsvaerk <= 15` opfylder kravet. Præcis 15 er tilladt.
- **Uden tal:** hvis den seneste måned ikke har en gyldig numerisk værdi, eller
  der ingen månedsdata er, giver en ellers matchende virksomhed
  `UTILSTRÆKKELIGE_DATA`. Værktøjet falder ikke tilbage til ældre måneder.

## Cache og API-forbrug

- Hvert CVR-nummer slås op med ét kald: `GET /api/cvr/virksomhed?cvr_nummer=…`.
- Rå svar gemmes i `cache/<cvr>.json`, også "ikke fundet"-svar.
- Svar, der er yngre end `--max-cache-alder-timer`, genbruges uden nyt kald.
  Standarden er 24 timer.
- `--kun-cache` laver ingen API-kald overhovedet.
- `--max-cache-alder-timer 0` tvinger nye opslag.
- **Retry:** 429, 5xx og netværksfejl giver op til 5 forsøg med eksponentiel
  backoff (2, 4, 8, 16 s). `Retry-After` respekteres. Timeout er 30 s
  (`--timeout`).
- **Fatale fejl:** ved 401, 402 eller 403 stopper alle videre API-kald.
  Resten af listen analyseres stadig fra cachen, hvor det er muligt.

## Udvikling

```bash
python -m unittest          # eller: pytest
ruff check . && ruff format --check .
mypy --strict
```
