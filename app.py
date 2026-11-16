"""Flask application for Personal Expense Tracker."""

import os
import re
import sqlite3
import traceback
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

from flask import Flask, request, jsonify, send_from_directory, g

import database

BASE_DIR = Path(__file__).resolve().parent
DATE_REGEX = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
AMOUNT_REGEX = re.compile(r"^[0-9]{1,8}(\.[0-9]{1,2})?$")


class ValidationError(Exception):
    """Custom exception for validation errors."""

    def __init__(self, message: str, code: str = "INVALID_INPUT"):
        super().__init__(message)
        self.message = message
        self.code = code


def validate_safe_text(value: str, field_name: str) -> str:
    """
    Validates that a string does not contain NUL bytes (\x00)
    and can be properly encoded to UTF-8 without lone surrogates.
    """
    if "\x00" in value:
        raise ValidationError(f"{field_name} cannot contain embedded NUL characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValidationError(
            f"{field_name} contains invalid Unicode characters (surrogates not permitted)"
        )
    return value


def validate_title(value: Any) -> str:
    """Validates that title is a string, non-empty after trimming, and <= 100 chars."""
    if not isinstance(value, str):
        raise ValidationError("Title must be a string")
    validate_safe_text(value, "Title")
    t = value.strip()
    if not t:
        raise ValidationError("Title is required and cannot be blank")
    if len(t) > 100:
        raise ValidationError("Title cannot exceed 100 characters")
    return t


def parse_amount_to_paise(value: Any) -> int:
    """
    Validates amount as a JSON string using exact regex and Decimal.
    Rejects floats, integers, non-strings, zero, negative, and values > ₹10,000,000.
    """
    if not isinstance(value, str):
        raise ValidationError("Amount must be a decimal string (e.g. '12.50')")
    val = value.strip()
    if not val:
        raise ValidationError("Amount cannot be empty")
    if not AMOUNT_REGEX.fullmatch(val):
        raise ValidationError(
            "Amount must be a valid positive decimal string with up to 2 decimal places"
        )
    try:
        d = Decimal(val)
    except InvalidOperation:
        raise ValidationError("Amount must be a valid number")
    if d <= Decimal("0"):
        raise ValidationError("Amount must be greater than zero")
    if d > Decimal("10000000"):
        raise ValidationError("Amount cannot exceed ₹10,000,000")

    return int((d * Decimal(100)).to_integral_exact())


def validate_category(value: Any, field_name: str = "Category") -> str:
    """Validates that category is a string and one of the permitted categories."""
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    c = value.strip()
    if c not in database.ALLOWED_CATEGORIES:
        allowed = ", ".join(database.ALLOWED_CATEGORIES)
        raise ValidationError(f"{field_name} must be one of: {allowed}")
    return c


