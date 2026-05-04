import pandas as pd

INPUT_FILE = "../data/neighborhoods.xlsx"
OUTPUT_FILE = "../data/neighborhoods.xlsx"

CITY_COL = "שם יישוב"
FULL_AS_COL = 'סמל א"ס מלא'
SETTLEMENT_CODE_COL = "סמל יישוב"
AS_COL = 'א"ס'
STREETS_COL = "רחובות עיקריים"
NEIGHBORHOODS_COL = "שכונה"

def split_and_clean(cell):
    if pd.isna(cell):
        return []
    text = str(cell).strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split(",")]
    parts = [part for part in parts if part]
    return parts


def main():
    df = pd.read_excel(INPUT_FILE)

    required_cols = [
        CITY_COL,
        FULL_AS_COL,
        SETTLEMENT_CODE_COL,
        AS_COL,
        STREETS_COL,
        NEIGHBORHOODS_COL,
    ]

    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"חסרות עמודות בקובץ: {missing_cols}")

    df[NEIGHBORHOODS_COL] = df[NEIGHBORHOODS_COL].apply(split_and_clean)
    df[STREETS_COL] = df[STREETS_COL].apply(split_and_clean)

    # Preserve empty rows so explode does not drop them
    df[NEIGHBORHOODS_COL] = df[NEIGHBORHOODS_COL].apply(lambda x: x if x else [None])
    df[STREETS_COL] = df[STREETS_COL].apply(lambda x: x if x else [None])

    result = df.explode(NEIGHBORHOODS_COL, ignore_index=True)
    result = result.explode(STREETS_COL, ignore_index=True)

    result[NEIGHBORHOODS_COL] = result[NEIGHBORHOODS_COL].apply(
        lambda x: x.strip() if isinstance(x, str) else x
    )
    result[STREETS_COL] = result[STREETS_COL].apply(
        lambda x: x.strip() if isinstance(x, str) else x
    )

    result = result.rename(columns={
        NEIGHBORHOODS_COL: "שכונה",
        STREETS_COL: "רחוב"
    })

    result.to_excel(OUTPUT_FILE, index=False)

    print(f"הקובץ נשמר בהצלחה: {OUTPUT_FILE}")
    print(f"מספר שורות במקור: {len(df)}")
    print(f"מספר שורות אחרי פיצול: {len(result)}")


if __name__ == "__main__":
    main()