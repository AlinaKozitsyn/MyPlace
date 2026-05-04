from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from engine import DataRepo, compare_cities
from schemas import CompareResponseOut

app = FastAPI(title="Family project API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
repo = DataRepo()


@app.get("/")
def root():
    return {"message": "Family project API is running. Go to /docs"}


class ChildModel(BaseModel):
    age: int = Field(ge=0, le=30)


class FamilyModel(BaseModel):
    parent1_income: float | None = Field(default=None, ge=0)
    parent2_income: float | None = Field(default=None, ge=0)
    desired_rooms: int | None = Field(default=None, ge=1, le=10)
    children: List[ChildModel] = Field(default_factory=list)


class ParentCommuteModel(BaseModel):
    work_address: str = Field(min_length=3)

    commute_mode: str = Field(
        pattern="^(private_car|electric_car|work_car|public_transport)$"
    )

    departure_time: Optional[str] = None

    work_days_per_week: int = Field(
        ge=1,
        le=7,
        description="How many physical work days per week"
    )


class CompareRequest(BaseModel):
    cities: List[str] = Field(min_length=1)
    family: FamilyModel
    parent1: ParentCommuteModel
    parent2: ParentCommuteModel | None = None
    departure_date: str | None = None


@app.get("/settlements/search")
def search_settlements(q: str = "", limit: int = 15):
    """Return settlements matching the query for autocomplete."""
    return repo.search_settlements(q, min(limit, 50))


@app.post("/compare", response_model=CompareResponseOut)
def compare(req: CompareRequest):
    try:
        return compare_cities(
            cities=req.cities,
            family=req.family.model_dump(),
            parent1=req.parent1.model_dump(),
            parent2=req.parent2.model_dump() if req.parent2 else None,
            repo=repo,
            departure_date=req.departure_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
