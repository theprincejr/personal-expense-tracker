/**
 * Frontend JavaScript for Personal Expense Tracker
 * Communicates with Flask JSON API via fetch.
 */

// Global State
let currentExpenses = [];
let bannerTimeout = null;

// DOM Elements
const form = document.getElementById("expense-form");
const formTitle = document.getElementById("form-title");
const formModeBadge = document.getElementById("form-mode-badge");
const expenseIdInput = document.getElementById("expense-id");
const titleInput = document.getElementById("expense-title");
const amountInput = document.getElementById("expense-amount");
const categoryInput = document.getElementById("expense-category");
const dateInput = document.getElementById("expense-date");
const noteInput = document.getElementById("expense-note");
const submitBtn = document.getElementById("submit-btn");
const cancelEditBtn = document.getElementById("cancel-edit-btn");

const banner = document.getElementById("notification-banner");

// Summary Elements
const summaryMonthTitle = document.getElementById("summary-month-title");
const summaryTotalAmount = document.getElementById("summary-total-amount");
const summaryExpenseCount = document.getElementById("summary-expense-count");
const summaryBreakdownContainer = document.getElementById("summary-breakdown-container");

// Filter Elements
const filterQ = document.getElementById("filter-q");
const filterCategory = document.getElementById("filter-category");
const filterFromDate = document.getElementById("filter-from-date");
const filterToDate = document.getElementById("filter-to-date");
const resetFiltersBtn = document.getElementById("reset-filters-btn");

// Table Elements
const expensesTbody = document.getElementById("expenses-tbody");
const expensesCountBadge = document.getElementById("expenses-count-badge");
const tableEmptyState = document.getElementById("table-empty-state");
const emptyStateTitle = document.getElementById("empty-state-title");
const emptyStateDesc = document.getElementById("empty-state-desc");

// --- Helper Functions ---

/**
 * Returns today's date formatted as YYYY-MM-DD in the user's local timezone.
 * Avoids toISOString().slice(0, 10) which returns UTC and causes timezone drift.
 */
