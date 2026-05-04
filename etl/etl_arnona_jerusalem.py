from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PDF_PATH = DATA_DIR / "jerusalem_tax_order_2026.pdf"
RAW_CSV_PATH = DATA_DIR / "arnona_jerusalem_neighborhoods_raw.csv"
FINAL_CSV_PATH = DATA_DIR / "arnona_jerusalem_neighborhoods_final.csv"
FINAL_JSON_PATH = DATA_DIR / "arnona_jerusalem_neighborhoods_final.json"

CITY = "ירושלים"
SOURCE_YEAR = 2026
SOURCE_DOCUMENT = "Jerusalem tax order 2026"
BUILDING_TYPE = 2

RESIDENTIAL_ZONE_RATES = {
    "א": 107.65,
    "ב": 86.34,
    "ג": 64.23,
}

ZONE_PAGE_RANGES = {
    "א": range(16, 29),  # pages 17-29
    "ב": range(29, 39),  # pages 30-39
    "ג": range(39, 45),  # pages 40-45
}

RAW_COLUMNS = [
    "city",
    "neighborhood_or_street",
    "arnona_zone",
    "source_page",
    "raw_text",
    "notes",
]

FINAL_COLUMNS = [
    "city",
    "neighborhood",
    "normalized_neighborhood",
    "arnona_zone",
    "building_type",
    "price_per_sqm_yearly",
    "source_year",
    "source_document",
    "conflict_resolved",
    "all_zones_found",
    "notes",
]

HEBREW_LETTER_RE = re.compile(r"[\u05d0-\u05ea]")
GUSH_RE = re.compile(r"^\s*[\d/][\d\s()/'-]*$")
GENERIC_NEIGHBORHOOD_STOPWORDS = {
    "בית",
    "גן",
    "ז",
    "יד",
    "כפר",
    "קרית",
    "שם",
}
SINGLETON_PREFIX_ALLOWLIST = (
    "אבו",
    "אדמת",
    "ארמון",
    "בית",
    "באב",
    "גאולה",
    "גבעת",
    "גילה",
    "גונן",
    "הר",
    "ואדי",
    "טלביה",
    "ימין",
    "יפה",
    "יפתא",
    "ליפתא",
    "מאה",
    "ממילא",
    "מרכז",
    "מחנה",
    "מקור",
    "מנחת",
    "מורשה",
    "מושבה",
    "נווה",
    "נוה",
    "נחלת",
    "סילוואן",
    "סן",
    "עטרות",
    "עיר",
    "עין",
    "פסגת",
    "קטמון",
    "קרית",
    "קריית",
    "רמת",
    "רמות",
    "רחביה",
    "רוממה",
    "רסקו",
    "שייח",
    "שיך",
    "שנלר",
    "שועפאט",
    "תלפיות",
)


def normalize_spaces(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u05be", "-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"([(])\s+", r"\1", text)
    text = re.sub(r"\s*-\s*", "-", text)
    text = text.replace("שכ '", "שכ'").replace("רח '", "רח'")
    text = text.replace("שד '", "שד'").replace('ר"ח', "רח'")
    return text.strip(" ,;")


def normalize_neighborhood(text: str) -> str:
    value = normalize_spaces(text)
    value = re.sub(r"^[^א-ת]+", "", value)
    value = re.sub(r"^(שכונת|שכוני|שיכון|שכון|שכ')\s*", "", value)
    value = re.sub(r"^(ע\"י|ע'י|ע״י|ליד|מול|מאחורי|בהמשך ל|בין)\s+", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"(?<=\D)\d+$", "", value)
    value = re.sub(r"\s+[א-ת]'?$", "", value)
    value = value.replace('"', "").replace("'", "")
    value = value.replace("-", " ")
    value = re.sub(r"\s+[א-ת]$", "", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"[^א-ת\s]+$", "", value)
    value = re.sub(r"\s+[א-ת]$", "", value)
    return value.strip(" ,")


def fuzzy_neighborhood_key(text: str) -> str:
    value = normalize_neighborhood(text)
    value = value.replace(" ", "")
    value = value.replace("יי", "י")
    return value


def sort_hebrew_tokens(words: list[tuple[float, str]]) -> str:
    ordered = [text for _, text in sorted(words, key=lambda item: item[0], reverse=True)]
    return normalize_spaces(" ".join(token for token in ordered if token.strip()))


def get_zone_for_page(page_index: int) -> str | None:
    for zone, page_range in ZONE_PAGE_RANGES.items():
        if page_index in page_range:
            return zone
    return None


