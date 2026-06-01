# BMW Maintenance Helper -- Project Plan

## Core Concept

A tool for any BMW owner to:

1. **Browse the BMW parts catalog** (RealOEM-style: navigate by system -> category -> diagram -> individual parts)
2. **Select parts** they need for any maintenance job -- the tool is not limited to a fixed list of jobs
3. **Auto-enrich each selected part** with:
   - OEM part number, description, price (from RealOEM)
   - Required quantity from the diagram
   - RockAuto alternatives with OEM interchange numbers and current pricing
4. **Group selected parts into named jobs** (e.g. "Oil system seals", "Cooling system overhaul") with labour notes
5. **Generate a professional quote-request email** to mechanic shops, fully populated with part numbers, quantities, brand preferences, and notes
6. **Import and parse estimate PDFs** received back from shops, extract line items, and compare multiple estimates side-by-side

Vehicle identity (VIN, year, model, engine, etc.) lives in a YAML config so the tool works for any BMW -- just swap the config.

---

## User Journey

```
1. bmw-helper catalog browse
   \- Select: Engine -> Lubrication System -> Oil Filter Housing
      \- View diagram with parts list
         |- Part 1: 11428637821  Oil filter housing gasket (upper) -- OEM $28 / RockAuto Elring $18
         |- Part 2: 11428637820  Oil filter housing gasket (lower) -- OEM $24 / RockAuto Elring $15
         \- Part 3: 17222245358  Oil cooler O-ring x2 -- OEM $8 / RockAuto CRP $3

   User selects parts -> added to active "service plan"

2. bmw-helper catalog browse
   \- Select: Engine -> Valve Train -> Valve Cover
      \- User selects valve cover gasket, spark plug tube seals -> added to plan

   [... repeat for any other systems ...]

3. bmw-helper plan show
   \- View all selected parts, grouped by system, with OEM + RockAuto prices

4. bmw-helper plan group
   \- Assign parts to named jobs (e.g. "Oil Filter Housing Gasket", "Valve Cover Gasket")
   \- Add job notes (overlapping labour, customer-supplied, no-warranty, etc.)

5. bmw-helper email generate
   \- Renders professional quote-request email from plan

6. bmw-helper estimate import Estimate_1885.pdf
   \- Parses PDF -> structured JSON stored in estimates/

7. bmw-helper estimate compare estimate_1885 estimate_1902
   \- Side-by-side labour + parts comparison table
```

---

## Tech Stack

