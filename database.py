"""Database access layer for Personal Expense Tracker using SQLite 3."""

import os
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

ALLOWED_CATEGORIES: Tuple[str, ...] = (
    "Food",
    "Transport",
    "Shopping",
    "Bills",
    "Entertainment",
    "Other",
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = str(BASE_DIR / "expenses.db")
MAX_SQLITE_INT = 9223372036854775807


def get_db_path(override_path: Optional[str] = None) -> str:
    """Returns the effective database path, checking EXPENSES_DB environment variable."""
    if override_path is not None:
        return override_path
    return os.environ.get("EXPENSES_DB", DEFAULT_DB_PATH)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates a new SQLite connection with Row factory enabled."""
    path = get_db_path(db_path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database schema with CHECK constraints generated from trusted constants."""
    categories_quoted = ", ".join(f"'{c}'" for c in ALLOWED_CATEGORIES)
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 100),
        amount_paise INTEGER NOT NULL CHECK (amount_paise > 0 AND amount_paise <= 1000000000),
        category TEXT NOT NULL CHECK (category IN ({categories_quoted})),
        date TEXT NOT NULL CHECK (length(date) = 10 AND date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(date, '+0 days') = date),
        note TEXT NULL CHECK (note IS NULL OR length(note) <= 500)
    );
    """
    conn = get_connection(db_path)
    try:
        conn.execute(create_table_sql)
        # Check if existing table needs date check constraint upgrade
        cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='expenses'")
        row = cursor.fetchone()
        if row and "date(date" not in row[0]:
            conn.execute("PRAGMA foreign_keys=off")
            conn.execute(f"""
            CREATE TABLE expenses_upgrade (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL CHECK (length(trim(title)) > 0 AND length(title) <= 100),
                amount_paise INTEGER NOT NULL CHECK (amount_paise > 0 AND amount_paise <= 1000000000),
                category TEXT NOT NULL CHECK (category IN ({categories_quoted})),
                date TEXT NOT NULL CHECK (length(date) = 10 AND date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' AND date(date, '+0 days') = date),
                note TEXT NULL CHECK (note IS NULL OR length(note) <= 500)
            );
            """)
            conn.execute("INSERT INTO expenses_upgrade SELECT * FROM expenses")
            conn.execute("DROP TABLE expenses")
            conn.execute("ALTER TABLE expenses_upgrade RENAME TO expenses")
        conn.commit()
    finally:
        conn.close()


def escape_like(query: str) -> str:
    """Escapes !, %, and _ for SQL LIKE queries with ESCAPE '!'."""
    return query.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def insert_expense(
    conn: sqlite3.Connection,
    title: str,
    amount_paise: int,
    category: str,
    date_str: str,
    note: Optional[str] = None,
) -> int:
    """Inserts a new expense and returns the generated row id."""
    sql = """
    INSERT INTO expenses (title, amount_paise, category, date, note)
    VALUES (?, ?, ?, ?, ?)
    """
    cursor = conn.execute(
        sql, (title.strip(), amount_paise, category, date_str, note)
    )
    return cursor.lastrowid


def get_expense_by_id(
    conn: sqlite3.Connection, expense_id: int
) -> Optional[Dict[str, Any]]:
    """Retrieves an expense by ID or returns None."""
    if not isinstance(expense_id, int) or expense_id < 1 or expense_id > MAX_SQLITE_INT:
        return None
    try:
        sql = "SELECT id, title, amount_paise, category, date, note FROM expenses WHERE id = ?"
        row = conn.execute(sql, (expense_id,)).fetchone()
        if row:
            return dict(row)
    except (OverflowError, sqlite3.DataError):
        return None
    return None


def update_expense(
    conn: sqlite3.Connection,
    expense_id: int,
    title: str,
    amount_paise: int,
    category: str,
    date_str: str,
    note: Optional[str] = None,
) -> bool:
    """Updates an expense by ID. Returns True if record existed and was updated."""
    if not isinstance(expense_id, int) or expense_id < 1 or expense_id > MAX_SQLITE_INT:
        return False
    try:
        sql = """
        UPDATE expenses
        SET title = ?, amount_paise = ?, category = ?, date = ?, note = ?
        WHERE id = ?
        """
        cursor = conn.execute(
            sql, (title.strip(), amount_paise, category, date_str, note, expense_id)
        )
        return cursor.rowcount > 0
    except (OverflowError, sqlite3.DataError):
        return False


def delete_expense(conn: sqlite3.Connection, expense_id: int) -> bool:
    """Deletes an expense by ID. Returns True if record was found and deleted."""
    if not isinstance(expense_id, int) or expense_id < 1 or expense_id > MAX_SQLITE_INT:
        return False
    try:
        sql = "DELETE FROM expenses WHERE id = ?"
        cursor = conn.execute(sql, (expense_id,))
        return cursor.rowcount > 0
    except (OverflowError, sqlite3.DataError):
        return False


def query_expenses(
    conn: sqlite3.Connection,
    category: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    q: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Queries expenses with multi-criteria filtering, sorted by date DESC, id DESC."""
    sql = "SELECT id, title, amount_paise, category, date, note FROM expenses WHERE 1=1"
    params: List[Any] = []

    if category:
        sql += " AND category = ?"
        params.append(category)
    if from_date:
        sql += " AND date >= ?"
        params.append(from_date)
    if to_date:
        sql += " AND date <= ?"
        params.append(to_date)
    if q and q.strip():
        sql += " AND title LIKE ? ESCAPE '!'"
        params.append(f"%{escape_like(q.strip())}%")

    sql += " ORDER BY date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_monthly_summary(
    conn: sqlite3.Connection,
    first_day_cur: str,
    first_day_next: str,
) -> Dict[str, Any]:
    """
    Calculates total spending, count, and category breakdown for a date window.
    Ordering is deterministic: total_paise DESC, category ASC.
    """
    total_sql = """
    SELECT COALESCE(SUM(amount_paise), 0) AS total_paise, COUNT(*) AS count
    FROM expenses
    WHERE date >= ? AND date < ?
    """

    breakdown_sql = """
    SELECT category, SUM(amount_paise) AS total_paise, COUNT(*) AS count
    FROM expenses
    WHERE date >= ? AND date < ?
    GROUP BY category
    ORDER BY total_paise DESC, category ASC
    """

    total_row = conn.execute(total_sql, (first_day_cur, first_day_next)).fetchone()
    breakdown_rows = conn.execute(
        breakdown_sql, (first_day_cur, first_day_next)
    ).fetchall()

    total_paise = total_row["total_paise"] if total_row else 0
    expense_count = total_row["count"] if total_row else 0

    breakdown = [
        {
            "category": r["category"],
            "total_paise": r["total_paise"],
            "count": r["count"],
        }
        for r in breakdown_rows
    ]

    return {
        "total_paise": total_paise,
        "expense_count": expense_count,
        "breakdown": breakdown,
    }