def iter_page_lines(page: fitz.Page) -> list[dict]:
    grouped: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        key = int(round(y0))
        grouped[key].append((x0, x1, text))

    lines: list[dict] = []
    for key in sorted(grouped):
        if key < 110 or key > 760:
            continue
        words = grouped[key]
        desc_words = [(x0, text) for x0, x1, text in words if x1 < 280]
        plot_words = [(x0, text) for x0, x1, text in words if 280 <= x1 < 450]
        gush_words = [(x0, text) for x0, x1, text in words if x0 >= 450]

        line = {
            "y": key,
            "desc": sort_hebrew_tokens(desc_words),
            "plots": sort_hebrew_tokens(plot_words),
            "gush": sort_hebrew_tokens(gush_words),
        }

        if any(line.values()):
            lines.append(line)

    return lines


def extract_raw_rows(pdf_path: Path) -> list[dict]:
    pdf = fitz.open(stream=pdf_path.read_bytes(), filetype="pdf")
    raw_rows: list[dict] = []

    for page_index in range(pdf.page_count):
        zone = get_zone_for_page(page_index)
        if not zone:
            continue

        page = pdf.load_page(page_index)
        current: dict | None = None

        for line in iter_page_lines(page):
            gush = line["gush"]
            desc = line["desc"]
            plots = line["plots"]

            if not any([gush, desc, plots]):
                continue

            if GUSH_RE.match(gush):
                if current and current["neighborhood_or_street"]:
                    raw_rows.append(current)
                current = {
                    "city": CITY,
                    "neighborhood_or_street": desc,
                    "arnona_zone": zone,
                    "source_page": page_index + 1,
                    "raw_text": normalize_spaces(
                        f"גוש {gush} | חלקות {plots} | {desc}"
                    ),
                    "notes": "",
                }
                continue

            if current is None:
                continue

            if desc:
                current["neighborhood_or_street"] = normalize_spaces(
                    f"{current['neighborhood_or_street']} {desc}"
                )
            if plots:
                current["raw_text"] = normalize_spaces(
                    f"{current['raw_text']} {plots}"
                )

        if current and current["neighborhood_or_street"]:
            raw_rows.append(current)

    return raw_rows


def split_candidate_parts(descriptor: str) -> list[str]:
    text = normalize_spaces(descriptor)
    text = re.sub(r"\([^)]*\)", "", text)
    return [part.strip() for part in text.split(",") if part.strip()]


def expand_combined_parts(part: str) -> list[str]:
    if " ו" not in part or part.startswith(("רח'", "רחוב", "דרך", "כביש", "שד", "שדרות")):
        return [part]

    pieces = [piece.strip() for piece in re.split(r"\s+ו(?=[\u05d0-\u05ea])", part) if piece.strip()]
    return pieces or [part]


def extract_neighborhood_candidates(descriptor: str) -> list[tuple[str, bool]]:
    candidates: list[tuple[str, bool]] = []
    street_context = False

    for part in split_candidate_parts(descriptor):
        explicit_neighborhood = part.startswith(("שכ'", "שכונת", "שכוני", "שיכון", "שכון"))
        street_part = part.startswith(("רח'", "רחוב", "דרך", "כביש", "שד", "שדרות"))

        if street_part:
            street_context = True
            continue

        if explicit_neighborhood:
            street_context = False

        if street_context and not explicit_neighborhood:
            continue

        for piece in expand_combined_parts(part):
            value = normalize_spaces(piece)
            if not HEBREW_LETTER_RE.search(value):
                continue
            if value.startswith(("כל ", "פרט ", "חלקה ", "חלקות ")):
                continue
            normalized = normalize_neighborhood(value)
            if normalized:
                candidates.append((normalized, explicit_neighborhood))

    unique_candidates: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for candidate, explicit in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique_candidates.append((candidate, explicit))
    return unique_candidates


def is_plausible_neighborhood(candidate: str, is_explicit: bool, candidate_count: int) -> bool:
    if candidate in GENERIC_NEIGHBORHOOD_STOPWORDS:
        return False
    if "/" in candidate:
        return False
    if "(" in candidate or ")" in candidate:
        return False
    if "שכ" in candidate:
        return False
    if "רח " in candidate or " רח" in candidate:
        return False
    if "אזור תעשיה" in candidate or "איזור תעשיה" in candidate or "בניה חדשה" in candidate:
        return False
    if candidate.startswith(("ע י ", "עי ")):
        return False
    if is_explicit:
        return True
    if candidate_count >= 2:
        return True
    return candidate.startswith(SINGLETON_PREFIX_ALLOWLIST)


