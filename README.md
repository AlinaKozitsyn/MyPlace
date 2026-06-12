# Family Project — City Comparison Tool

A tool for Israeli families to compare cities and settlements across housing costs, commute times, education quality, safety, tax benefits, and quality of life.

## What it does

Given a list of cities and a family profile (incomes, children, desired apartment size, work addresses), the API returns a side-by-side comparison including:

- **Rent estimates** — sourced from Nadlan 2025 data and district-level averages
- **Commute costs** — calculated via Google Maps Distance Matrix (car, electric car, company car, public transport)
- **Education** — schools, class sizes, bagrut eligibility rates, dropout rates
- **Quality of life** — peripherality rank, accessibility rank, socio-economic cluster (CBS 2021)
- **Safety** — crime statistics by severity cluster, normalized per 1,000 residents
- **Tax benefits** — income tax reductions available in development towns (mas hafchata 2026)
- **Demographics** — age distribution, religion breakdown, median age

## Tech stack

- **Backend**: Python, FastAPI, PostgreSQL (psycopg2)
- **Frontend**: Single-page HTML with Tailwind CSS and Hebrew RTL layout
- **ETL**: Python scripts under `etl/` that load CBS and government data into Postgres
- **Commute**: Google Maps Distance Matrix API

## Setup

### Prerequisites

- Python 3.12+
- PostgreSQL running locally (default: `localhost:5432`, database `family_project`)
- Google Maps API key (optional — commute data is skipped without it)

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

Create a `.env` file in the project root:

```
PGHOST=localhost
PGPORT=5432
PGDATABASE=family_project
PGUSER=postgres
PGPASSWORD=your_password
GOOGLE_MAPS_API_KEY=your_key
```

### Load data

Run the ETL scripts to populate the database:

```bash
python etl/etl_settlements.py
python etl/etl_general_info.py
python etl/etl_households.py
python etl/etl_education.py
python etl/etl_periphery.py
python etl/etl_social_economic.py
python etl/etl_age_and_religion.py
python etl/etl_transport.py
python etl/etl_arnona_jerusalem.py
```

### Run the API

```bash
uvicorn app:main --reload
```

API docs available at `http://localhost:8000/docs`.

Open `frontend/index.html` directly in a browser to use the UI.

## API

### `GET /settlements/search?q=<query>&limit=15`

Returns matching settlements for autocomplete. Supports fuzzy Hebrew name matching.

### `POST /compare`

Compare one or more cities for a given family profile.

```json
{
  "cities": ["תל אביב", "ירושלים"],
  "family": {
    "parent1_income": 15000,
    "parent2_income": 12000,
    "desired_rooms": 4,
    "children": [{"age": 5}, {"age": 9}]
  },
  "parent1": {
    "work_address": "Azrieli, Tel Aviv",
    "commute_mode": "private_car",
    "work_days_per_week": 5
  },
  "parent2": {
    "work_address": "Hadassah Ein Kerem, Jerusalem",
    "commute_mode": "public_transport",
    "work_days_per_week": 4
  }
}
```

Commute modes: `private_car`, `electric_car`, `work_car`, `public_transport`.

## Project structure

```
app.py              FastAPI entry point and request models
engine.py           Core comparison logic and data access layer
commute.py          Google Maps Distance Matrix integration
schemas.py          Pydantic output schemas
config.py           .env file loader
arnona_calculator.py  Jerusalem arnona (municipal tax) calculator
etl/                ETL scripts for all data sources
data/               Raw data files (CSV, XLSX)
frontend/           HTML UI
```

## Data sources

- Central Bureau of Statistics (CBS) — population, education, households, age, socio-economic index
- Israel Police — crime statistics by settlement
- Ministry of Interior — peripherality and accessibility rankings
- Nadlan / district rental data — 2025 rent prices
- Ministry of Finance — income tax benefit rates for 2026 (mas hafchata)