### Backend
| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.12+ | rockauto-api is Python; best PDF/scraping ecosystem |
| API server | FastAPI | Async, auto-docs, plays well with asyncio-based rockauto-api |
| CLI (non-visual ops) | [Typer](https://typer.tiangolo.com/) | Estimate import, email generate, server start |
| Config | YAML (`ruamel.yaml`) | Human-editable with comment preservation |
| PDF parsing | `pdfplumber` | Best table + mixed-layout extraction |
| RockAuto | `rockauto-api` (rsp2k/rockauto-api) | Async Pydantic client; vehicle + parts + pricing |
| RealOEM | Custom scraper (`httpx` + `BeautifulSoup4`) | No public API; scrape catalog tree, diagrams, image maps, prices |
| Templates | `Jinja2` | Quote email rendering |
| Storage | JSON files | Simple, no DB; one file per service plan + one per estimate |
| Caching | `diskcache` | Persist RealOEM + RockAuto responses locally |
| Async | `asyncio` + `anyio` | Required by rockauto-api |
| Local LLM | [Ollama](https://ollama.com) + `ollama` Python lib | Runs model locally; no data leaves the machine |
| LLM model | `qwen3:8b` (default) | Newer generation; better reasoning and structured output than qwen2.5 |

### Frontend
| Concern | Choice | Reason |
|---|---|---|
| Framework | Vanilla JS + [Alpine.js](https://alpinejs.dev/) | Lightweight reactive state; no build step needed |
| Styling | [Tailwind CSS](https://tailwindcss.com/) (CDN) | Utility-first; looks good without a design system |
| Diagram interaction | SVG overlay on `<img>` | RealOEM embeds image maps; we re-render as an SVG layer for click/hover |
| Parts table | HTML table with row highlighting | Linked to SVG callouts bidirectionally |
| Served by | FastAPI static files | Single process, no separate Node server |

---

## Directory Structure

```
BMW_Maintenance_Helper/
|-- config/
|   |-- vehicle.yaml              # Vehicle identity (VIN, year, model, engine...)
|   |-- schedule.yaml             # Parsed maintenance schedule (intervals per item)
|   \-- service_history.yaml     # When each item was last performed + at what odometer
|-- plans/
|   \-- 2026_spring_service.json  # Active/saved service plans (part selections + job groupings)
|-- estimates/
|   \-- shopa_1885.json           # Parsed estimates (auto-generated from PDFs)
|-- templates/
|   \-- quote_email.j2            # Jinja2 quote-request email template
|-- frontend/
|   |-- index.html                # Single-page app shell
|   |-- app.js                    # Alpine.js app: catalog browser, plan editor
|   \-- style.css                 # Tailwind overrides / custom styles
|-- bmw_helper/
|   |-- __init__.py
|   |-- cli.py                    # Typer: bmw-helper serve / estimate import / email generate
|   |-- api.py                    # FastAPI app + all REST endpoints
|   |-- config.py                 # Load/validate vehicle.yaml
|   |-- models.py                 # Pydantic models (Vehicle, Part, Job, Plan, Estimate...)
|   |-- realoem/
|   |   |-- client.py             # httpx scraper for RealOEM
|   |   |-- catalog.py            # Category tree + group navigation
|   |   |-- diagram.py            # Diagram image URL + image map hotspot coordinates
|   |   \-- parts.py              # Part detail, pricing, supersession lookup
|   |-- rockauto/
|   |   |-- client.py             # rockauto-api wrapper
|   |   \-- lookup.py             # Alternatives by OEM interchange PN
|   |-- plan.py                   # Service plan: part selection, job grouping, persistence
|   |-- email_generator.py        # Render quote email from Jinja2 template
|   |-- estimate_parser.py        # PDF -> structured Estimate JSON
|   \-- comparator.py             # Multi-estimate comparison
|-- cache/                        # diskcache directory (gitignored)
|-- pyproject.toml
\-- PLAN.md
```

---

## Data Models (`models.py`)

### Vehicle Config

```yaml
# config/vehicle.yaml
owner:
  name: Your Name
  email: your.email@example.com

vehicle:
  vin:          WBAXXXXXXXXXXXXXXXXX
  year:         2007
  make:         BMW
  model:        335i
  body:         E93 Convertible
  engine_code:  N54
  engine_desc:  3.0L Twin-Turbo Inline-6
  transmission: "6-Speed Manual (GS6-53BZ)"
  drive:        RWD
  odometer_km:  80000

preferences:
  currency:        CAD
  tax_name:        GST
  tax_rate:        0.05
  preferred_brands: [Elring, "Victor Reinz", Bosch, INA, Febi, "Genuine BMW"]
  oem_only_systems: ["Water Pump", "Thermostat"]   # flag systems where cheap aftermarket is not acceptable
```

### Part (selected from catalog)

```python
class CatalogPart(BaseModel):
    oem_pn: str                      # BMW OEM part number
    description: str                 # e.g. "Oil filter housing gasket"
    qty_required: int                # quantity needed per the diagram
    realoem_price_cad: float | None  # OEM price from RealOEM
    superseded_by: str | None        # if PN is superseded, the current PN
    diagram_ref: str | None          # e.g. "11_0750 pos. 3"
    catalog_path: list[str]          # e.g. ["Engine", "Lubrication System", "Oil Filter Housing"]

class RockAutoAlternative(BaseModel):
    brand: str
    part_number: str                 # RockAuto / manufacturer PN
    oem_interchange: list[str]       # OEM PNs this replaces
    price_cad: float
    availability: str                # "In Stock", "Ships in 3-5 days", etc.
    url: str
    notes: str | None

class SelectedPart(BaseModel):
    catalog_part: CatalogPart
    rockauto_alternatives: list[RockAutoAlternative]
    preferred_brand: str | None      # user's override for this specific part
    notes: str | None                # e.g. "customer-supplied", "no warranty"
    customer_supplied: bool = False
```

### Service Plan

```python
class Job(BaseModel):
    id: str                          # slug, e.g. "oil_filter_housing_gasket"
    name: str                        # human label
    parts: list[SelectedPart]
    labour_notes: str | None         # e.g. "overlapping work with oil pan removal"
    overlaps_with: list[str]         # other job IDs
    customer_supplied_labour: bool   # shop provides labour only, customer supplies parts
    no_warranty: bool = False
    special_instructions: str | None

class ServicePlan(BaseModel):
    id: str
    name: str                        # e.g. "2026 Spring Service"
    created: datetime
    vehicle_vin: str
    jobs: list[Job]
    ungrouped_parts: list[SelectedPart]  # parts selected but not yet assigned to a job
    notes: str | None
```

### Parsed Estimate

```python
class EstimateLineItem(BaseModel):
    activity: str                    # "Repair", "Parts", "Media Package", etc.
    description: str
    oem_pns: list[str]               # extracted from description text
    brand: str | None
    tax: str | None
    qty: float
    rate: float
    amount: float

class ShopEstimate(BaseModel):
    id: str
    source_file: str
    shop_name: str
    shop_address: str | None
    shop_phone: str | None
    shop_email: str | None
    gst_number: str | None
    estimate_number: str
    date: date
    vehicle_vin: str | None
    line_items: list[EstimateLineItem]
    subtotal: float
    tax_amount: float
    total: float
    status: str                      # "received", "accepted", "declined", "expired"
    valid_days: int | None
    raw_notes: str | None
```

---

## API Endpoints (FastAPI)

The dashboard at `/` is the home screen and shows the maintenance status table. The catalog browser is at `/catalog`.

The browser frontend talks to these; they can also be called directly with curl/httpie.

```
# Maintenance schedule + history
GET  /api/schedule                           -> all schedule items with intervals
GET  /api/schedule/status                    -> each item with status (overdue/due soon/ok/unknown)
GET  /api/history                            -> full service history
GET  /api/history/{item_id}                  -> history for one item
POST /api/history                            -> record a service event {item_id, odometer_km, date, shop, notes}
DELETE /api/history/{event_id}               -> remove a history entry
PATCH /api/vehicle/odometer                  -> update current odometer reading

# Catalog
GET  /api/catalog/tree                       -> full category tree for the vehicle
GET  /api/catalog/group/{group_code}         -> parts list + diagram URL + image map hotspots
GET  /api/catalog/part/{oem_pn}              -> part detail, price, supersession, RockAuto alternatives
GET  /api/catalog/search?q=<query>           -> keyword or PN search

# Service plan
GET  /api/plans                              -> list all plans
POST /api/plans                              -> create new plan {name}
GET  /api/plans/{plan_id}                    -> full plan detail
POST /api/plans/{plan_id}/parts              -> add part {oem_pn, qty, notes}
DELETE /api/plans/{plan_id}/parts/{oem_pn}   -> remove part
POST /api/plans/{plan_id}/jobs               -> create job group {name, notes}
PATCH /api/plans/{plan_id}/jobs/{job_id}     -> update job (assign parts, edit notes/flags)

# Quote email
POST /api/email/generate                     -> {plan_id} -> rendered email text

# Estimates
POST /api/estimates/import                   -> multipart PDF upload -> parsed JSON
GET  /api/estimates                          -> list all estimates
GET  /api/estimates/{id}                     -> full detail
GET  /api/estimates/compare?ids=id1,id2      -> comparison table data

# Proxy (avoids CORS for diagram images)
GET  /api/proxy/diagram?url=<realoem-img-url>
```

## CLI Commands (non-visual operations)

```
bmw-helper serve [--port 8000]              # Start web server + open browser
bmw-helper config show                      # Print vehicle config

bmw-helper schedule import <file.pdf>       # Parse maintenance schedule PDF -> config/schedule.yaml
bmw-helper schedule status                  # Print dashboard table to terminal

bmw-helper history record <item-id> --km <odometer> [--date YYYY-MM-DD] [--shop "name"] [--notes "..."]
bmw-helper history show [<item-id>]         # Show service history for one or all items

bmw-helper estimate import <file.pdf>       # Parse estimate PDF -> JSON
bmw-helper email generate <plan-id>         # Render quote email to stdout or --output file.txt
```

---

## Catalog Browser -- Web UI

The app runs as a local web server (`bmw-helper serve`) and opens in the browser. A single-page app with three panels:

```
+----------------------------------------------------------------------------------+
|  BMW 2007 335i E93  .  N54  .  WBAXXXXXXXXXXXXXXXXX               [View Plan]   |
|-----------------+------------------------------+-------------------------------|
| CATALOG TREE    |  DIAGRAM                      |  PARTS TABLE                  |
|                 |                               |                               |
| [v] Engine        |  [exploded diagram image]     |  No.  Description      Qty   |
|   [v] Lubrication |                               |  -------------------------- |
|     Oil Filter  |   (1)  (2)                       |  (1)  Cylinder head cover  1  |
|     Oil Pan     |       [diagram with           |  (2)  ASA-Bolt M6X32.5   26  |
|     Oil Pump    |        numbered callout        |  (3)  ASA-Bolt M6X38      2  |
|   [v] Valve Train |        bubbles overlaid        |  (4)  C-clip nut M6-ZNS3  4  |
|     Valve Cover |        as SVG hotspots]        |  (5)  Threaded bolt       3  |
|     VANOS       |                               |  (6)  Profile-gasket [x]   1  |
|   [v] Cooling     |   (3)  (6)                       |  (7)  Sleeve              6  |
|     Water Pump  |                               |  (8)  Metal bracket       1  |
|     Thermostat  |  Hover callout -> highlight    |                               |
| [>] Transmission  |  row in table                 |  OEM $29.77                  |
| [>] Electrical    |  Click callout -> select part  |  Elring $18.20 <- RockAuto   |
| [>] Body          |  Click again -> deselect       |                               |
| [>] Suspension    |                               |  [Add selected to plan]       |
\-----------------+------------------------------+-------------------------------+
```

### How diagram interaction works

RealOEM renders diagrams as `<img>` + `<map>` elements -- each numbered callout bubble has an `<area>` tag with `coords` (x, y, radius for circles). The scraper extracts:
- The diagram image URL (served as a proxy through our backend to avoid CORS)
- All `<area>` entries: position number -> `(x, y, r)` coordinates

The frontend renders:
1. The diagram `<img>` at its natural size (or scaled with CSS)
2. An `<svg>` overlay positioned absolutely on top, same dimensions
3. One `<circle>` per callout at the extracted coordinates -- transparent fill, visible on hover/selected
4. Hover on SVG circle -> highlight the corresponding table row (and vice versa)
5. Click SVG circle or table row -> toggle part selected state
6. Selected parts shown with a checkmark; a badge on the callout bubble

### Plan sidebar / modal

Clicking **[View Plan]** opens a slide-over panel showing all selected parts across all diagrams visited, grouped by catalog section, with OEM price + best RockAuto alternative price per line. Parts can be dragged/assigned into named jobs from here.

---

## Maintenance Schedule

### Source

A maintenance schedule PDF (e.g. the N54 community schedule, or BMW's own service guide) is ingested once and stored as structured YAML alongside the vehicle config. The schedule is model/engine-specific, not per-VIN, so it can be shared across vehicles of the same type.

### Parsed Structure (`config/schedule.yaml`)

```yaml
source: "BMW 335i maint km.pdf"
engine: N54
unit: km
version: "1.1b"

items:
  - id: oil_filter
    name: Oil & Filter Change
    action_inspect: ~
    interval_inspect_km: ~
    action_replace: R
    interval_replace_km: 12000
    bmw_recommendation_km: 24000
    notes: "BMW recommends every 24,000; community recommends every 12,000"
    catalog_hint: "Engine > Lubrication System > Oil Filter"   # links to RealOEM category

  - id: brake_fluid
    name: Brake Fluid
    action_inspect: ~
    interval_inspect_km: ~
    action_replace: R
    interval_replace_km: 48000
    bmw_recommendation_km: 24000           # BMW says every 2 years ~ 24,000 km
    notes: "Replace every 48,000 km or every 2.5 years"
    catalog_hint: "Brakes > Brake Fluid"

  - id: engine_air_filter
    name: Engine Air Filter
    action_inspect: I
    interval_inspect_km: 24000
    action_replace: R
    interval_replace_km: 48000
    bmw_recommendation_km: 45000
    catalog_hint: "Engine > Air Supply > Air Filter"

  # ... (all 17 items from the PDF, auto-parsed on import)
```

### Service History (`config/service_history.yaml`)

Tracks when each scheduled item was last performed, so the tool can compute what's due.

```yaml
vehicle_vin: WBAXXXXXXXXXXXXXXXXX

history:
  - item_id: oil_filter
    date: 2024-06-01
    odometer_km: 50000
    performed_by: Self
    parts: ["11427541827 OEM"]
    notes: "Liqui Moly 5W-30"

  - item_id: spark_plugs
    date: 2022-01-15
    odometer_km: 36000
    performed_by: "Local shop"
    parts: ["12120037244 NGK 97506"]
    notes: ~
```

### Maintenance Dashboard (web UI -- home screen)

When the app opens, the first screen is a dashboard showing the status of every scheduled item relative to current odometer:

```
BMW 2007 335i E93  .  80,000 km  .  Last updated: 2025-01-01

ITEM                       LAST DONE    LAST DONE KM   NEXT DUE KM   STATUS        OVERDUE BY
-------------------------------------------------------------------------------------------------
Oil & Filter               2024-06-01   50,000 km      62,000 km     [*] DUE SOON    --         [+]
Brake Fluid                2020-01-01   20,000 km      68,000 km     [!] OVERDUE     12,000 km [+]
Interior Air Filter        unknown      --              --             ? UNKNOWN             [+]
Engine Air Filter (I)      2023-01-01   40,000 km      64,000 km     [ok] OK          --
Spark Plugs                2022-01-15   36,000 km      108,000 km    [ok] OK          --
Clutch Fluid               unknown      --              --             ? UNKNOWN             [+]
Engine Coolant (I)         2023-01-01   40,000 km      64,000 km     [ok] OK          --
...
```

Status colours:
- **Red OVERDUE** -- current odometer past next due km
- **Yellow DUE SOON** -- within 5,000 km of next due
- **Green OK** -- more than 5,000 km remaining
- **Grey UNKNOWN** -- no service history recorded

The `[+]` button on overdue/due items opens a dialog: "Add to active service plan" -> pre-populates the plan with that item and deep-links to the relevant RealOEM catalog category.

### Schedule Import

`bmw-helper schedule import <file.pdf>` parses a maintenance schedule PDF using `pdfplumber` table extraction and writes `config/schedule.yaml`. The N54 community schedule is the primary target format; the parser extracts the km column headers and maps I/R markers to each item row.

---

## Local LLM Integration (Ollama)

### Why

The app has structured data (schedule, history, catalog tree, part descriptions) but the user interacts with it in natural language. A local 8B model bridges that gap without sending any data to a cloud API -- your VIN, service history, and part selections stay on your machine.

### Runtime

[Ollama](https://ollama.com) runs the model locally and exposes an OpenAI-compatible HTTP API at `http://localhost:11434`. The `ollama` Python library wraps it.

**Ollama is a hard requirement.** The app checks at startup whether Ollama is reachable and whether the required model is available. If either check fails, the app exits with a clear message rather than running in a degraded state:

```
[x] Ollama is not running.
  Start it with: ollama serve
  Then pull the model: ollama pull qwen3:8b
```

This is enforced in `bmw_helper/ai.py:AIClient.__init__()` and called from both `bmw-helper serve` and `bmw-helper ai ask`.

Recommended model: **`qwen3:8b`** -- newer generation, better reasoning and structured output than qwen2.5, supports tool/function calling, fast on Apple Silicon. Fallback: `qwen2.5:7b` or `llama3.1:8b`.

```
ollama pull qwen3:8b
```

### Agentic approach -- tool use

Rather than pre-fetching data and passing it to the LLM, the LLM is given a set of **tools** it can call itself. This means it can do multi-step data gathering autonomously before synthesising an answer.

`qwen3:8b` supports Ollama's tool/function-calling API natively. The agent loop:

```
User question
  -> LLM decides which tools to call
  -> App executes tools, returns results
  -> LLM decides if it needs more tools
  -> ... (repeat until LLM has enough data)
  -> LLM returns final answer
```

Example -- *"What will it cost to fix everything overdue, and what's cheapest?"*

```
LLM calls: get_schedule_status()
  -> [brake_fluid: overdue 1,910 days, clutch_fluid: overdue 1,910 days, ...]
LLM calls: get_rockauto_alternatives("brake_fluid")
  -> [Ate SL.6 DOT 4 $18.40, ...]
LLM calls: get_rockauto_alternatives("clutch_fluid")
  -> [Ate SL.6 DOT 4 $18.40 -- same fluid as brakes]
LLM calls: search_catalog("spark plugs N54")
  -> group: Engine > Ignition > Spark Plugs, parts: [12120037244 x6]
LLM calls: get_rockauto_alternatives("12120037244")
  -> [NGK 97506 x6 $89.40, ...]
-> Final answer: "Total parts ~$340. Brake + clutch fluid use the same bottle ($18.40).
   Spark plugs are the biggest cost at $89 for a set of 6..."
```

### Tools available to the agent

| Tool | What it does |
|---|---|
| `get_schedule_status()` | All scheduled items with km/time overdue or remaining |
| `get_service_history(item_id?)` | Full history, optionally filtered to one item |
| `get_vehicle_info()` | VIN, engine, odometer, manufacture date |
| `search_catalog(query)` | RealOEM keyword/description search -> matching group codes + part lists |
| `get_diagram(group_code)` | Parts list for a specific catalog group |
| `get_part_detail(oem_pn)` | OEM description, price, supersession from RealOEM |
| `get_rockauto_alternatives(oem_pn)` | RockAuto alternatives with brand, price, availability |
| `add_to_plan(oem_pn, qty, plan_id?)` | Add a part to the active service plan |
| `get_plan(plan_id?)` | Current service plan with all selected parts and jobs |
| `parse_service_note(text)` | Parse free-text into structured `performed_by`/`parts`/`notes` |

### Features powered by the agent

#### 1. Maintenance advisor / general assistant
> *"What should I prioritise at 80,000 km with a budget of about $2,000?"*
> *"What's the total cost to fix everything overdue?"*
> *"Is it worth doing the gearbox oil at this mileage?"*

The agent calls `get_schedule_status()`, then autonomously digs into parts/pricing for overdue items to build a costed recommendation.

Exposed as: `POST /api/ai/chat` -> `{ message: str, history: [...] }` -> `{ reply: str, tool_calls: [...] }`  
Also: `bmw-helper ai ask "<question>"`

#### 2. Natural language catalog search
> *"I need to fix oil leaks around the valve cover and oil filter housing"*

The agent calls `search_catalog()` with variations of the query, returns matching diagram paths. The UI navigates directly to those diagrams.

#### 3. Plan builder
> *"Add everything I need for a valve cover gasket job"*

The agent calls `search_catalog()`, `get_diagram()`, identifies the relevant parts, calls `add_to_plan()` for each one. User sees parts appear in the plan in real time.

#### 4. Service note parser
> *"replaced the valve cover gasket, Elring part, shop said no warranty because the car is old"*

The agent calls `parse_service_note()` -> returns structured fields ready to save.

#### 5. Quote email refinement
After the template renders, the user can ask the agent to adjust specific sections in plain language.

### Architecture

```
bmw_helper/
|-- ai.py          # AIClient: Ollama connection check, agent loop, tool registry
\-- ai_tools.py    # Tool implementations (thin wrappers over existing app functions)
```

```python
# ai.py
class AIClient:
    def __init__(self, model: str = "qwen3:8b", host: str = "http://localhost:11434"):
        # Raises RuntimeError if Ollama is not reachable or model is not pulled

    def chat(self, message: str, history: list[dict]) -> tuple[str, list[dict]]:
        """Run the agent loop. Returns (final_reply, updated_history)."""

# ai_tools.py -- each function becomes a tool the agent can call
def get_schedule_status() -> list[dict]: ...
def get_service_history(item_id: str | None = None) -> list[dict]: ...
def get_vehicle_info() -> dict: ...
def search_catalog(query: str) -> list[dict]: ...
def get_diagram(group_code: str) -> dict: ...
def get_part_detail(oem_pn: str) -> dict: ...
def get_rockauto_alternatives(oem_pn: str) -> list[dict]: ...
def add_to_plan(oem_pn: str, qty: int = 1, plan_id: str | None = None) -> dict: ...
def parse_service_note(text: str) -> dict: ...
```

### Manual path is always available

The AI is an *accelerator*, not a replacement for the manual workflow. Every action the agent can take is also available manually:

| Task | Manual path | AI path |
|---|---|---|
| Find parts for a job | Browse catalog tree -> navigate to diagram -> click callouts | Ask agent: *"add everything for valve cover gasket"* |
| Check what's due | Read dashboard status table | Ask agent: *"what should I do first?"* |
| Add a part to plan | Click part row -> "Add to plan" button | Agent calls `add_to_plan()` |
| Record service | `bmw-helper history record ...` flags | Describe in plain text -> agent parses + records |
| Build quote email | Select jobs in plan UI -> generate | Agent assembles plan from conversation |

The catalog browser UI (three-panel: tree / diagram / parts table) is always present regardless of whether the agent is used. The AI chat panel sits alongside it as an optional accelerator -- not gating any functionality.

### Phase placement

`ai.py` and `ai_tools.py` are built in **Phase 4** alongside the catalog browser. The startup check (Ollama running + model available) is enforced from Phase 4 onward. The chat endpoint powers a persistent conversation panel in the web UI sidebar.

---

## RealOEM Integration

RealOEM has no public API. Scraping approach:

1. **VIN -> Catalog ID**: `GET realoem.com/bmw/enUS/select?vin=<VIN>` -> parse catalog/model ID for the vehicle.
2. **Category tree**: `GET realoem.com/bmw/enUS/showparts?id=<catalog-id>` -> parse the left-nav tree of systems/groups.
3. **Group/diagram**: `GET realoem.com/bmw/enUS/showparts?id=<catalog-id>&fg=<group-code>` -> parse the parts table (position, OEM PN, description, qty).
4. **Part price**: Parse the price shown in the parts table, or follow to the part detail page.
5. **Part search**: `GET realoem.com/bmw/enUS/findpart?id=<catalog-id>&sch=<OEM_PN>` -> verify PN fits vehicle, get description, check for supersessions.

All responses are cached with `diskcache` keyed by `(catalog_id, group_code)` or `(catalog_id, oem_pn)`. TTL: 7 days. Cache is stored in `~/.bmw_helper/cache/realoem/`.

Rate limiting: 1 request/second, `User-Agent` mimicking a normal browser. Personal use only.

Reference implementations: `ballon3/realoem`, `MoAshrafPT/realoem_scraper` on GitHub.

---

## RockAuto Integration

`rsp2k/rockauto-api` (async Python client). Workflow per part:

1. Use vehicle config to navigate: make -> year -> model -> engine -> get vehicle key.
2. Determine the RockAuto part category from the OEM part description (e.g. "Oil Filter Housing Gasket" -> category "Gasket").
3. Fetch listings for that category/vehicle; filter by OEM interchange numbers matching the target OEM PN.
4. Return the top alternatives sorted by price, with brand, PN, price, and availability.
5. Cache results in `~/.bmw_helper/cache/rockauto/` with 24-hour TTL (prices change more frequently).

---

## Estimate PDF Parser

`pdfplumber` extracts text and table data. The parser identifies:

- **Shop block**: company name, address, phone, email, GST number -- via regex on the header area.
- **Vehicle block**: owner name, year/make/model, VIN -- typically just below the shop address.
- **Line item table**: DATE | ACTIVITY | DESCRIPTION | TAX | QTY | RATE | AMOUNT -- extracted as a table.
  - OEM part numbers are extracted from DESCRIPTION using BMW PN regex patterns (11-13 digit numbers, formatted with spaces or dashes).
  - Brand names are extracted from DESCRIPTION (Elring, INA, Febi, Genuine BMW, etc.).
- **Totals block**: SUBTOTAL, TAX, TOTAL -- extracted from the footer area.

The parser will handle the ShopA format as the first target. A pluggable `ParserStrategy` base class allows adding new shop PDF formats without touching the core parser.

---

## Estimate Comparison

`bmw-helper estimate compare` produces a rich table:

```
JOB / PART                          ShopA #1885          Shop 2 #XXX         REF (RockAuto)
------------------------------------------------------------------------------------------------
OIL FILTER HOUSING GASKET
  Labour (4.6h @ $149/h)             $685.40                  ---
  Gasket upper -- Elring               $36.20                  ---                  $18.20
  Gasket lower -- Elring               $34.50                  ---                  $15.60
  O-rings x2 -- CRP                    $6.62                  ---                   $5.80
  Subtotal                           $762.72                  ---
------------------------------------------------------------------------------------------------
VALVE COVER GASKET
  Labour (5.8h @ $149/h)             $864.20
  Valve cover gasket -- Elring         $89.60
  Subtotal                           $953.80
------------------------------------------------------------------------------------------------
TOTAL (pre-tax)                    $8,137.27
TOTAL (with GST 5%)                $8,544.18
------------------------------------------------------------------------------------------------
Effective labour rate               $149.00/h
```

Comparison maps estimate line items to jobs via OEM PN matching and description fuzzy matching.

---

## Quote Email Template Structure

The rendered email mirrors the example provided:

1. **Greeting + intro** -- one paragraph stating vehicle, work scope, and parts quality requirements
2. **VEHICLE block** -- formatted table: VIN, year, model, engine, trans, drive, odometer
3. **WORK REQUESTED** -- numbered list of jobs, each containing:
   - Job name
   - Parts sub-list: description -- OEM PN (e.g. `* Valve cover gasket -- 11127565286`)
   - Optional notes (overlapping labour, preferred kit, customer-supplied, no warranty)
4. **ADDITIONAL** -- any add-on items tied to another job's teardown
5. **Closing** -- sign-off with owner name

The template is fully data-driven from the service plan, so adding/removing jobs in the plan automatically updates the email.

---

## Phase Plan

### Phase 1 -- Foundation
- [ ] `pyproject.toml`, dependencies, virtualenv setup
- [ ] `vehicle.yaml` schema + example for E93 335i
- [ ] Pydantic models (`models.py`)
- [ ] Config loader (`config.py`)
- [ ] Typer CLI skeleton with command groups
- [ ] `bmw-helper config show`

### Phase 2 -- Maintenance Schedule + Dashboard
- [ ] `pdfplumber` parser for N54 community schedule PDF -> `config/schedule.yaml`
- [ ] `bmw-helper schedule import` command
- [ ] Service history model + `config/service_history.yaml` read/write
- [ ] `bmw-helper history record/show` commands
- [ ] Status computation (overdue/due soon/ok/unknown) given current odometer
- [ ] FastAPI endpoints: `/api/schedule/status`, `/api/history`
- [ ] Dashboard home page (`/`) with status table; `[+]` button opens "add to plan" dialog
- [ ] `bmw-helper schedule status` terminal output

### Phase 3 -- RealOEM Catalog Scraper
- [ ] VIN -> catalog ID lookup
- [ ] Category tree navigation
- [ ] Diagram/parts list fetching
- [ ] Part detail + supersession lookup
- [ ] `diskcache` integration
- [ ] `bmw-helper catalog part <oem-pn>` and `search` commands

### Phase 3 -- RockAuto Integration
- [ ] Vehicle hierarchy navigation to vehicle key
- [ ] Part category search + OEM interchange matching
- [ ] Caching
- [ ] `bmw-helper catalog part` enriched with RockAuto alternatives

### Phase 4 -- Catalog Browser Web UI + LLM
- [ ] `bmw_helper/ai.py` -- Ollama client, `available()` check, prompt builders
- [ ] `POST /api/ai/advise` -- maintenance advisor endpoint
- [ ] `bmw-helper ai ask` CLI command
- [ ] Three-panel catalog browser UI (category tree / diagram / parts table)
- [ ] SVG hotspot overlay on diagram image (from RealOEM image map coords)
- [ ] Bidirectional hover/select between diagram callouts and parts table row
- [ ] Natural language search box -> LLM maps query to catalog paths
- [ ] Part selection -> add to active service plan
- [ ] `POST /api/ai/catalog-search` endpoint

### Phase 5 -- Service Plan
- [ ] Plan creation, persistence (JSON)
- [ ] Part add/remove, job grouping
- [ ] `bmw-helper plan *` commands

### Phase 6 -- Quote Email Generator
- [ ] Jinja2 template
- [ ] Email renderer
- [ ] `bmw-helper email generate`

### Phase 7 -- Estimate Parsing + Comparison
- [ ] `pdfplumber` parser for ShopA format
- [ ] Estimate JSON storage
- [ ] `bmw-helper estimate import/list/show/compare`

---

## Open Questions / Risks

1. **RealOEM scraping fragility** -- No public API; site structure may change. Mitigate with aggressive caching and clear error messages when scraping fails.
2. **RealOEM currency** -- Prices shown depend on the user's locale. The scraper should detect/set CAD pricing.
3. **rockauto-api stability** -- Mimics browser behaviour; RockAuto may change their structure. Pin the version; test real lookups early.
4. **PDF parser coverage** -- Each shop formats estimates differently. ShopA is target format for Phase 7; other formats handled as they come in.
5. **VIN -> RealOEM catalog mapping** -- Some VINs may not resolve cleanly (e.g. if the car was optioned differently from a standard catalog entry). Need manual override in `vehicle.yaml`.
6. **Email sending** -- Out of scope for now; generate text only. Gmail API integration is a natural follow-on.
