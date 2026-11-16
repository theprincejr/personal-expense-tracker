# Personal Expense Tracker

A lightweight, single-user local web application for recording, filtering, and summarizing daily expenses, built with Python, Flask, SQLite, and vanilla JavaScript. Designed for zero-configuration local execution, exact monetary arithmetic, and durable persistence without external database servers or cloud dependencies.

---

## 1. What the Application Does

The Personal Expense Tracker provides an intuitive web interface backed by a REST API for personal financial management:

- **Record Daily Expenses:** Add transactions with a short title, amount in Indian Rupees (₹), category, date, and an optional explanatory note. Dates default automatically to the user's local calendar date.
- **Reverse-Chronological Expense Log:** View all recorded expenses in a clean, responsive table sorted newest first, with a deterministic secondary sort by ID (`ORDER BY date DESC, id DESC`).
- **In-Place Editing:** Switch the main form into edit mode by clicking "Edit" on any expense row. Values populate the form immediately, and the update is saved without page reload while preserving active list filters.
- **Delete with Confirmation:** Remove expenses using browser-native confirmation dialogs (`window.confirm()`) to prevent accidental deletion. Both table rows and summary totals refresh immediately.
- **Independent Monthly Summary:** A persistent overview card displays total spending, transaction count, and category breakdown for the current calendar month. The summary is computed directly from SQLite using Python date arithmetic and remains completely independent of active table filters.
- **Multi-Criteria Filtering & Search:**
  - **Category Filter:** Filter expenses by specific categories.
  - **Inclusive Date Range:** Filter records between `from_date` and `to_date` inclusive.
  - **Partial Title Search:** Find expenses by title keywords with automatic escaping of SQL wildcard characters (`%`, `_`, `!`).
  - **Reset Filters:** Clear all active filters with a single click to restore the full expense history.
- **Responsive Interface:** Custom layout that adapts between desktop monitors, tablets, and mobile screens down to 375px.

---

## 2. Why These Technologies Were Chosen

| Technology | Selection Rationale |
|:---|:---|
| **Python 3.11+ & Flask** | **Lightweight backend and straightforward REST API.** Flask provides a minimal, synchronous web framework with zero unnecessary abstractions. It handles JSON routing, request parsing, and static file delivery from a single process (`python app.py`) without requiring a complex web server stack. |
| **SQLite 3 (`sqlite3` stdlib)** | **Zero-configuration local relational database.** SQLite requires no external database server daemon, background processes, user authentication, or network port configuration. It stores all data in a single local file (`expenses.db`), providing full ACID transactions and durability across application restarts. |
| **Vanilla JavaScript (ES6+)** | **Native browser APIs without build complexity.** Native `fetch()` and direct DOM manipulation provide full interactivity without external dependencies, npm packages, node runtimes, or build pipelines (Webpack, Vite, Babel). This eliminates dependency management friction and transpilation steps. |
| **Integer Paise Storage** | **Exact monetary precision.** IEEE 754 binary floating-point numbers (`FLOAT` or `REAL`) cannot accurately represent decimal fractions like `0.10` or `0.20`, leading to cumulative rounding errors in financial balances. Storing values as integer paise (₹1.00 = 100 paise) guarantees exact base-10 integer arithmetic. |
| **Python `Decimal` Conversion** | **Safe string-to-integer parsing.** Amounts are accepted as formatted strings (e.g., `"250.50"`) and converted using Python's `decimal.Decimal` module before being stored as integer paise. This avoids intermediate floating-point conversions at the API boundary. |
| **Parameterized SQL & Constraints** | **Defense-in-depth data integrity.** SQL queries use parameterized bindings (`?` placeholders) to eliminate SQL injection risks. Input is validated at the Flask application layer for clear user feedback, and enforced independently at the database layer via SQLite `CHECK` constraints. |

---

## 3. Architecture & Data Flow

The application follows a clean layered architecture separating presentation, API routing, business validation, and database operations.

```text
Browser UI (Semantic HTML5 / CSS3 / Vanilla JavaScript)
  │
  │ HTTP JSON Requests (fetch: GET, POST, PUT, DELETE)
  ▼
Flask Application Layer (app.py)
  ├─ URL Routing & Request Dispatching
  ├─ Content-Type & JSON Payload Verification
  ├─ Input Validation (Decimal monetary parsing, ISO date checks)
  ├─ Uniform Error Envelope Generation (400, 404, 415, 500)
  └─ Per-Request Database Connection Lifecycle (Flask g & teardown)
  │
  │ Parameterized SQL Queries (? parameter bindings)
  ▼
Data-Access & Database Layer (database.py)
  ├─ Single Source of Truth Constants (ALLOWED_CATEGORIES)
  ├─ Database Schema Initialization
  └─ SQLite Storage (expenses.db with CHECK constraints)
```