function getLocalTodayISO() {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

/**
 * Formats integer paise into a clean Indian Rupee string without floating-point math errors.
 */
function formatPaiseToINR(paise) {
    if (typeof paise !== "number" || isNaN(paise)) return "₹0.00";
    const rupees = Math.floor(paise / 100);
    const remPaise = paise % 100;
    return "₹" + rupees.toLocaleString("en-IN") + "." + String(remPaise).padStart(2, "0");
}

/**
 * Converts integer paise into a standard decimal string (e.g. 1250 -> "12.50") for form inputs.
 */
function paiseToDecimalString(paise) {
    if (typeof paise !== "number" || isNaN(paise)) return "";
    const rupees = Math.floor(paise / 100);
    const remPaise = paise % 100;
    return `${rupees}.${String(remPaise).padStart(2, "0")}`;
}

/**
 * Shows an accessible notification banner.
 */
function showBanner(message, type = "success") {
    if (bannerTimeout) clearTimeout(bannerTimeout);

    banner.className = `notification-banner ${type}`;
    banner.textContent = message;

    bannerTimeout = setTimeout(() => {
        banner.className = "notification-banner hidden";
        banner.textContent = "";
    }, 4500);
}

// --- Data Loading Functions ---

// Request Sequencing & Cancellation State
let activeExpensesAbortController = null;
let activeExpenseRequestId = 0;

let activeSummaryAbortController = null;
let activeSummaryRequestId = 0;

/**
 * Loads and renders expenses based on current filter values.
 * Uses AbortController and request sequencing to prevent stale responses
 * from overwriting newer search results.
 */
async function loadExpenses() {
    if (activeExpensesAbortController) {
        activeExpensesAbortController.abort();
    }
    activeExpensesAbortController = new AbortController();
    const { signal } = activeExpensesAbortController;
    const currentRequestId = ++activeExpenseRequestId;

    const params = new URLSearchParams();

    const q = filterQ.value.trim();
    const category = filterCategory.value;
    const fromDate = filterFromDate.value;
    const toDate = filterToDate.value;

    if (q) params.set("q", q);
    if (category) params.set("category", category);
    if (fromDate) params.set("from_date", fromDate);
    if (toDate) params.set("to_date", toDate);

    try {
        const response = await fetch(`/api/expenses?${params.toString()}`, { signal });
        if (currentRequestId !== activeExpenseRequestId) return;

        const data = await response.json();
        if (currentRequestId !== activeExpenseRequestId) return;

        if (!response.ok) {
            renderExpensesError(data.error || "Failed to load expenses");
            showBanner(data.error || "Failed to load expenses", "error");
            return;
        }

        currentExpenses = data;
        renderExpensesTable(currentExpenses);
    } catch (err) {
        if (err.name === "AbortError") {
            // Superseded by newer request; silently ignore
            return;
        }
        if (currentRequestId !== activeExpenseRequestId) return;

        renderExpensesError("Network error while loading expenses");
        showBanner("Network error while loading expenses", "error");
    }
}

/**
 * Renders a visible error state in the expense table card when loading fails.
 * Clears stale rows so users do not mistake previous results for current filter matches.
 */
function renderExpensesError(errorMessage) {
    expensesTbody.innerHTML = "";
    currentExpenses = [];
    expensesCountBadge.textContent = "Error";
    expensesCountBadge.className = "badge badge-neutral";

    tableEmptyState.classList.remove("hidden");
    const emptyIcon = tableEmptyState.querySelector(".empty-icon");
    if (emptyIcon) emptyIcon.textContent = "⚠️";
    emptyStateTitle.textContent = "Failed to load expenses";
    emptyStateDesc.textContent = errorMessage;
}

/**
 * Loads the current month summary independently of active list filters.
 * Uses request sequencing to prevent stale responses and shows an explicit error state on failure.
 */
async function loadMonthlySummary() {
    if (activeSummaryAbortController) {
        activeSummaryAbortController.abort();
    }
    activeSummaryAbortController = new AbortController();
    const { signal } = activeSummaryAbortController;
    const currentRequestId = ++activeSummaryRequestId;

    try {
        const response = await fetch("/api/summary/current-month", { signal });
        if (currentRequestId !== activeSummaryRequestId) return;

        const data = await response.json();
        if (currentRequestId !== activeSummaryRequestId) return;

        if (!response.ok) {
            renderSummaryError("Summary data unavailable");
            return;
        }

        summaryMonthTitle.textContent = `${data.month} Summary`;
        summaryTotalAmount.textContent = formatPaiseToINR(data.total_paise);
        summaryExpenseCount.textContent = data.expense_count;

        renderSummaryBreakdown(data.breakdown);
    } catch (err) {
        if (err.name === "AbortError") return;
        if (currentRequestId !== activeSummaryRequestId) return;
        renderSummaryError("Summary temporarily unavailable");
    }
}

/**
 * Displays a visible error state in the monthly summary card on failure.
 * Clears outdated totals so they cannot be mistaken for current values.
 */
function renderSummaryError(message) {
    summaryMonthTitle.textContent = "Current Month Summary";
    summaryTotalAmount.textContent = "Unavailable";
    summaryExpenseCount.textContent = "—";
    summaryBreakdownContainer.innerHTML = "";
    const hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = `⚠️ ${message}.`;
    summaryBreakdownContainer.appendChild(hint);
}

// --- Rendering Functions ---

/**
 * Safely renders the expenses table using DOM methods (prevents XSS).
 */
function renderExpensesTable(expenses) {
    expensesTbody.innerHTML = "";

    expensesCountBadge.textContent = `${expenses.length} ${expenses.length === 1 ? "entry" : "entries"}`;

    if (expenses.length === 0) {
        tableEmptyState.classList.remove("hidden");
        const emptyIcon = tableEmptyState.querySelector(".empty-icon");
        if (emptyIcon) emptyIcon.textContent = "📝";
        const hasFilters = filterQ.value.trim() || filterCategory.value || filterFromDate.value || filterToDate.value;
        if (hasFilters) {
            emptyStateTitle.textContent = "No matching expenses";
            emptyStateDesc.textContent = "No expenses match your search or filter criteria. Try resetting filters.";
        } else {
            emptyStateTitle.textContent = "No expenses recorded yet";
            emptyStateDesc.textContent = "Add your first expense using the form above!";
        }
        return;
    }

    tableEmptyState.classList.add("hidden");

    expenses.forEach((expense) => {
        const tr = document.createElement("tr");

        // Date cell
        const dateTd = document.createElement("td");
        dateTd.textContent = expense.date;
        tr.appendChild(dateTd);

        // Title cell
        const titleTd = document.createElement("td");
        titleTd.textContent = expense.title;
        tr.appendChild(titleTd);

        // Category cell
        const catTd = document.createElement("td");
        const catBadge = document.createElement("span");
        catBadge.className = `cat-badge cat-${expense.category}`;
        catBadge.textContent = expense.category;
        catTd.appendChild(catBadge);
        tr.appendChild(catTd);

        // Amount cell
        const amountTd = document.createElement("td");
        amountTd.className = "text-right amount-cell";
        amountTd.textContent = formatPaiseToINR(expense.amount_paise);
        tr.appendChild(amountTd);

        // Note cell
        const noteTd = document.createElement("td");
        noteTd.className = "note-cell";
        noteTd.textContent = expense.note || "—";
        if (expense.note) noteTd.title = expense.note;
        tr.appendChild(noteTd);

        // Actions cell
        const actionsTd = document.createElement("td");
        actionsTd.className = "actions-cell";

        const editBtn = document.createElement("button");
        editBtn.className = "btn btn-edit-outline";
        editBtn.textContent = "Edit";
        editBtn.addEventListener("click", () => setEditMode(expense));
        actionsTd.appendChild(editBtn);

        const deleteBtn = document.createElement("button");
        deleteBtn.className = "btn btn-danger-outline";
        deleteBtn.textContent = "Delete";
        deleteBtn.addEventListener("click", () => handleDeleteExpense(expense));
        actionsTd.appendChild(deleteBtn);

        tr.appendChild(actionsTd);

        expensesTbody.appendChild(tr);
    });
}

/**
 * Renders category breakdown chips in the monthly summary card.
 */
function renderSummaryBreakdown(breakdown) {
    summaryBreakdownContainer.innerHTML = "";

    if (!breakdown || breakdown.length === 0) {
        const hint = document.createElement("p");
        hint.className = "empty-hint";
        hint.textContent = "No expenses recorded for this month yet.";
        summaryBreakdownContainer.appendChild(hint);
        return;
    }

    breakdown.forEach((item) => {
        const chip = document.createElement("div");
        chip.className = "category-chip";

        const nameSpan = document.createElement("span");
        nameSpan.className = "category-chip-name";
        nameSpan.textContent = item.category;

        const countSpan = document.createElement("span");
        countSpan.className = "category-chip-count";
        countSpan.textContent = `(${item.count})`;

        const amountSpan = document.createElement("span");
        amountSpan.className = "category-chip-amount";
        amountSpan.textContent = formatPaiseToINR(item.total_paise);

        chip.appendChild(nameSpan);
        chip.appendChild(countSpan);
        chip.appendChild(amountSpan);

        summaryBreakdownContainer.appendChild(chip);
    });
}

// --- Form State Management ---

/**
 * Switches the single unified form into Edit Mode.
 */
function setEditMode(expense) {
    expenseIdInput.value = expense.id;
    titleInput.value = expense.title;
    amountInput.value = paiseToDecimalString(expense.amount_paise);
    categoryInput.value = expense.category;
    dateInput.value = expense.date;
    noteInput.value = expense.note || "";

    formTitle.textContent = `Edit Expense #${expense.id}`;
    formModeBadge.textContent = "Edit Mode";
    formModeBadge.className = "badge badge-edit";
    submitBtn.textContent = "Update Expense";
    cancelEditBtn.classList.remove("hidden");

    form.scrollIntoView({ behavior: "smooth", block: "start" });
    titleInput.focus();
}

/**
 * Resets the single unified form back to Add Mode.
 */
function resetFormToAddMode() {
    form.reset();
    expenseIdInput.value = "";
    dateInput.value = getLocalTodayISO();

    formTitle.textContent = "Add Expense";
    formModeBadge.textContent = "Add Mode";
    formModeBadge.className = "badge badge-add";
    submitBtn.textContent = "Add Expense";
    cancelEditBtn.classList.add("hidden");
}

// --- Event Handlers ---

/**
 * Handles Add/Edit form submission.
 */
form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const title = titleInput.value.trim();
    const amountStr = amountInput.value.trim();
    const category = categoryInput.value;
    const dateVal = dateInput.value;
    const note = noteInput.value.trim();
    const expenseId = expenseIdInput.value;

    // Client-side quick check
    if (!title) {
        showBanner("Please enter an expense title.", "error");
        titleInput.focus();
        return;
    }
    if (!amountStr) {
        showBanner("Please enter an amount.", "error");
        amountInput.focus();
        return;
    }
    if (!category) {
        showBanner("Please select a category.", "error");
        categoryInput.focus();
        return;
    }
    if (!dateVal) {
        showBanner("Please enter a valid date.", "error");
        dateInput.focus();
        return;
    }

    const payload = {
        title: title,
        amount: amountStr, // Sent as decimal string
        category: category,
        date: dateVal,
        note: note ? note : null,
    };

    const isEdit = Boolean(expenseId);
    const url = isEdit ? `/api/expenses/${expenseId}` : "/api/expenses";
    const method = isEdit ? "PUT" : "POST";

    submitBtn.disabled = true;

    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        const data = await response.json();

        if (!response.ok) {
            showBanner(data.error || "Failed to save expense", "error");
            submitBtn.disabled = false;
            return;
        }

        showBanner(isEdit ? "Expense updated successfully!" : "Expense added successfully!", "success");
        resetFormToAddMode();
        // Preserves active filters across Add, Edit, and Delete operations
        await Promise.all([loadExpenses(), loadMonthlySummary()]);
    } catch (err) {
        showBanner("Network error while saving expense.", "error");
    } finally {
        submitBtn.disabled = false;
    }
});

