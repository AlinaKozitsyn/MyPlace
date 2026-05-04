from typing import List, Optional
from pydantic import BaseModel, Field

class MetaOut(BaseModel):
    comparison_type: str
    generated_at: str
    currency: str = "ILS"

class InputFamilySummary(BaseModel):
    parent1_income: Optional[float] = None
    parent2_income: Optional[float] = None
    desired_rooms: Optional[int] = None
    children_count: int = 0

class InputSummaryOut(BaseModel):
    cities: List[str]
    family: InputFamilySummary

class CostsOut(BaseModel):
    rent_monthly: Optional[float] = None
    arnona_monthly: Optional[float] = None
    education_monthly: Optional[float] = None
    commute_monthly: Optional[float] = None
    total_monthly: Optional[float] = None

class WorkCommuteOut(BaseModel):
    duration_min: Optional[int] = None
    distance_km: Optional[float] = None
    mode: Optional[str] = None
    monthly_cost: Optional[float] = None
    status: str = "missing"

class TransportOut(BaseModel):
    parent1_work_commute: WorkCommuteOut
    parent2_work_commute: Optional[WorkCommuteOut] = None
    nearest_train_station: Optional[str] = None
    govmap_available: bool = False

class EducationOut(BaseModel):
    schools_total: Optional[float] = None
    schools_elementary: Optional[float] = None
    schools_middle_schools: Optional[float] = None
    schools_high_schools: Optional[float] = None
    avg_students_per_class_elementary: Optional[float] = None
    avg_students_per_class_secondary: Optional[float] = None
    avg_students_per_class_middle_schools: Optional[float] = None
    avg_students_per_class_high_schools: Optional[float] = None
    dropout_rate_total: Optional[float] = None
    bagrut_eligibility_rate: Optional[float] = None
    higher_education_entry_rate_8_years: Optional[float] = None
    avg_students_per_teacher: Optional[float] = None


class RankDisplayOut(BaseModel):
    value: Optional[float] = None
    out_of: Optional[int] = None
    display_place: Optional[int] = None
    percentile: Optional[float] = None
    summary: Optional[str] = None


class QualityOfLifeOut(BaseModel):
    potential_accessibility_rank: Optional[RankDisplayOut] = None
    peripherality_rank_2020: Optional[RankDisplayOut] = None
    social_economic_cluster_2021: Optional[RankDisplayOut] = None
    average_cars_per_household: Optional[float] = None
    religion: Optional[str] = None
    age0_19_pcnt: Optional[float] = None
    age20_64_pcnt: Optional[float] = None
    age65_pcnt: Optional[float] = None
    age_median: Optional[float] = None


class TaxesOut(BaseModel):
    total_family_income_monthly: Optional[float] = None
    tax_ceiling_annual: Optional[float] = None
    tax_benefit_annual: Optional[float] = None
    tax_benefit_monthly: Optional[float] = None
    tax_benefit_percent: Optional[float] = None


class SafetyOut(BaseModel):
    crime_index: Optional[float] = None
    cluster_1_per_1000: Optional[float] = None
    cluster_2_per_1000: Optional[float] = None
    cluster_3_per_1000: Optional[float] = None


class SummaryOut(BaseModel):
    highlights: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DataCompletenessOut(BaseModel):
    ready_fields: int = 0
    missing_fields: int = 0
    completion_percent: float = 0
    missing_categories: List[str] = Field(default_factory=list)

class CityCompareResultOut(BaseModel):
    city: str
    settlement_id: Optional[int] = None
    district_code: Optional[int] = None
    desired_rooms: Optional[int] = None
    rent_source: Optional[str] = None
    costs: CostsOut
    transport: TransportOut
    education: EducationOut
    quality_of_life: QualityOfLifeOut
    taxes: TaxesOut
    safety: SafetyOut
    summary: SummaryOut
    data_completeness: DataCompletenessOut

class CompareResponseOut(BaseModel):
    meta: MetaOut
    input_summary: InputSummaryOut
    results: List[CityCompareResultOut]