def validate_note(value: Any) -> Optional[str]:
    """Validates optional note: nullable, string, max 500 chars after trim."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("Note must be a string")
    validate_safe_text(value, "Note")
    n = value.strip()
    if not n:
        return None
    if len(n) > 500:
        raise ValidationError("Note cannot exceed 500 characters")
    return n


def validate_date_field(
    value: Any,
    field_name: str = "Date",
    is_post: bool = False,
    is_omitted: bool = False,
) -> str:
    """
    Validates calendar date.
    - Omitted date on POST defaults to local today.
    - Explicit blank, non-string, malformed, or impossible calendar dates are rejected.
    - PUT requires an explicit valid date.
    """
    if is_omitted and is_post:
        return date.today().isoformat()

    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string in YYYY-MM-DD format")

    val = value.strip()
    if not val:
        raise ValidationError(f"{field_name} cannot be blank")

    if not DATE_REGEX.fullmatch(val):
        raise ValidationError(f"{field_name} must be in YYYY-MM-DD format")

    try:
        parsed = datetime.strptime(val, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"{field_name} is not a valid calendar date")

    return parsed.isoformat()


def get_current_month_bounds() -> Tuple[str, str, str]:
    """Computes first day of current month and first day of next month via Python date arithmetic."""
    today = date.today()
    month_label = today.strftime("%B %Y")
    first_day_cur = date(today.year, today.month, 1).isoformat()
    if today.month == 12:
        first_day_next = date(today.year + 1, 1, 1).isoformat()
    else:
        first_day_next = date(today.year, today.month + 1, 1).isoformat()
    return first_day_cur, first_day_next, month_label


def create_app(test_config: Optional[Dict[str, Any]] = None) -> Flask:
    """Flask application factory."""
    static_dir = str(BASE_DIR / "static")
    app = Flask(__name__, static_folder=static_dir, static_url_path="")

    if test_config:
        app.config.update(test_config)

    # Initialize database schema for configured database target
    target_db = app.config.get("DATABASE") or database.get_db_path()
    database.init_db(target_db)

    # Database connection lifecycle per request
    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            db_path = app.config.get("DATABASE") or database.get_db_path()
            g.db = database.get_connection(db_path)
        return g.db

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    # --- Routes ---

    @app.route("/")
    def index():
        """Serves the single-page frontend."""
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/api/expenses", methods=["GET"])
    def get_expenses():
        """Lists expenses with optional filtering, sorted by date DESC, id DESC."""
        raw_category = request.args.get("category")
        raw_from_date = request.args.get("from_date")
        raw_to_date = request.args.get("to_date")
        raw_q = request.args.get("q")

        filter_category: Optional[str] = None
        if raw_category is not None:
            if raw_category.strip():
                filter_category = validate_category(
                    raw_category, field_name="Filter category"
                )

        parsed_from: Optional[str] = None
        if raw_from_date is not None:
            if raw_from_date.strip():
                parsed_from = validate_date_field(
                    raw_from_date,
                    field_name="From date",
                    is_post=False,
                    is_omitted=False,
                )

        parsed_to: Optional[str] = None
        if raw_to_date is not None:
            if raw_to_date.strip():
                parsed_to = validate_date_field(
                    raw_to_date,
                    field_name="To date",
                    is_post=False,
                    is_omitted=False,
                )

        if parsed_from and parsed_to and parsed_from > parsed_to:
            raise ValidationError("From date cannot be later than To date")

        filter_q: Optional[str] = None
        if raw_q is not None:
            validate_safe_text(raw_q, "Search query")
            if raw_q.strip():
                filter_q = raw_q.strip()

        conn = get_db()
        expenses = database.query_expenses(
            conn=conn,
            category=filter_category,
            from_date=parsed_from,
            to_date=parsed_to,
            q=filter_q,
        )
        return jsonify(expenses), 200

    @app.route("/api/expenses", methods=["POST"])
    def create_expense():
        """Creates a new expense record."""
        if not request.is_json:
            return (
                jsonify(
                    {
                        "error": "Content-Type must be application/json",
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                    }
                ),
                415,
            )

        try:
            data = request.get_json(silent=False)
        except Exception:
            return (
                jsonify(
                    {
                        "error": "Malformed JSON in request body",
                        "code": "MALFORMED_JSON",
                    }
                ),
                400,
            )

        if not isinstance(data, dict):
            return (
                jsonify(
                    {
                        "error": "Request body must be a JSON object",
                        "code": "INVALID_INPUT",
                    }
                ),
                400,
            )

        title = validate_title(data.get("title"))
        amount_paise = parse_amount_to_paise(data.get("amount"))
        category = validate_category(data.get("category"))

        # POST: omitted date defaults to today; explicit blank or invalid date rejected
        is_omitted = "date" not in data
        date_str = validate_date_field(
            data.get("date"),
            field_name="Date",
            is_post=True,
            is_omitted=is_omitted,
        )
        note = validate_note(data.get("note"))

        conn = get_db()
        new_id = database.insert_expense(
            conn=conn,
            title=title,
            amount_paise=amount_paise,
            category=category,
            date_str=date_str,
            note=note,
        )
        conn.commit()

        created = {
            "id": new_id,
            "title": title,
            "amount_paise": amount_paise,
            "category": category,
            "date": date_str,
            "note": note,
        }
        return jsonify(created), 201

    @app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
    def update_expense_endpoint(expense_id: int):
        """Updates an existing expense record."""
        if expense_id < 1 or expense_id > database.MAX_SQLITE_INT:
            return (
                jsonify(
                    {
                        "error": f"Expense with ID {expense_id} not found",
                        "code": "NOT_FOUND",
                    }
                ),
                404,
            )

        if not request.is_json:
            return (
                jsonify(
                    {
                        "error": "Content-Type must be application/json",
                        "code": "UNSUPPORTED_MEDIA_TYPE",
                    }
                ),
                415,
            )

        try:
            data = request.get_json(silent=False)
        except Exception:
            return (
                jsonify(
                    {
                        "error": "Malformed JSON in request body",
                        "code": "MALFORMED_JSON",
                    }
                ),
                400,
            )

        if not isinstance(data, dict):
            return (
                jsonify(
                    {
                        "error": "Request body must be a JSON object",
                        "code": "INVALID_INPUT",
                    }
                ),
                400,
            )

        title = validate_title(data.get("title"))
        amount_paise = parse_amount_to_paise(data.get("amount"))
        category = validate_category(data.get("category"))

        # PUT requires a valid date; never defaults to today
        if "date" not in data:
            raise ValidationError("Date is required for update")
        date_str = validate_date_field(
            data.get("date"),
            field_name="Date",
            is_post=False,
            is_omitted=False,
        )
        note = validate_note(data.get("note"))

        conn = get_db()
        updated = database.update_expense(
            conn=conn,
            expense_id=expense_id,
            title=title,
            amount_paise=amount_paise,
            category=category,
            date_str=date_str,
            note=note,
        )
        if not updated:
            return (
                jsonify(
                    {
                        "error": f"Expense with ID {expense_id} not found",
                        "code": "NOT_FOUND",
                    }
                ),
                404,
            )
        conn.commit()

        result = {
            "id": expense_id,
            "title": title,
            "amount_paise": amount_paise,
            "category": category,
            "date": date_str,
            "note": note,
        }
        return jsonify(result), 200

    @app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
    def delete_expense_endpoint(expense_id: int):
        """Deletes an expense record."""
        if expense_id < 1 or expense_id > database.MAX_SQLITE_INT:
            return (
                jsonify(
                    {
                        "error": f"Expense with ID {expense_id} not found",
                        "code": "NOT_FOUND",
                    }
                ),
                404,
            )

        conn = get_db()
        deleted = database.delete_expense(conn=conn, expense_id=expense_id)
        if not deleted:
            return (
                jsonify(
                    {
                        "error": f"Expense with ID {expense_id} not found",
                        "code": "NOT_FOUND",
                    }
                ),
                404,
            )
        conn.commit()
        return jsonify({"success": True}), 200

    @app.route("/api/summary/current-month", methods=["GET"])
    def get_current_month_summary():
        """Calculates monthly total spending, count, and category breakdown independently of filters."""
        first_day_cur, first_day_next, month_label = get_current_month_bounds()
        conn = get_db()
        summary = database.get_monthly_summary(conn, first_day_cur, first_day_next)
        response_data = {
            "month": month_label,
            "total_paise": summary["total_paise"],
            "expense_count": summary["expense_count"],
            "breakdown": summary["breakdown"],
        }
        return jsonify(response_data), 200

    # --- Error Handlers ---

    @app.errorhandler(ValidationError)
    def handle_validation_error(e: ValidationError):
        return jsonify({"error": e.message, "code": e.code}), 400

    @app.errorhandler(sqlite3.IntegrityError)
    def handle_integrity_error(e):
        app.logger.warning("Database IntegrityError: %s", str(e))
        return (
            jsonify(
                {
                    "error": "Database constraint violation",
                    "code": "INVALID_INPUT",
                }
            ),
            400,
        )

    @app.errorhandler(400)
    def handle_bad_request(e):
        return (
            jsonify(
                {
                    "error": getattr(e, "description", "Bad request"),
                    "code": "INVALID_INPUT",
                }
            ),
            400,
        )

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "Resource not found", "code": "NOT_FOUND"}), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return (
            jsonify(
                {
                    "error": "Method not allowed on this endpoint",
                    "code": "METHOD_NOT_ALLOWED",
                }
            ),
            405,
        )

    @app.errorhandler(415)
    def handle_unsupported_media_type(e):
        return (
            jsonify(
                {
                    "error": "Content-Type must be application/json",
                    "code": "UNSUPPORTED_MEDIA_TYPE",
                }
            ),
            415,
        )

    @app.errorhandler(500)
    def handle_internal_server_error(e):
        app.logger.error("Internal Server Error: %s", traceback.format_exc())
        return (
            jsonify(
                {
                    "error": "An unexpected server error occurred",
                    "code": "INTERNAL_SERVER_ERROR",
                }
            ),
            500,
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
