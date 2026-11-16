"""Comprehensive Automated Regression Test Suite for Personal Expense Tracker.

Covers all 26 automated regression tests verifying full application correctness, edge cases, and security invariants.
"""

import atexit
import os
import tempfile

# CRITICAL STARTUP ORDERING GUARD:
# Establish an isolated temporary database environment BEFORE importing app or database modules.
# This prevents app.py's module-level `app = create_app()` from initializing the default expenses.db.
_module_temp_dir = tempfile.TemporaryDirectory()
_module_test_db = os.path.join(_module_temp_dir.name, "test_isolated.db")
_orig_expenses_db = os.environ.get("EXPENSES_DB")
os.environ["EXPENSES_DB"] = _module_test_db


def _cleanup_module_temp_db():
    try:
        _module_temp_dir.cleanup()
    except Exception:
        pass
    if _orig_expenses_db is not None:
        os.environ["EXPENSES_DB"] = _orig_expenses_db
    elif "EXPENSES_DB" in os.environ:
        del os.environ["EXPENSES_DB"]


atexit.register(_cleanup_module_temp_db)

import sqlite3
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

import database
from app import create_app, parse_amount_to_paise, validate_date_field, ValidationError


class ExpenseTrackerRegressionTests(unittest.TestCase):
    test_db_path: str = _module_test_db

    @classmethod
    def setUpClass(cls):
        cls.test_db_path = _module_test_db
        database.init_db(cls.test_db_path)

    @classmethod
    def tearDownClass(cls):
        # Additional teardown safety
        pass

    def setUp(self):
        # Clean test table before each test
        conn = database.get_connection(self.test_db_path)
        try:
            conn.execute("DELETE FROM expenses")
            conn.commit()
        finally:
            conn.close()

        self.app = create_app({"TESTING": True, "DATABASE": self.test_db_path})
        self.client = self.app.test_client()

    # 1. Valid expense creation and persistence
    def test_01_valid_expense_creation_and_persistence(self):
        payload = {
            "title": "Grocery Shopping",
            "amount": "450.75",
            "category": "Food",
            "date": "2026-11-16",
            "note": "Supermarket vegetables",
        }
        res = self.client.post("/api/expenses", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["title"], "Grocery Shopping")
        self.assertEqual(data["amount_paise"], 45075)
        self.assertEqual(data["category"], "Food")
        self.assertEqual(data["date"], "2026-11-16")
        self.assertEqual(data["note"], "Supermarket vegetables")
        self.assertIn("id", data)

        # Verify persisted in SQLite
        conn = database.get_connection(self.test_db_path)
        try:
            row = database.get_expense_by_id(conn, data["id"])
            self.assertIsNotNone(row)
            self.assertEqual(row["amount_paise"], 45075)
        finally:
            conn.close()

    # 2. Invalid amount types and formats
    def test_02_invalid_amount_types_and_formats(self):
        # Reject float at API boundary
        res1 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": 100.50, "category": "Food"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertIn("decimal string", res1.get_json()["error"])

        # Reject integer at API boundary
        res2 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": 100, "category": "Food"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("decimal string", res2.get_json()["error"])

        # Reject non-numeric string
        res3 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": "abc", "category": "Food"},
        )
        self.assertEqual(res3.status_code, 400)

        # Reject zero
        res4 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": "0.00", "category": "Food"},
        )
        self.assertEqual(res4.status_code, 400)
        self.assertIn("greater than zero", res4.get_json()["error"])

        # Reject negative
        res5 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": "-25.00", "category": "Food"},
        )
        self.assertEqual(res5.status_code, 400)

        # Reject > ₹10,000,000
        res6 = self.client.post(
            "/api/expenses",
            json={"title": "Test", "amount": "10000000.01", "category": "Food"},
        )
        self.assertEqual(res6.status_code, 400)
        self.assertIn("cannot exceed ₹10,000,000", res6.get_json()["error"])

    # 3. Decimal precision and exact paise conversion
    def test_03_decimal_precision_and_exact_paise(self):
        # More than 2 decimal places -> rejected
        res = self.client.post(
            "/api/expenses",
            json={"title": "Precision", "amount": "12.345", "category": "Food"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("up to 2 decimal places", res.get_json()["error"])

        # Exact conversion: 0.10 + 0.20 = 30 paise
        paise_1 = parse_amount_to_paise("0.10")
        paise_2 = parse_amount_to_paise("0.20")
        self.assertEqual(paise_1, 10)
        self.assertEqual(paise_2, 20)
        self.assertEqual(paise_1 + paise_2, 30)

        # Whole rupee without decimal point
        self.assertEqual(parse_amount_to_paise("500"), 50000)

    # 4. Blank and oversized titles
    def test_04_blank_and_oversized_titles(self):
        # Blank / whitespace title
        res1 = self.client.post(
            "/api/expenses",
            json={"title": "   ", "amount": "50.00", "category": "Food"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertIn("Title is required", res1.get_json()["error"])

        # Oversized title (>100 chars)
        res2 = self.client.post(
            "/api/expenses",
            json={"title": "X" * 101, "amount": "50.00", "category": "Food"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("cannot exceed 100 characters", res2.get_json()["error"])

        # Non-string title
        res3 = self.client.post(
            "/api/expenses",
            json={"title": 12345, "amount": "50.00", "category": "Food"},
        )
        self.assertEqual(res3.status_code, 400)
        self.assertIn("Title must be a string", res3.get_json()["error"])

    # 5. Invalid categories and notes
    def test_05_invalid_categories_and_notes(self):
        # Invalid category
        res1 = self.client.post(
            "/api/expenses",
            json={"title": "Lunch", "amount": "150.00", "category": "InvalidCategory"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertIn("Category must be one of", res1.get_json()["error"])

        # Oversized note (>500 chars)
        res2 = self.client.post(
            "/api/expenses",
            json={"title": "Lunch", "amount": "150.00", "category": "Food", "note": "N" * 501},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("cannot exceed 500 characters", res2.get_json()["error"])

        # Note is null -> permitted
        res3 = self.client.post(
            "/api/expenses",
            json={"title": "Lunch", "amount": "150.00", "category": "Food", "note": None},
        )
        self.assertEqual(res3.status_code, 201)
        self.assertIsNone(res3.get_json()["note"])

    # 6. Invalid and impossible dates
    def test_06_invalid_and_impossible_dates(self):
        # Impossible date: Feb 30 (API level)
        res1 = self.client.post(
            "/api/expenses",
            json={"title": "Coffee", "amount": "50.00", "category": "Food", "date": "2026-02-30"},
        )
        self.assertEqual(res1.status_code, 400)
        self.assertIn("not a valid calendar date", res1.get_json()["error"])

        # Malformed format (DD-MM-YYYY)
        res2 = self.client.post(
            "/api/expenses",
            json={"title": "Coffee", "amount": "50.00", "category": "Food", "date": "16-11-2026"},
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("YYYY-MM-DD format", res2.get_json()["error"])

        # Non-string date (e.g. 0 or False)
        res3 = self.client.post(
            "/api/expenses",
            json={"title": "Coffee", "amount": "50.00", "category": "Food", "date": False},
        )
        self.assertEqual(res3.status_code, 400)

        # Database-level CHECK constraint verification (direct SQLite insert)
        conn = database.get_connection(self.test_db_path)
        try:
            # 1. Impossible calendar date (Feb 30) rejected by SQLite CHECK constraint
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO expenses (title, amount_paise, category, date) VALUES (?, ?, ?, ?)",
                    ("Direct Check 2026-02-30", 1000, "Food", "2026-02-30"),
                )
            # 2. Non-leap year Feb 29 rejected by SQLite CHECK constraint
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO expenses (title, amount_paise, category, date) VALUES (?, ?, ?, ?)",
                    ("Direct Check 2025-02-29", 1000, "Food", "2025-02-29"),
                )
            # 3. Valid leap year Feb 29 accepted by SQLite CHECK constraint
            conn.execute(
                "INSERT INTO expenses (title, amount_paise, category, date) VALUES (?, ?, ?, ?)",
                ("Direct Check 2024-02-29", 1000, "Food", "2024-02-29"),
            )
            conn.commit()
        finally:
            conn.close()

    # 7. POST omitted date versus explicit blank date
    def test_07_post_omitted_date_vs_blank_date(self):
        # Omitted date -> defaults to today's local date
        res_omitted = self.client.post(
            "/api/expenses",
            json={"title": "Omitted Date", "amount": "100.00", "category": "Food"},
        )
        self.assertEqual(res_omitted.status_code, 201)
        self.assertEqual(res_omitted.get_json()["date"], date.today().isoformat())

        # Explicit blank date -> MUST BE REJECTED with 400!
        res_blank = self.client.post(
            "/api/expenses",
            json={"title": "Blank Date", "amount": "100.00", "category": "Food", "date": ""},
        )
        self.assertEqual(res_blank.status_code, 400)
        self.assertIn("cannot be blank", res_blank.get_json()["error"])

    # 8. PUT missing date rejection
    def test_08_put_missing_date_rejection(self):
        # Create item
        res = self.client.post(
            "/api/expenses",
            json={"title": "Original", "amount": "50.00", "category": "Food"},
        )
        exp_id = res.get_json()["id"]

        # PUT without date -> MUST BE REJECTED (never default to today)
        res_put = self.client.put(
            f"/api/expenses/{exp_id}",
            json={"title": "Updated", "amount": "60.00", "category": "Food"},
        )
        self.assertEqual(res_put.status_code, 400)
        self.assertIn("Date is required", res_put.get_json()["error"])

        # PUT with valid date -> succeeds
        res_put_valid = self.client.put(
            f"/api/expenses/{exp_id}",
            json={"title": "Updated", "amount": "60.00", "category": "Food", "date": "2026-11-20"},
        )
        self.assertEqual(res_put_valid.status_code, 200)
        self.assertEqual(res_put_valid.get_json()["date"], "2026-11-20")

    # 9. Invalid category and date filters
    def test_09_invalid_category_and_date_filters(self):
        # Invalid filter category
        res1 = self.client.get("/api/expenses?category=FakeCategory")
        self.assertEqual(res1.status_code, 400)
        self.assertIn("Filter category must be one of", res1.get_json()["error"])

        # Malformed from_date filter
        res2 = self.client.get("/api/expenses?from_date=2026-99-99")
        self.assertEqual(res2.status_code, 400)
        self.assertIn("not a valid calendar date", res2.get_json()["error"])

        # Malformed to_date filter
        res3 = self.client.get("/api/expenses?to_date=not-a-date")
        self.assertEqual(res3.status_code, 400)

    # 10. Reversed date ranges
    def test_10_reversed_date_ranges(self):
        res = self.client.get("/api/expenses?from_date=2026-11-20&to_date=2026-11-10")
        self.assertEqual(res.status_code, 400)
        self.assertIn("From date cannot be later than To date", res.get_json()["error"])

    # 11. Inclusive date boundaries
    def test_11_inclusive_date_boundaries(self):
        self.client.post(
            "/api/expenses",
            json={"title": "Boundary Start", "amount": "10.00", "category": "Food", "date": "2026-11-01"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Boundary End", "amount": "20.00", "category": "Food", "date": "2026-11-10"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Outside", "amount": "30.00", "category": "Food", "date": "2026-11-11"},
        )

        res = self.client.get("/api/expenses?from_date=2026-11-01&to_date=2026-11-10")
        self.assertEqual(res.status_code, 200)
        titles = [e["title"] for e in res.get_json()]
        self.assertIn("Boundary Start", titles)
        self.assertIn("Boundary End", titles)
        self.assertNotIn("Outside", titles)

    # 12. Combined filters
    def test_12_combined_filters(self):
        self.client.post(
            "/api/expenses",
            json={"title": "Taxi to airport", "amount": "500.00", "category": "Transport", "date": "2026-11-05"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Taxi to office", "amount": "200.00", "category": "Transport", "date": "2026-11-15"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Airport lunch", "amount": "300.00", "category": "Food", "date": "2026-11-05"},
        )

        # Filter: category=Transport AND q=airport AND to_date=2026-11-10
        res = self.client.get("/api/expenses?category=Transport&q=airport&to_date=2026-11-10")
        self.assertEqual(res.status_code, 200)
        items = res.get_json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Taxi to airport")

    # 13. Literal %, _, and ! title searches
    def test_13_literal_search_escaping(self):
        self.client.post(
            "/api/expenses",
            json={"title": "Discount 50% Off", "amount": "50.00", "category": "Shopping"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "item_one", "amount": "25.00", "category": "Shopping"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "itemXone", "amount": "25.00", "category": "Shopping"},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Warning! Danger", "amount": "15.00", "category": "Bills"},
        )

        # Search literal %: matches only "Discount 50% Off"
        res_pct = self.client.get("/api/expenses?q=50%")
        self.assertEqual(len(res_pct.get_json()), 1)
        self.assertEqual(res_pct.get_json()[0]["title"], "Discount 50% Off")

        # Search literal % alone: matches only "Discount 50% Off"
        res_pct_alone = self.client.get("/api/expenses?q=%")
        self.assertEqual(len(res_pct_alone.get_json()), 1)
        self.assertEqual(res_pct_alone.get_json()[0]["title"], "Discount 50% Off")

        # Search literal _: matches only "item_one" (not "itemXone")
        res_und = self.client.get("/api/expenses?q=item_one")
        self.assertEqual(len(res_und.get_json()), 1)
        self.assertEqual(res_und.get_json()[0]["title"], "item_one")

        # Search literal _ alone: matches only "item_one"
        res_und_alone = self.client.get("/api/expenses?q=_")
        self.assertEqual(len(res_und_alone.get_json()), 1)
        self.assertEqual(res_und_alone.get_json()[0]["title"], "item_one")

        # Search literal !: matches only "Warning! Danger"
        res_exc = self.client.get("/api/expenses?q=Warning!")
        self.assertEqual(len(res_exc.get_json()), 1)
        self.assertEqual(res_exc.get_json()[0]["title"], "Warning! Danger")

        # Search literal ! alone: matches only "Warning! Danger"
        res_exc_alone = self.client.get("/api/expenses?q=!")
        self.assertEqual(len(res_exc_alone.get_json()), 1)
        self.assertEqual(res_exc_alone.get_json()[0]["title"], "Warning! Danger")

    # 14. CRUD operations and missing IDs
    def test_14_crud_operations_and_missing_ids(self):
        res = self.client.post(
            "/api/expenses",
            json={"title": "Movie", "amount": "300.00", "category": "Entertainment"},
        )
        exp_id = res.get_json()["id"]

        # Missing PUT ID -> 404
        res_bad_put = self.client.put(
            "/api/expenses/88888",
            json={"title": "Movie", "amount": "300.00", "category": "Entertainment", "date": "2026-11-16"},
        )
        self.assertEqual(res_bad_put.status_code, 404)
        self.assertEqual(res_bad_put.get_json()["code"], "NOT_FOUND")

        # Missing DELETE ID -> 404
        res_bad_del = self.client.delete("/api/expenses/88888")
        self.assertEqual(res_bad_del.status_code, 404)
        self.assertEqual(res_bad_del.get_json()["code"], "NOT_FOUND")

        # Delete real ID -> 200
        res_del = self.client.delete(f"/api/expenses/{exp_id}")
        self.assertEqual(res_del.status_code, 200)

    # 15. Monthly summary accuracy, deterministic order, and filter independence
    def test_15_monthly_summary_accuracy_and_independence(self):
        today = date.today()
        cur_date = today.isoformat()

        # Add expenses across categories
        self.client.post(
            "/api/expenses",
            json={"title": "Groceries", "amount": "500.00", "category": "Food", "date": cur_date},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Fuel", "amount": "500.00", "category": "Transport", "date": cur_date},
        )
        self.client.post(
            "/api/expenses",
            json={"title": "Electricity", "amount": "1000.00", "category": "Bills", "date": cur_date},
        )

        res = self.client.get("/api/summary/current-month")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # Total: 500 + 500 + 1000 = ₹2000 (200,000 paise)
        self.assertEqual(data["total_paise"], 200000)
        self.assertEqual(data["expense_count"], 3)

        # Ordering check: Bills (100,000), then Food and Transport (50,000 each sorted by category ASC)
        breakdown = data["breakdown"]
        self.assertEqual(breakdown[0]["category"], "Bills")
        self.assertEqual(breakdown[0]["total_paise"], 100000)
        # Deterministic secondary order by category ASC: Food before Transport
        self.assertEqual(breakdown[1]["category"], "Food")
        self.assertEqual(breakdown[2]["category"], "Transport")

        # Filter independence: active filter on GET /api/expenses does NOT alter summary
        self.client.get("/api/expenses?category=Bills")
        res_summary_again = self.client.get("/api/summary/current-month")
        self.assertEqual(res_summary_again.get_json()["total_paise"], 200000)

    # 16. Database isolation between tests and real application
    def test_16_database_isolation(self):
        """Verifies that test operations are isolated in a temporary database and do not touch expenses.db."""
        # Insert a unique expense via test client
        unique_title = "Isolated Test Expense Verification 98765"
        res = self.client.post(
            "/api/expenses",
            json={"title": unique_title, "amount": "99.00", "category": "Other", "date": "2026-11-16"},
        )
        self.assertEqual(res.status_code, 201)
        created_id = res.get_json()["id"]

        # 1. Verify item exists in test database
        conn_test = database.get_connection(self.test_db_path)
        try:
            test_row = database.get_expense_by_id(conn_test, created_id)
            self.assertIsNotNone(test_row)
            self.assertEqual(test_row["title"], unique_title)
        finally:
            conn_test.close()

        # 2. Verify default expenses.db is never modified, written to, or created merely to check isolation
        if os.path.exists(database.DEFAULT_DB_PATH):
            # Real database exists in workspace: inspect strictly in read-only URI mode without creating/migrating
            ro_uri = f"file:{os.path.abspath(database.DEFAULT_DB_PATH)}?mode=ro"
            conn_real = sqlite3.connect(ro_uri, uri=True)
            try:
                real_matches = conn_real.execute(
                    "SELECT COUNT(*) FROM expenses WHERE title = ?", (unique_title,)
                ).fetchone()[0]
                self.assertEqual(real_matches, 0)
            finally:
                conn_real.close()
        else:
            # Real database does not exist: verify it remains completely absent
            self.assertFalse(os.path.exists(database.DEFAULT_DB_PATH))

        # Verify environment variable and path isolation
        self.assertEqual(os.environ.get("EXPENSES_DB"), self.test_db_path)
        self.assertNotEqual(self.test_db_path, database.DEFAULT_DB_PATH)

    # 17. Persistence across database reconnect / restart
    def test_17_persistence_across_restart(self):
        res = self.client.post(
            "/api/expenses",
            json={"title": "Durable Rent", "amount": "15000.00", "category": "Bills"},
        )
        exp_id = res.get_json()["id"]

        # Close and reopen new connection
        conn2 = database.get_connection(self.test_db_path)
        try:
            row = database.get_expense_by_id(conn2, exp_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["title"], "Durable Rent")
            self.assertEqual(row["amount_paise"], 1500000)
        finally:
            conn2.close()

    # 18. API payload fidelity with HTML and script-like text
    def test_18_safe_html_input(self):
        """
        Verifies backend data fidelity: strings containing HTML/script tags are stored
        and returned faithfully without server-side corruption, mangling, or stripping.

        Security model / XSS defense:
        The backend acts as an exact, faithful data store. Defense against Cross-Site Scripting (XSS)
        is enforced in the frontend via DOM property assignment (element.textContent = ...),
        which treats all strings strictly as literal text, never executable HTML markup.
        """
        script_title = "<script>alert('xss')</script> & <b>Bold</b>"
        script_note = "<em>Safe</em> & <img src=x onerror=alert(1)>"
        res = self.client.post(
            "/api/expenses",
            json={"title": script_title, "amount": "10.00", "category": "Other", "note": script_note},
        )
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data["title"], script_title)
        self.assertEqual(data["note"], script_note)

        # Confirm persisted exactly as input in SQLite
        conn = database.get_connection(self.test_db_path)
        try:
            row = database.get_expense_by_id(conn, data["id"])
            self.assertIsNotNone(row)
            self.assertEqual(row["title"], script_title)
            self.assertEqual(row["note"], script_note)
        finally:
            conn.close()

    # 19. Deterministic ordering for expenses on the same date
    def test_19_deterministic_ordering_same_date(self):
        same_date = "2026-11-16"
        res1 = self.client.post("/api/expenses", json={"title": "First", "amount": "10.00", "category": "Food", "date": same_date})
        res2 = self.client.post("/api/expenses", json={"title": "Second", "amount": "20.00", "category": "Food", "date": same_date})
        res3 = self.client.post("/api/expenses", json={"title": "Third", "amount": "30.00", "category": "Food", "date": same_date})

        list_res = self.client.get("/api/expenses")
        items = list_res.get_json()
        self.assertEqual(len(items), 3)
        # Deterministic secondary ordering: id DESC (most recently inserted first)
        self.assertEqual(items[0]["title"], "Third")
        self.assertEqual(items[1]["title"], "Second")
        self.assertEqual(items[2]["title"], "First")

    # 20. Empty note acceptance and persistence
    def test_20_empty_note_acceptance(self):
        # Empty string note
        res1 = self.client.post("/api/expenses", json={"title": "No Note String", "amount": "10.00", "category": "Food", "note": ""})
        self.assertEqual(res1.status_code, 201)
        self.assertIsNone(res1.get_json()["note"])

        # Omitted note
        res2 = self.client.post("/api/expenses", json={"title": "Omitted Note", "amount": "20.00", "category": "Food"})
        self.assertEqual(res2.status_code, 201)
        self.assertIsNone(res2.get_json()["note"])

    # 21. Empty month summary displays zero and empty breakdown
    def test_21_empty_month_summary(self):
        # Ensure database has 0 expenses for this test
        res = self.client.get("/api/summary/current-month")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["total_paise"], 0)
        self.assertEqual(data["expense_count"], 0)
        self.assertEqual(data["breakdown"], [])

    # 22. Oversized and out-of-range expense IDs return 404, never 500
    def test_22_oversized_expense_ids(self):
        oversized_id = "99999999999999999999"
        payload = {
            "title": "Valid Title",
            "amount": "100.00",
            "category": "Food",
            "date": "2026-11-16",
        }

        # PUT oversized ID -> must return 404 NOT_FOUND, never 500
        res_put = self.client.put(f"/api/expenses/{oversized_id}", json=payload)
        self.assertEqual(res_put.status_code, 404)
        self.assertEqual(res_put.get_json()["code"], "NOT_FOUND")

        # DELETE oversized ID -> must return 404 NOT_FOUND, never 500
        res_del = self.client.delete(f"/api/expenses/{oversized_id}")
        self.assertEqual(res_del.status_code, 404)
        self.assertEqual(res_del.get_json()["code"], "NOT_FOUND")

    # 23. Unicode validation, embedded NUL rejection, and Malayalam text acceptance
    def test_23_unicode_and_nul_validation(self):
        # 1. Embedded NUL in title -> 400
        res_nul_title = self.client.post(
            "/api/expenses",
            json={"title": "Nul\x00Title", "amount": "10.00", "category": "Food"},
        )
        self.assertEqual(res_nul_title.status_code, 400)
        self.assertIn("NUL characters", res_nul_title.get_json()["error"])

        # 2. Lone surrogate in title -> 400
        res_surr_title = self.client.post(
            "/api/expenses",
            json={"title": "Surrogate\ud800Title", "amount": "10.00", "category": "Food"},
        )
        self.assertEqual(res_surr_title.status_code, 400)
        self.assertIn("invalid Unicode", res_surr_title.get_json()["error"])

        # 3. Embedded NUL in note -> 400
        res_nul_note = self.client.post(
            "/api/expenses",
            json={"title": "Valid Title", "amount": "10.00", "category": "Food", "note": "Bad\x00Note"},
        )
        self.assertEqual(res_nul_note.status_code, 400)
        self.assertIn("NUL characters", res_nul_note.get_json()["error"])

        # 4. Lone surrogate in note -> 400
        res_surr_note = self.client.post(
            "/api/expenses",
            json={"title": "Valid Title", "amount": "10.00", "category": "Food", "note": "Bad\ud800Note"},
        )
        self.assertEqual(res_surr_note.status_code, 400)
        self.assertIn("invalid Unicode", res_surr_note.get_json()["error"])

        # 5. Embedded NUL in search query -> 400
        res_nul_q = self.client.get("/api/expenses?q=search\x00term")
        self.assertEqual(res_nul_q.status_code, 400)
        self.assertIn("NUL characters", res_nul_q.get_json()["error"])

        # 6. Lone surrogate in search query raises ValidationError
        with self.assertRaises(ValidationError) as cm:
            from app import validate_safe_text
            validate_safe_text("search\ud800term", "Search query")
        self.assertIn("invalid Unicode", str(cm.exception))

        # 7. Valid Malayalam text in title, note, and search query -> accepted
        malayalam_title = "പച്ചക്കറി ചന്ത (Vegetable Market)"
        malayalam_note = "ആഴ്ചയിലെ പലചരക്ക് സാധനങ്ങൾ"
        res_mal = self.client.post(
            "/api/expenses",
            json={
                "title": malayalam_title,
                "amount": "350.50",
                "category": "Food",
                "note": malayalam_note,
            },
        )
        self.assertEqual(res_mal.status_code, 201)
        created_data = res_mal.get_json()
        self.assertEqual(created_data["title"], malayalam_title)
        self.assertEqual(created_data["note"], malayalam_note)

        # Search Malayalam text
        res_search_mal = self.client.get("/api/expenses?q=പച്ചക്കറി")
        self.assertEqual(res_search_mal.status_code, 200)
        items = res_search_mal.get_json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], malayalam_title)

    # 24. Filter query isolation and persistence
    def test_24_filter_query_isolation(self):
        # Create expenses
        self.client.post("/api/expenses", json={"title": "Food Item 1", "amount": "10.00", "category": "Food"})
        self.client.post("/api/expenses", json={"title": "Transport Item 1", "amount": "20.00", "category": "Transport"})

        # Active filter for Transport
        res_filter = self.client.get("/api/expenses?category=Transport")
        self.assertEqual(res_filter.status_code, 200)
        self.assertEqual(len(res_filter.get_json()), 1)
        self.assertEqual(res_filter.get_json()[0]["title"], "Transport Item 1")

        # Adding a new Food item succeeds
        res_add = self.client.post("/api/expenses", json={"title": "Food Item 2", "amount": "30.00", "category": "Food"})
        self.assertEqual(res_add.status_code, 201)

        # Active filter for Transport still isolates only Transport
        res_filter_again = self.client.get("/api/expenses?category=Transport")
        self.assertEqual(len(res_filter_again.get_json()), 1)
        self.assertEqual(res_filter_again.get_json()[0]["title"], "Transport Item 1")

    # 25. Application factory automatically initializes database schema
    def test_25_app_factory_initializes_db(self):
        import tempfile
        with tempfile.TemporaryDirectory() as factory_temp:
            factory_db = os.path.join(factory_temp, "factory_auto_init.db")
            self.assertFalse(os.path.exists(factory_db))

            # Calling create_app initializes the database schema automatically
            test_app = create_app({"TESTING": True, "DATABASE": factory_db})
            self.assertTrue(os.path.exists(factory_db))

            # Verify schema was created properly
            conn = sqlite3.connect(factory_db)
            try:
                table_row = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='expenses'"
                ).fetchone()
                self.assertIsNotNone(table_row)
                self.assertIn("amount_paise", table_row[0])
                self.assertIn("date(date", table_row[0])
            finally:
                conn.close()

    # 26. Importing app in an environment without expenses.db does not create expenses.db
    def test_26_import_isolation_without_default_db(self):
        """Verifies that importing app in a clean directory with EXPENSES_DB override does not create expenses.db."""
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as clean_dir:
            default_db_probe = os.path.join(clean_dir, "expenses.db")
            isolated_db = os.path.join(clean_dir, "isolated.db")

            code = (
                "import os, sys\n"
                "from pathlib import Path\n"
                "app_dir = Path(r'" + str(database.BASE_DIR) + "')\n"
                "sys.path.insert(0, str(app_dir))\n"
                "import app\n"
                "assert not os.path.exists('expenses.db'), 'expenses.db was created in working directory!'\n"
            )
            env = os.environ.copy()
            env["EXPENSES_DB"] = isolated_db
            res = subprocess.run(
                [sys.executable, "-c", code],
                cwd=clean_dir,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0, f"Subprocess failed: {res.stderr}")
            self.assertFalse(os.path.exists(default_db_probe))


if __name__ == "__main__":
    unittest.main()
