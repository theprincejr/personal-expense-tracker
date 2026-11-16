# Personal Expense Tracker

A fast, reliable, and interview-explainable local Personal Expense Tracker built with Python 3.11+, Flask>=3.0,<4, SQLite 3, and vanilla JavaScript. Developed for a time-boxed practical software engineering assessment with an emphasis on code hygiene, exact monetary calculations, edge-case resilience, and explainable design decisions.

---

## 1. Project Overview & Features

### Overview
The Personal Expense Tracker enables users to manage daily expenses locally without external server infrastructure or third-party cloud services. The application enforces strict financial data integrity, exact base-10 arithmetic, and comprehensive input validation across both client and server boundaries.

### Core Features Implemented
- **Add Expense:** Capture title, amount (decimal string), category, date (defaults to today's local calendar date), and optional note.
- **View Expenses:** Real-time table displaying all recorded fields, sorted newest date first with deterministic secondary ordering (`ORDER BY date DESC, id DESC`).
- **In-Place Editing:** Top form switches seamlessly between Add Mode and Edit Mode with pre-populated values and a visible "Cancel Edit" option.
- **Delete with Native Confirmation:** Uses browser-native `confirm()` before removing records, immediately updating list and summary views.
- **Independent Monthly Summary:** Real-time card showing current month total spending, transaction count, and category breakdown. Calculated strictly using Python date arithmetic (`date >= first_day_cur AND date < first_day_next`) and completely isolated from active list filters.
- **Multi-Criteria Filtering:**
  - Category dropdown filter.
  - Inclusive date range filter (`from_date` to `to_date`).
  - Case-insensitive literal title search using SQL LIKE with `!` wildcard escaping.
  - Instant "Reset Filters" button.
- **Responsive Interface:** Custom CSS grid and flexbox layout optimized for both desktop and narrow mobile screens (375px+).

---

## 2. Technology Stack & Decision Rationale

| Layer | Technology | Decision Rationale |
| :--- | :--- | :--- |
| **Backend** | **Python 3.11+ / Flask>=3.0,<4** | Minimal, synchronous web framework already available in the environment. Serves both static assets and REST API from a single process (`python app.py`) with zero build step or bundler friction. |
| **Database** | **SQLite 3 (`sqlite3` stdlib)** | Serverless, zero-configuration ACID database (`expenses.db`). Guarantees durable local persistence across application restarts without external credentials or containers. |
| **Frontend** | **Semantic HTML5, CSS3, Vanilla JavaScript (`fetch`)** | Avoids npm package downloads, transpilation, and Webpack/Vite bundler configuration. Direct DOM manipulation with safe `textContent` rendering. |
| **Monetary Precision** | **Integer Paise (`amount_paise`) + Python `Decimal`** | IEEE 754 binary floating-point numbers (`FLOAT`/`REAL`) cannot accurately represent decimal fractions like `0.1` or `0.2`, causing cumulative rounding errors. Storing integer paise (₹1.00 = 100 paise) guarantees exact monetary arithmetic without floating-point rounding errors. |
| **Calendar Dates** | **ISO 8601 (`YYYY-MM-DD`) Strings** | Expenses are discrete calendar events, not timestamps. Treating dates strictly as `YYYY-MM-DD` strings avoids timezone conversion bugs that shift dates across midnight. |

---

## 3. Architecture & Request Data Flow

```
[ Browser UI: Vanilla JS (app.js) ]
  ├─ Single Unified Add/Edit Form (with Cancel option)
  ├─ Filter Bar (Category, Dates, Search with '!' Escaping)
  ├─ Monthly Summary Card (Total & Category Breakdown)
  ├─ Responsive Expense Table (Edit populates form, Delete uses confirm())
  └─ Currency Display: Formatted from amount_paise via integer division/modulo
         │
         │ (JSON HTTP: POST / PUT / GET / DELETE)
         ▼
[ Flask Application (app.py) ]
  ├─ Per-Request SQLite Connection (g.db & @app.teardown_appcontext)
  ├─ Strict Content-Type (415) & JSON Body (400) Verification
  ├─ Decimal Monetary Parsing (Decimal -> Integer Paise)
  ├─ Reusable Calendar Date Validator (datetime.strptime)
  ├─ Python Date Arithmetic for Current Month Boundaries
  ├─ Dynamic SQL Query Builder with '!' Wildcard Escaping
  └─ Uniform JSON Error Envelope (400, 404, 405, 415, 500)
         │
         │ (Parameterized SQL with ? bindings)
         ▼
[ Database Access Layer (database.py) ]
  ├─ Single Source of Truth: ALLOWED_CATEGORIES tuple
  ├─ DDL Generation with Safely Quoted Literals
  └─ SQLite Database (expenses.db with CHECK constraints)
```

---

## 4. Database Schema & Design Decisions

```sql
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 100),
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0 AND amount_paise <= 1000000000),
    category TEXT NOT NULL CHECK (category IN ('Food', 'Transport', 'Shopping', 'Bills', 'Entertainment', 'Other')),
    date TEXT NOT NULL CHECK (length(date) = 10 AND date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(date, '+0 days') = date),
    note TEXT NULL CHECK (note IS NULL OR length(note) <= 500)
);
```

### Design Details:
1. **`id INTEGER PRIMARY KEY`:** Standard SQLite rowid primary key; avoids the internal `sqlite_sequence` overhead of `AUTOINCREMENT`.
2. **`amount_paise`:** Stored as an integer up to ₹10,000,000 (1,000,000,000 paise). The `CHECK` constraint guarantees positive values at the storage level.
3. **Dual-Layer Defense:** Validations are enforced in Python for friendly error messaging, and backed by hard database `CHECK` constraints to guarantee data integrity.
4. **Single Source of Truth:** `ALLOWED_CATEGORIES` is defined in Python; DDL quotes these constants safely during schema creation without SQL injection risk.
5. **Native SQLite Calendar Validation:** SQLite independently enforces calendar date integrity via `date(date, '+0 days') = date`. Impossible dates such as `2026-02-30` or non-leap `2025-02-29` normalize to another date (e.g., `2026-03-02`), violating equality and raising `sqlite3.IntegrityError` directly at the database layer, even for direct SQL inserts.

---

## 5. API Endpoints & Responsibilities

All endpoints consume and return `application/json`. Errors follow a uniform format: `{ "error": "Message", "code": "ERROR_CODE" }`.

| Endpoint | Method | Request Payload / Query Params | Status Codes | Description |
| :--- | :---: | :--- | :---: | :--- |
| `/api/expenses` | `GET` | Query: `category`, `from_date`, `to_date`, `q` | `200`, `400` | Lists expenses matching filters, sorted by `date DESC, id DESC`. Rejects reversed date ranges (`from > to`) with 400. |
| `/api/expenses` | `POST` | Body: `{ title, amount, category, date?, note? }` | `201`, `400`, `415` | Creates an expense. `amount` must be a decimal string. Omitted date defaults to local today; explicit blank date is rejected. |
| `/api/expenses/<int:id>` | `PUT` | Body: `{ title, amount, category, date, note? }` | `200`, `400`, `404`, `415` | Updates existing expense. Date is strictly required. |
| `/api/expenses/<int:id>` | `DELETE`| None | `200`, `404` | Deletes expense by ID. Returns `{ success: true }`. |
| `/api/summary/current-month` | `GET` | None | `200` | Returns current month spending, count, and category breakdown. Isolated from list filters. |

---

## 6. Validation & Business Rules

1. **Title:** Required string; whitespace trimmed; must be 1–100 characters.
2. **Amount:** 
   - Must be sent as a decimal string (e.g. `"150.50"` or `"500"`). Non-string inputs (floats/integers) are rejected at the API boundary.
   - Validated via regex `^[0-9]{1,8}(\.[0-9]{1,2})?$` and parsed with `decimal.Decimal`.
   - Must be greater than zero and at most ₹10,000,000.
   - Values with $>2$ decimal places are rejected.
3. **Category:** Must strictly match one of: `Food`, `Transport`, `Shopping`, `Bills`, `Entertainment`, `Other`.
4. **Date:** 
   - ISO `YYYY-MM-DD` format verified by regex and `datetime.strptime()` calendar check (rejects impossible dates like `2026-02-30`).
   - On `POST`, omitting the field defaults to local today. Providing an explicit empty string `""` or invalid type is rejected with 400.
   - On `PUT`, date is mandatory and never defaults to today.
5. **Note:** Optional and nullable; whitespace trimmed; max 500 characters.
6. **Date Range Filters:** Both boundaries are inclusive (`date >= from AND date <= to`). If `from_date > to_date`, returns 400 Bad Request.

---

## 7. Installation & Startup Commands

### Prerequisites
- Python 3.11+
- `pip` package manager (`Flask>=3.0,<4` as specified in `requirements.txt`)

### Option A: Windows (PowerShell)

```powershell
# 1. Clone or navigate to the project directory
cd <project-directory>

# 2. (Optional) Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Note: If script execution is restricted in PowerShell, run:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
python app.py
```

### Option B: macOS / Linux (Bash)

```bash
# 1. Navigate to directory
cd <project-directory>

# 2. (Optional) Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
python3 app.py
```

### Open the Application
Open any modern web browser (e.g. Chrome, Firefox, Edge, Safari) and navigate to:
```
http://127.0.0.1:5000
```

---

## 8. Automated Testing & Verification Results

A dedicated automated regression test suite is provided in [`test_app.py`](test_app.py). It exercises all critical verification scenarios using an isolated temporary directory sandbox created via Python's `tempfile.TemporaryDirectory()`, ensuring `expenses.db` and any pre-existing databases remain completely untouched.

### Run Tests Command
```powershell
python test_app.py
```

### Actual Test Execution Output
```
Ran 26 tests in 1.410s

OK
```

### Summary of Verified Scenarios
1. **Creation & Persistence:** Valid expense creation and SQLite row retrieval.
2. **Amount Format Rejection:** Floats (`100.5`), ints (`100`), non-numeric strings (`"abc"`), zero (`"0.00"`), negative (`"-25.00"`), and $>₹10\text{M}$ rejected with 400.
3. **Decimal Precision & Conversion:** `12.345` rejected; ₹0.10 + ₹0.20 = exact 30 paise (₹0.30).
4. **Title Validation:** Blank, whitespace-only, and 101-character titles rejected with 400.
5. **Category & Note Constraints:** Invalid category and 501-character note rejected with 400; null notes accepted.
6. **Calendar Date Validation & SQLite Integrity:** February 30, malformed dates (`16-11-2026`), and boolean values rejected with 400; SQLite `CHECK (date(date, '+0 days') = date)` independently rejects invalid calendar dates directly at the database layer.
7. **POST Date Omission vs. Blank:** Omitted date defaults to local today; explicit `""` rejected with 400.
8. **PUT Date Requirement:** Missing date on PUT rejected with 400 (never defaults to today).
9. **Filter Validation:** Invalid category or malformed dates in query params rejected with 400.
10. **Reversed Date Range:** `from_date > to_date` rejected with 400 (`"From date cannot be later than To date"`).
11. **Inclusive Date Filtering:** Expenses on exact `from_date` and `to_date` boundaries included.
12. **Combined Filtering:** Category + date range + title search joined with `AND`.
13. **Literal Wildcard Escaping:** Literal `%`, `_`, and `!` searches escape SQL wildcards using `!`.
14. **CRUD & Missing Records:** Non-existent IDs return 404 for PUT and DELETE.
15. **Monthly Summary Calculation:** Correct aggregation, deterministic order (`total_paise DESC, category ASC`), and filter independence.
16. **Database Isolation:** Verifies data created during test runs is isolated in `tempfile.TemporaryDirectory()` and does not appear in `expenses.db`.
17. **Persistence Across Restart:** Data survives connection close and reconnect.
18. **API Payload Fidelity with HTML & XSS Defense:** Confirms backend faithfully stores and returns HTML/script tags (`<script>alert('xss')</script> & <b>Bold</b>`) without mangling or corruption, while frontend enforces XSS defense in the browser via DOM `textContent` assignment.
19. **Deterministic Ordering on Same Date:** Expenses on identical dates are deterministically ordered by `id DESC`.
20. **Empty Note Acceptance and Persistence:** Empty strings and omitted notes are safely accepted and stored as `NULL`.
21. **Empty Month Summary:** Displays 0 paise, 0 count, and empty breakdown list when no expenses exist for the month.
22. **Oversized Expense IDs:** Out-of-range/overflow IDs (`99999999999999999999`) on PUT and DELETE return controlled 404 responses, never 500.
23. **Unicode & Embedded NUL Safety:** Embedded NUL bytes (`\x00`) and lone surrogates are rejected with 400 across titles, notes, and search queries; valid Malayalam and multi-language Unicode text is fully supported.
24. **Filter Query Isolation & Preservation:** Adding expenses while filters are active preserves filter isolation and keeps query boundaries intact.
25. **Application Factory Schema Auto-Init:** `create_app()` automatically ensures the database schema and CHECK constraints are initialized for any configured database target.
26. **Import Isolation Without Default DB:** Verifies that importing the application module in a clean directory does not create or initialize a default `expenses.db`.

---

## 9. Implementation Walkthrough

### 1. Adding an Expense
The user enters title, amount, category, date, and note in the top form. `app.js` sends a `POST /api/expenses` request. `app.py` checks `Content-Type: application/json`, parses amount with `Decimal`, converts to integer paise, validates the date, and inserts into SQLite via parameterized SQL. The response returns HTTP 201 with the created record. The frontend shows a success banner, preserves any active filters, reloads the filtered expense list, and refreshes the monthly summary.

### 2. Editing & Deleting
- **Edit:** Clicking "Edit" on any table row populates the top form with existing data and changes the form into "Edit Mode" with a "Cancel Edit" button. Submitting sends a `PUT /api/expenses/<id>` request, updating the row in SQLite while preserving active filters.
- **Delete:** Clicking "Delete" invokes browser-native `window.confirm()`. Upon confirmation, a `DELETE /api/expenses/<id>` request is sent, deleting the row and refreshing list and summary views while preserving active filters.

### 3. Filtering, Searching & Race Condition Prevention
The filter bar captures category, date range, and title search. The backend constructs a parameterized query with `title LIKE ? ESCAPE '!'`, where `!`, `%`, and `_` are escaped. Results are sorted newest first (`ORDER BY date DESC, id DESC`).
- **Request Sequencing:** To prevent race conditions where slower older search responses overwrite newer filter results, `app.js` employs `AbortController` and an incremental request sequence counter. In-flight requests are automatically aborted upon new input, and any out-of-order responses are discarded.

### 4. Filter Interaction Behavior & Error Handling
- **Universal Filter Preservation:** Active filters (category, date range, search query) are strictly preserved across Add, Edit, and Delete operations.
- **Immediate Feedback:** Adding an expense displays a success notification even if the newly created record does not match the active filter criteria. The monthly summary card updates immediately to reflect the new expense, and the filtered table remains stable.
- **Visible List Error State:** If fetching expenses fails, stale table rows are removed and an explicit error message is displayed in the table empty state, while filter input values remain preserved so the user can easily adjust or reset them.
- **Visible Summary Error State:** If fetching the monthly summary fails, outdated numbers are cleared, an explicit "Unavailable" indicator is shown, and subsequent successful refreshes restore normal figures.
- **Reset Capability:** Users can click "Reset Filters" at any time to clear all active filters and view the full unfiltered expense history.

### 5. Monthly Summary Aggregation
`GET /api/summary/current-month` calculates the current local month span using Python date arithmetic (`date >= first_day_cur AND date < first_day_next`). The SQL query aggregates `SUM(amount_paise)` and `COUNT(*)` grouped by category, ordered deterministically by `total_paise DESC, category ASC`.

---

## 10. Explicit Project Assumptions

- **Currency:** Indian Rupee (INR / ₹) with exact integer paise storage.
- **Single Local User:** Single-user desktop/laptop application; no multi-tenant authentication or session management.
- **Local SQLite Storage:** File-based persistence in `expenses.db`.
- **No Cloud Deployment:** Local machine execution on `http://127.0.0.1:5000`.
- **Future Dates Permitted:** Users may record advance bookings or upcoming bills.

---

## 11. Trade-offs, Limitations & Deferred Features

### Technical Trade-offs
- **SQLite vs. PostgreSQL:** SQLite was selected for zero-configuration local evaluation. It has zero network overhead and requires no database server process, making it ideal for a 2-hour assessment.
- **Vanilla JavaScript vs. React:** Vanilla JS eliminates build tooling, Webpack/Vite bundlers, and npm dependencies. Direct DOM manipulation is transparent and easy to explain.
- **In-Place Form vs. Modals:** A single in-place form eliminates modal z-index stacking bugs, backdrop clicks, and accessibility pitfalls.

### Known Limitations
- **SQLite LIKE Unicode Case Folding:** SQLite's default built-in `LIKE` operator is case-insensitive for standard ASCII characters (`a-z`, `A-Z`), but case-sensitive for non-ASCII Unicode characters (e.g. accented Latin or Cyrillic) unless an external ICU extension is loaded.
- **Single-User Scope:** Does not support multi-user data partitioning or concurrent write locks across multiple distributed machines.

### Deliberately Deferred Features
- Multi-user authentication & authorization.
- Recurring automated expense scheduling.
- Receipt image uploads and OCR parsing.
- PDF / Excel export.
