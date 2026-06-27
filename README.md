# CKD Market Opportunity Analysis — NHS CVDPrevent

This project was completed for a pharmaceutical-company interview and reached the final round. It is published here to demonstrate data-analysis and ETL skills.

This project uses the [NHS CVDPrevent API](https://api.cvdprevent.nhs.uk) to identify Integrated Care Board (ICB) level opportunities for improving Chronic Kidney Disease (CKD) diagnosis and treatment in England.

---

## What This Project Does

The notebook provides a case study of the Chronic Kidney Disease (CKD) market and implements an ETL pipeline that extracts data from the NHS CVDPrevent API.

The analysis shows trends across ICBs, tracks testing rates, identifies ICBs with the largest uncoded backlog, and segments the market to inform targeted strategies.

---

## Project Structure

```
.
├── case_study_updated.ipynb   # Main analysis notebook (ETL + all questions)
├── requirements.txt           # Python dependencies
└── src/
    ├── __init__.py            # Public package interface
    ├── api_client.py          # HTTP client wrapping the CVDPrevent REST API
    └── data_builder.py        # Data validation and cleaning logic
```

---

## ETL Pipeline

The pipeline follows a standard Extract → Clean → Transform pattern, implemented across `src/` and the notebook.

### 1. Extract (`src/api_client.py`)

`CVDPreventClient` wraps the CVDPrevent REST API with:

- **Retry logic** — automatic retry on transient errors (429, 5xx) with exponential backoff via `urllib3.Retry`.
- **Error handling** — raises `CVDPApiError` on network failures, non-200 responses, and API-level error payloads.
- **Two API endpoints used:**
  - `GET /area?timePeriodID=&systemLevelID=7` — retrieves all 42 ICBs for the selected time period.
  - `GET /indicator?timePeriodID=&systemLevelID=7&areaID=` — retrieves all indicator data for one ICB. An optional `tagID=9` filter is used in the Bonus A time-series loop to reduce payload size to CKD indicators only.

**Indicators fetched:**

| Code | Description |
|---|---|
| `CVDP001CKD` | Patients with GP-recorded CKD (G3a–G5) — *diagnosed* |
| `CVDP002CKD` | Patients with two eGFR readings < 60 ml/min/1.73m² but no CKD code — *uncoded gap* |
| `CVDP004CKD` | Diagnosed CKD patients with a uACR test in the preceding 12 months — *monitoring quality* |
| `CVDP006CKD` | Patients eligible for eGFR testing who received one — *testing coverage* |

The fetch is filtered to the `"Persons"` / `"Sex"` category (ICB-level un-stratified totals) for the main analysis; all category rows are retained for the demographics bonus section.

### 2. Clean (`src/data_builder.py`)

`clean_raw_records()` converts the raw list of API dicts into a validated long-format DataFrame. Steps applied in order:

1. Strip whitespace from string identifier fields (`area_name`, `indicator_code`, `time_period_name`).
2. Drop rows with missing or empty identity fields (`area_name`, `time_period_id`, `indicator_code`).
3. Drop rows with null `numerator` or `denominator`.
4. Deduplicate on `(area_id, time_period_id, indicator_code, category columns)` — keeping the first occurrence.
5. Coerce `numerator`, `denominator`, and `value` to numeric; drop rows that fail coercion.
6. Cast `numerator` and `denominator` to `int` (counts are always whole numbers).
7. Drop rows where `denominator == 0` (no base population).
8. Drop rows where `numerator > denominator` (data integrity violation).

All dropped rows are logged as warnings so they are visible when `logging.INFO` is enabled.

### 3. Transform (notebook)

After cleaning, the notebook pivots the long-format DataFrame into a wide analytical table — one row per ICB — and derives business columns:

```
N total Population                    ← denominator of CVDP001CKD
N patients eligible for CKD diagnosis ← CVDP001CKD_num + CVDP002CKD_num (diagnosed + uncoded)
N patients eligible but uncoded        ← CVDP002CKD_num
N patients eligible for eGFR tests    ← CVDP006CKD_den
N patients tested for eGFR            ← CVDP006CKD_num
N patients eligible for uACR tests    ← CVDP004CKD_den
N patients tested for uACR            ← CVDP004CKD_num
```

A set of sanity checks validates that no derived column exceeds its logical ceiling (e.g. uncoded ≤ eligible for CKD, tested ≤ eligible) before any analysis begins.

---

## Setup

### Prerequisites

- Python 3.9+
- Internet access to the CVDPrevent API (`api.cvdprevent.nhs.uk`)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run the Notebook

```bash
jupyter lab case_study_updated.ipynb
```

Or open directly in VS Code with the Jupyter extension.

---

## Data Source

All data is sourced from the **NHS CVDPrevent API** — a publicly accessible service that publishes cardiovascular and CKD prevention indicators at ICB level for England.

- API base URL: `https://api.cvdprevent.nhs.uk`
- No authentication is required.
- Default time period used: `timePeriodID=31`
- Geographic granularity: ICB (`systemLevelID=7`) — 42 ICBs across England

---

## Key Analytical Design Decisions

- **Market opportunity** is defined as *diagnosed + uncoded* patients, not uncoded alone. Both groups are addressable for treatment.
- **Quadrant segmentation** (Q2) uses national medians as thresholds — data-driven, no arbitrary cutoffs.
- **uACR rate is excluded from clustering** (Bonus B). `CVDP004CKD` measures monitoring quality for already-diagnosed patients, not the ability to find new patients.
- **k=3 selected for K-Means** (Bonus B). Silhouette scores are flat across k=2–7 (range 0.291–0.308); k=3 was chosen for actionability — it maps to a clean High / Mid / Low gap playbook for a field team.
- **eGFR-led case-finding** (Q3). Uncoded patients already have eGFR evidence; the bottleneck is GPs not translating that evidence into a CKD code, making eGFR recall the primary intervention lever.