def aggregate_rows(raw_rows: list[dict]) -> tuple[list[dict], list[dict], dict[str, set[str]]]:
    aggregated: dict[str, dict] = {}
    multiple_zone_map: dict[str, set[str]] = defaultdict(set)
    missing_zone_rows: list[dict] = []
    candidate_counts: dict[str, int] = defaultdict(int)
    explicit_candidates: set[str] = set()

    extracted_candidates_per_row: list[tuple[dict, list[tuple[str, bool]]]] = []
    for row in raw_rows:
        extracted = extract_neighborhood_candidates(row["neighborhood_or_street"])
        extracted_candidates_per_row.append((row, extracted))
        for candidate, is_explicit in extracted:
            candidate_counts[candidate] += 1
            if is_explicit:
                explicit_candidates.add(candidate)

    for row, extracted_candidates in extracted_candidates_per_row:
        zone = row["arnona_zone"]
        price = RESIDENTIAL_ZONE_RATES.get(zone)
        if not zone or price is None:
            missing_zone_rows.append(row)
            continue

        candidates = [
            candidate
            for candidate, _ in extracted_candidates
            if is_plausible_neighborhood(
                candidate,
                candidate in explicit_candidates,
                candidate_counts[candidate],
            )
        ]
        if not candidates:
            continue

        for candidate in candidates:
            key = fuzzy_neighborhood_key(candidate)
            existing = aggregated.get(key)
            if existing is None:
                aggregated[key] = {
                    "city": CITY,
                    "neighborhood": candidate,
                    "normalized_neighborhood": candidate,
                    "arnona_zone": zone,
                    "building_type": BUILDING_TYPE,
                    "price_per_sqm_yearly": price,
                    "source_year": SOURCE_YEAR,
                    "source_document": SOURCE_DOCUMENT,
                    "conflict_resolved": "false",
                    "all_zones_found": {zone},
                    "notes": "standard residential building type",
                }
            else:
                existing["all_zones_found"].add(zone)
                if len(candidate) < len(existing["neighborhood"]) or " " in candidate and " " not in existing["neighborhood"]:
                    existing["neighborhood"] = candidate
                    existing["normalized_neighborhood"] = candidate
                if price > existing["price_per_sqm_yearly"]:
                    existing["arnona_zone"] = zone
                    existing["price_per_sqm_yearly"] = price
                if len(existing["all_zones_found"]) > 1:
                    existing["conflict_resolved"] = "true"
                    multiple_zone_map[existing["normalized_neighborhood"]] = set(existing["all_zones_found"])

    final_rows: list[dict] = []
    zone_order = {"א": 0, "ב": 1, "ג": 2, "ד": 3}
    for neighborhood_key in sorted(aggregated):
        record = aggregated[neighborhood_key]
        zones = sorted(record["all_zones_found"], key=lambda value: zone_order.get(value, 99))
        record["all_zones_found"] = ";".join(zones)
        if record["conflict_resolved"] == "true":
            record["notes"] = "appeared in multiple zones; highest price selected"
        final_rows.append(record)

    return final_rows, missing_zone_rows, multiple_zone_map


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def extract_residential_zone_rates(pdf_path: Path) -> dict[str, float]:
    pdf = fitz.open(stream=pdf_path.read_bytes(), filetype="pdf")
    page_text = pdf.load_page(1).get_text()
    for expected in ("107.65", "86.34", "64.23"):
        if expected not in page_text:
            raise ValueError(f"Missing expected residential rate {expected} on source page 2.")
    return RESIDENTIAL_ZONE_RATES.copy()


def build_outputs() -> tuple[list[dict], list[dict], list[dict], dict[str, set[str]]]:
    if not PDF_PATH.exists():
        raise FileNotFoundError(f"Source PDF not found: {PDF_PATH}")

    extract_residential_zone_rates(PDF_PATH)
    raw_rows = extract_raw_rows(PDF_PATH)
    final_rows, missing_zone_rows, multiple_zone_map = aggregate_rows(raw_rows)

    write_csv(RAW_CSV_PATH, RAW_COLUMNS, raw_rows)
    write_csv(FINAL_CSV_PATH, FINAL_COLUMNS, final_rows)
    write_json(FINAL_JSON_PATH, final_rows)

    return raw_rows, final_rows, missing_zone_rows, multiple_zone_map


def print_validation(
    raw_rows: list[dict],
    final_rows: list[dict],
    missing_zone_rows: list[dict],
    multiple_zone_map: dict[str, set[str]],
) -> None:
    print(f"Raw extracted rows: {len(raw_rows)}")
    print(f"Final unique neighborhoods: {len(final_rows)}")

    print("Neighborhoods that appeared in multiple zones:")
    if multiple_zone_map:
        for neighborhood in sorted(multiple_zone_map):
            zones = ";".join(sorted(multiple_zone_map[neighborhood]))
            print(f"  - {neighborhood}: {zones}")
    else:
        print("  - none")

    print("Rows with missing/unclear zone:")
    if missing_zone_rows:
        for row in missing_zone_rows[:20]:
            print(
                f"  - page {row['source_page']}: "
                f"{row['neighborhood_or_street']} | zone={row['arnona_zone']}"
            )
    else:
        print("  - none")

    print("Sample final output:")
    for row in final_rows[:10]:
        print(json.dumps(row, ensure_ascii=False))


def main() -> None:
    raw_rows, final_rows, missing_zone_rows, multiple_zone_map = build_outputs()
    print_validation(raw_rows, final_rows, missing_zone_rows, multiple_zone_map)


if __name__ == "__main__":
    main()
