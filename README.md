# CVR Adresse Checker

Finder virksomheder, der **reelt** har skiftet fysisk beliggenhedsadresse inden
for de seneste 3 kalendermåneder. Data kommer fra [cvr.dev](https://cvr.dev).
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
(JA/NEJ/UKENDT), `status`, `note` og `datakilde` (api/cache).

Filerne bruger `;` som separator og UTF-8 med BOM, så de kan åbnes direkte i
dansk Excel. Separatoren kan ændres med `--separator ","`.

### Status

| Status | Betydning |
|---|---|
| `MATCH` | Reelt adresseskift med `gyldigFra` inden for [i dag − 3 kalendermåneder; i dag] |
| `IKKE_MATCH` | Intet reelt skift, eller skiftet er ældre end 3 måneder eller ligger i fremtiden |
| `UTILSTRÆKKELIGE_DATA` | Data kan ikke afgøre det sikkert (overlap, manglende felter, ingen aktuel adresse) |
| `FEJL` | Ugyldigt CVR, ikke fundet, API-fejl, 429/5xx efter retries, ugyldigt response-format |

Ophørte virksomheder kan have status `MATCH`. De er markeret `aktiv=NEJ` med en
note og kommer aldrig i `matches.csv`. Det samme gælder virksomheder under
konkurs, likvidation eller med ukendt status. Kun `sammensatStatus`
"Aktiv"/"Normal" med et åbent livsforløb tæller som aktiv.

## Matchlogik

Kun `beliggenhedsadresse` bruges. `postadresse` indgår ikke.

1. **Fysisk adressenøgle:** land, kommunekode, vej, husnummerFra, bogstavFra,
   husnummerTil, bogstavTil og postnummer.
   - Vejkode bruges frem for vejnavn, når begge poster har vejkode.
   - Tekst trimmes og sammenlignes uden hensyn til store/små bogstaver.
   - **Indgår ikke:** etage, sidedør, c/o, postboks, adresseId, sidstOpdateret
     og DAR-validering.
2. **Sortering:** posterne sorteres efter `periode.gyldigFra`.
3. **Segmenter:** fra den aktuelle post (`gyldigTil = null`) går værktøjet
   baglæns. Fortløbende poster med samme fysiske nøgle er ét segment, så
   tekniske historikposter og interne flytninger aldrig tæller.
4. **Flytning:** den første tidligere post med en anden nøgle er den gamle
   adresse. Flyttedatoen er `gyldigFra` for det aktuelle segments første post.
5. **Resultat:** `MATCH` hvis `flyttedato >= i dag − 3 kalendermåneder` og
   flyttedatoen ikke ligger i fremtiden.

Systemet gætter ikke. Disse tilfælde giver `UTILSTRÆKKELIGE_DATA`:

- overlappende poster med forskellige adresser
- flere aktuelle adresser
- manglende `gyldigFra`
- manglende nødvendige felter i de poster, der afgør resultatet
- en post med vejkode, der skal sammenlignes med en post, der kun har vejnavn

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