### Typical Request Lifecycle: Adding or Editing an Expense

1. **User Action:** The user fills out the form in the web interface and clicks "Add Expense" (or "Save Changes" in edit mode).
2. **Client Dispatch:** `static/app.js` performs client-side field validation and issues an asynchronous `fetch()` request (`POST /api/expenses` or `PUT /api/expenses/<id>`) with an `application/json` payload.
3. **API Validation:** `app.py` intercepts the request:
   - Validates that `Content-Type` is `application/json`.
   - Validates that title and category are valid and within allowed length limits.
   - Converts the decimal amount string into integer paise via `Decimal`.
   - Validates calendar date format and calendar existence using `datetime.strptime()`.
4. **Database Execution:** `database.py` executes a parameterized `INSERT` or `UPDATE` statement against `expenses.db` using SQLite `?` placeholders.
5. **Constraint Check:** SQLite validates table `CHECK` constraints (positive amount, allowed category, valid calendar date).
6. **Response & UI Update:** Flask returns HTTP 201 (Created) or HTTP 200 (OK) with the saved expense object. The frontend shows a temporary success notification, re-fetches the current filtered list, and updates the monthly summary card.

### Application Factory & Connection Management

- **Application Factory (`create_app`):** The application is instantiated via `create_app(test_config=None)`. This isolates configuration state, allows test suites to inject custom database configurations, and enables automatic discovery by the Flask CLI (`flask --app app run`).
- **Connection Lifecycle:** SQLite database connections are stored in Flask's application context `g.db`. Connections are opened lazily on first access and closed cleanly at the end of each HTTP request via `@app.teardown_appcontext`, preventing connection leaks.

---

## 4. Database Design & Schema

The application uses a single table named `expenses` defined with strict column types and database-level `CHECK` constraints:

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

### Schema Specifications

| Column | Type | Constraints | Description |
|:---|:---|:---|:---|
| `id` | `INTEGER` | `PRIMARY KEY` | Unique primary key assigned by SQLite. |
| `title` | `TEXT` | `NOT NULL`, 1–100 chars | Non-empty expense title, trimmed of leading/trailing whitespace. |
| `amount_paise` | `INTEGER` | `NOT NULL`, $1 \le \text{paise} \le 1,000,000,000$ | Expense amount stored as an integer number of paise (up to ₹10,000,000.00). |
| `category` | `TEXT` | `NOT NULL`, Restricted Enum | Restricted to exactly: `Food`, `Transport`, `Shopping`, `Bills`, `Entertainment`, `Other`. |
| `date` | `TEXT` | `NOT NULL`, ISO 8601 `YYYY-MM-DD` | Valid calendar date string. Verified by regex format and SQLite calendar math. |
| `note` | `TEXT` | `NULL`, max 500 chars | Optional supplementary notes, or `NULL` if omitted. |

### Database Integrity Features

1. **Integer Currency Representation:** Monetary values are stored as whole numbers of paise. ₹150.50 is stored as `15050`. The database `CHECK (amount_paise > 0)` prevents zero or negative amounts from ever being written.
2. **Category Restrictions:** The category column is constrained by a `CHECK (category IN (...))` expression generated from `database.ALLOWED_CATEGORIES`, establishing Python as the single source of truth for business rules.
3. **Native Calendar Date Integrity:** In addition to format checking (`GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'`), SQLite enforces real calendar dates via `date(date, '+0 days') = date`. Non-existent dates like `2026-02-30` or non-leap-year `2025-02-29` normalize to another date in SQLite (e.g., `2026-03-02`), violating equality and raising `sqlite3.IntegrityError` directly at the database level.

---

## 5. API Reference

All API responses return `application/json`. Requests with bodies (`POST` and `PUT`) require `Content-Type: application/json` and a JSON payload; `GET` and `DELETE` requests do not require a request body. Errors follow a uniform JSON envelope:
```json
{
  "error": "Human-readable description of the error",
  "code": "ERROR_CODE_IDENTIFIER"
}
```

### Endpoint Summary