/**
 * Handles Edit cancellation.
 */
cancelEditBtn.addEventListener("click", () => {
    resetFormToAddMode();
    showBanner("Edit cancelled.", "success");
});

/**
 * Handles expense deletion with native confirm dialog.
 */
async function handleDeleteExpense(expense) {
    const confirmed = window.confirm(`Are you sure you want to delete "${expense.title}"?`);
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/expenses/${expense.id}`, {
            method: "DELETE",
        });

        const data = await response.json();

        if (!response.ok) {
            showBanner(data.error || "Failed to delete expense", "error");
            return;
        }

        showBanner(`Deleted "${expense.title}".`, "success");

        // If the deleted expense was being edited, reset form
        if (expenseIdInput.value === String(expense.id)) {
            resetFormToAddMode();
        }

        await Promise.all([loadExpenses(), loadMonthlySummary()]);
    } catch (err) {
        showBanner("Network error while deleting expense.", "error");
    }
}

// --- Filter Event Listeners ---

let searchDebounceTimer = null;
filterQ.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(loadExpenses, 250);
});

filterCategory.addEventListener("change", loadExpenses);
filterFromDate.addEventListener("change", loadExpenses);
filterToDate.addEventListener("change", loadExpenses);

resetFiltersBtn.addEventListener("click", () => {
    filterQ.value = "";
    filterCategory.value = "";
    filterFromDate.value = "";
    filterToDate.value = "";
    loadExpenses();
    showBanner("Filters reset.", "success");
});

// --- Initial Page Load ---

document.addEventListener("DOMContentLoaded", () => {
    // Default form date to today's local date
    dateInput.value = getLocalTodayISO();

    // Load initial data
    loadExpenses();
    loadMonthlySummary();
});
