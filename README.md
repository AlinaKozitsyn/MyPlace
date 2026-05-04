# Family Project

A web tool that helps families compare Israeli cities side-by-side when deciding where to live. Given a family's income, desired apartment size, children, and each parent's work address, it computes monthly cost estimates, commute times, education and safety indicators, taxes, and other quality-of-life signals for the cities being compared.

## Features

For each city the API returns:

- **Costs** — estimated monthly rent, arnona (municipal property tax), education, and commute.
- **Transport** — door-to-door commute time and distance per parent (Google Maps Directions), monthly commute cost based on travel mode (private/electric/work car or public transport), nearest train station.
- **Education** — number of schools by level, average class size, dropout rate, bagrut eligibility, higher-education entry rate, students per teacher.
- **Quality of life** — potential accessibility rank, peripherality rank, socio-economic cluster, average cars per household, age distribution, dominant religion.
- **Taxes** — family-income tax ceiling and the tax benefit (annual / monthly / percent) granted in eligible settlements.
- **Safety** — composite crime index and per-1,000 rates for several crime clusters.
- **Summary** — highlights and warnings, plus a data-completeness score.

A static HTML frontend (`frontend/index.html`) provides an RTL Hebrew UI for entering family details and viewing the comparison.

## Architecture

```
app.py                   FastAPI HTTP entrypoint (/compare, /settlements/search)
engine.py                Comparison engine — pulls data from Postgres and assembles the response
commute.py               Google Maps Directions wrapper (commute time/distance)
arnona_calculator.py     Per-city arnona (property tax) computation
arnona_jerusalem.py      Jerusalem-specific arnona zone resolution
schemas.py               Pydantic response models
config.py                Minimal .env loader
crime_statistics_pandas.py / run_crime_statistics_queries.py
                         Crime data utilities
etl/                     One-off ETL scripts that populate Postgres tables
                         from CBS / data.gov.il / municipal sources
data/                    Static input files (Excel/CSV) used by the ETL scripts
frontend/index.html      Single-page UI (Tailwind CDN, RTL Hebrew)
test_*.py                Unit tests (unittest)
```

The engine reads from a PostgreSQL database (`family_project`) with one table per data domain: settlements, education, periphery, social_economic, transport, age_and_religion, households, arnona_*, etc. Each `etl/etl_*.py` script is responsible for loading one table.

## Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (local or remote)
- A Google Maps Platform API key with the **Directions API** enabled

### Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Environment variables

Copy `.env.example` to `.env` and fill in the values:

```
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
PGHOST=localhost
PGPORT=5432
PGDATABASE=family_project
PGUSER=postgres
PGPASSWORD=your_password
```

`.env` is gitignored — never commit it.

### Database

Create an empty database and run the ETL scripts to populate it:

```bash
createdb family_project

# Run from the etl/ folder; each script is independent
cd etl
python etl_settlements.py
python etl_education.py
python etl_periphery.py
python etl_social_economic.py
python etl_age_and_religion.py
python etl_households.py
python etl_transport.py
python etl_general_info.py
python etl_neighborhoods.py
python etl_arnona_jerusalem.py
python etl_arnona_rishon_lezion.py
```

Some ETL scripts pull live data from data.gov.il / CBS APIs; others read the Excel/CSV files in `data/`.

## Run

Start the API:

```bash
uvicorn app:app --reload
```

- API docs: <http://localhost:8000/docs>
- Frontend: open `frontend/index.html` in a browser (it calls the local API).

## API

### `POST /compare`

Compare a list of cities for a given family.

```json
{
  "cities": ["Jerusalem", "Tel Aviv"],
  "family": {
    "parent1_income": 18000,
    "parent2_income": 14000,
    "desired_rooms": 4,
    "children": [{ "age": 7 }, { "age": 3 }]
  },
  "parent1": {
    "work_address": "Rothschild 1, Tel Aviv",
    "commute_mode": "public_transport",
    "departure_time": "08:00",
    "work_days_per_week": 5
  },
  "parent2": {
    "work_address": "Hebrew University, Jerusalem",
    "commute_mode": "private_car",
    "departure_time": "07:30",
    "work_days_per_week": 4
  },
  "departure_date": "2026-06-01"
}
```

`commute_mode` is one of: `private_car`, `electric_car`, `work_car`, `public_transport`.

### `GET /settlements/search?q=<query>&limit=<n>`

Autocomplete for Israeli settlement names (Hebrew or English).

## Tests

```bash
python -m unittest discover -p "test_*.py"
```

## Data sources

- Israel Central Bureau of Statistics (CBS) — settlements, education, transport, demographics
- data.gov.il — periphery & socio-economic indices
- Municipal websites — arnona rate tables (Jerusalem, Rishon LeZion)
- Israel Police — crime statistics
- Google Maps Directions API — commute times