| Endpoint | Method | Query / Payload | Status | Description |
|:---|:---:|:---|:---:|:---|
| `/api/expenses` | `GET` | Query params: `category`, `from_date`, `to_date`, `q` | `200`, `400` | Returns a list of expenses matching the active filters, ordered by `date DESC, id DESC`. Rejects invalid categories, malformed dates, or reversed date ranges (`from_date > to_date`) with HTTP 400. |
| `/api/expenses` | `POST` | JSON body: `{ "title": "...", "amount": "...", "category": "...", "date": "...", "note": "..." }` | `201`, `400`, `415` | Creates a new expense. `amount` must be a formatted decimal string. `date` is optional and defaults to today's local date if omitted; an explicit empty string is rejected with HTTP 400. |
| `/api/expenses/<int:id>` | `PUT` | JSON body: `{ "title": "...", "amount": "...", "category": "...", "date": "...", "note": "..." }` | `200`, `400`, `404`, `415` | Updates an existing expense by ID. `date` is mandatory and does not default. Oversized IDs exceeding SQLite integer limits return HTTP 404. |
| `/api/expenses/<int:id>` | `DELETE`| None | `200`, `404` | Deletes an expense by ID. Returns `{ "success": true }`. Non-existent or overflow IDs return HTTP 404. |
| `/api/summary/current-month` | `GET` | None | `200` | Returns total monthly expenditure, total expense count, and per-category breakdown for the current month. Filter-independent. |

---

## 6. Key Engineering Decisions

### Exact Monetary Precision
Financial calculations cannot tolerate binary floating-point errors (such as `0.1 + 0.2 = 0.30000000000000004`). By requiring amounts as decimal strings at the API boundary, validating them with Python's `Decimal` class, and storing them as integer paise in SQLite, rounding discrepancies are completely prevented throughout the storage and retrieval lifecycle.

### Strict Calendar Date Validation
Date strings are checked against `datetime.strptime(val, "%Y-%m-%d")` in Python and independently validated in SQLite using `date(date, '+0 days') = date`. This dual-layer defense rejects invalid leap year dates, impossible days (e.g. February 30), and malformed strings before they can corrupt reports.

### Inclusive Filtering & Safe Wildcard Escaping
- **Inclusive Range:** Date boundaries include both the start date and end date (`date >= from_date AND date <= to_date`), matching standard human expectations.
- **Wildcard Escaping:** When searching by title, SQL wildcards (`%`, `_`) and the escape character (`!`) are safely escaped in Python before binding to the query (`title LIKE ? ESCAPE '!'`). Searching for `100%` finds records containing the literal string `"100%"` rather than treating `%` as a wildcard.

### Independent Monthly Summaries
The monthly summary card displays current month spending regardless of what filters the user applies to the expense table. This ensures users always retain high-level visibility over their overall monthly budget even when drilling down into a specific category or date range.

### Frontend Request Sequencing & Race Condition Prevention
When typing in the search box or changing filters quickly, network requests can finish out of order. To prevent an older, slower search response from overwriting newer search results, `static/app.js` tracks an incremental request counter and utilizes browser `AbortController` instances. Obsolete pending requests are cancelled immediately when new input occurs, and any out-of-order responses are discarded.

### Visible Frontend Error States
If a network error or server failure occurs while loading expenses or the monthly summary, the interface does not leave stale data on screen. Stale rows or summary numbers are cleared, and a visible, user-friendly error notice is displayed in the respective card. Existing filter inputs are preserved so users can adjust or retry their query.

### Safe Test Database Isolation
To ensure test runs never touch, overwrite, or delete real user data in `expenses.db`, the test suite establishes an isolated sandbox using Python's `tempfile.TemporaryDirectory()`. The test harness sets the `EXPENSES_DB` environment variable before importing application modules, guaranteeing that running `python test_app.py` leaves real databases 100% byte-for-byte untouched.

---

## 7. Installation & Running

### Prerequisites
- Python 3.11+
- `pip` package manager (`Flask>=3.0,<4` specified in `requirements.txt`)

### Option A: Windows (PowerShell)

```powershell
# 1. Clone or navigate to the project directory
cd <project-directory>

# 2. (Optional) Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# Note: If PowerShell script execution is restricted, run:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
python app.py
```

### Option B: macOS / Linux (Bash)

```bash
# 1. Navigate to the project directory
cd <project-directory>

# 2. (Optional) Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the application
python3 app.py
```

### Accessing the Web Interface
Once started, open any modern web browser and navigate to:
```text
http://127.0.0.1:5000
```

---

## 8. Automated Testing

The project includes an automated regression test suite in [`test_app.py`](test_app.py). Tests execute against an isolated temporary database and do not modify `expenses.db`.

### Running Tests
```powershell
python test_app.py
```

### Expected Output
```text
..........................
----------------------------------------------------------------------
Ran 26 tests in <duration>

OK
```
*(Execution time varies depending on host hardware and filesystem speed.)*

### Verified Test Scenarios (26 Tests)

1. **Creation & Persistence:** Expense creation and SQLite row retrieval.
2. **Amount Format Rejection:** Floats, integers, non-numeric strings, zero, negative, and values exceeding ₹10,000,000.00 rejected with HTTP 400.
3. **Decimal Precision & Conversion:** Sub-paise inputs (e.g. `12.345`) rejected; exact paise arithmetic confirmed (₹0.10 + ₹0.20 = 30 paise).
4. **Title Validation:** Blank, whitespace-only, and strings exceeding 100 characters rejected with HTTP 400.
5. **Category & Note Constraints:** Unknown categories and notes exceeding 500 characters rejected with HTTP 400; null notes accepted.
6. **Calendar Date Validation & SQLite Integrity:** Malformed dates, boolean values, and invalid calendar days (Feb 30) rejected by Python and SQLite `CHECK` constraints.
7. **POST Date Omission vs. Blank:** Omitted date defaults to local today; explicit blank string `""` rejected with HTTP 400.
8. **PUT Date Requirement:** Missing date on update rejected with HTTP 400 (never defaults to today).
9. **Filter Query Validation:** Invalid category or malformed dates in query parameters rejected with HTTP 400.
10. **Reversed Date Range:** Querying `from_date > to_date` returns HTTP 400.
11. **Inclusive Date Filtering:** Expenses falling on exact start or end date boundaries are included.
12. **Multi-Filter Combination:** Category, date range, and title search combined cleanly using SQL `AND`.
13. **Literal Wildcard Escaping:** Literal `%`, `_`, and `!` characters in search queries are matched literally.
14. **CRUD on Missing Records:** Non-existent IDs return HTTP 404 on `PUT` and `DELETE`.
15. **Monthly Summary Calculation:** Correct aggregation, deterministic sorting (`total_paise DESC, category ASC`), and filter independence.
16. **Database Isolation:** Confirms test execution is confined to `tempfile` and leaves `expenses.db` untouched.
17. **Persistence Across Restart:** Data persists across database connection closures and restarts.
18. **Payload Fidelity & XSS Protection:** Backend preserves characters faithfully while frontend escapes HTML via safe DOM `textContent` rendering.
19. **Deterministic Ordering:** Multiple expenses on the same date are ordered deterministically by `id DESC`.
20. **Empty Note Handling:** Blank notes are safely stored and returned as `NULL`.
21. **Empty Month Summary:** Returns zero total, zero count, and an empty breakdown list when no expenses exist in the current month.
22. **Oversized Expense IDs:** IDs exceeding 64-bit integer limits on `PUT` and `DELETE` return HTTP 404 rather than unhandled 500 server errors.
23. **Unicode & Embedded NUL Safety:** Embedded NUL bytes (`\x00`) and lone surrogates are rejected with HTTP 400; valid multi-language Unicode (e.g. Malayalam) is fully supported.
24. **API Filter Query Isolation:** Verifies that creating an expense while query filters are active does not alter the filtered endpoint's query boundaries. (Note: Frontend filter input preservation across actions is implemented in JavaScript but has not been tested using automated browser interaction.)
25. **Application Factory Schema Auto-Init:** `create_app()` ensures database tables and constraints are initialized for any configured target database.
26. **Import Isolation Without Default DB:** Importing the `app` module in a clean directory does not create or touch `expenses.db`.

---

## 9. Design Trade-offs & Limitations

- **Single-User Scope:** Designed as a personal desktop tool. Does not include multi-user authentication, password management, or concurrent multi-tenant data partitioning.
- **Single Currency (INR / ₹):** Currency formatting and symbol displays are configured specifically for Indian Rupees. Multi-currency conversion is not implemented.
- **SQLite `LIKE` Unicode Case Folding:** SQLite's default built-in `LIKE` operator is case-insensitive for standard ASCII characters (`A-Z`), but case-sensitive for non-ASCII Unicode characters (e.g., accented characters) unless an external ICU extension is loaded.
- **Local File Persistence:** Relies on local filesystem storage (`expenses.db`). Backups can be made simply by copying the database file when the application is stopped.
