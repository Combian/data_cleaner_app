# Data Cleaner

A self-hosted, single-user web app for interactively cleaning tabular data
(CSV/Excel). Upload a file, inspect it for missing values, whitespace
issues, duplicates, and outliers, apply cleaning operations one at a time
with a full preview/undo/history trail, then export the cleaned result.

**Stack:** FastAPI backend (pure pandas logic, no database) + vanilla
HTML/CSS/JS frontend.

## Project structure

```
main.py             FastAPI routes — HTTP only, no pandas logic
cleaning.py          Pure data-cleaning functions (pandas)
state.py             In-memory session state + undo history
static/              Frontend (index.html, script.js, style.css)
requirements.txt     Python dependencies
```

## Setup

Clone the repo first:

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Windows (Command Prompt)

```cmd
python -m venv .venv
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

> If PowerShell blocks the activation script with an execution-policy error, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, then retry.

## Run

```bash
uvicorn main:app --reload
```

Then open `http://localhost:8000` in your browser.

## How it works

1. **Upload** a CSV or Excel file (`.csv`, `.xls`, `.xlsx`). Multi-sheet
   Excel files let you pick a sheet.
2. **Inspect** — see a per-column summary: type, missing %, unique count,
   whitespace issues, and outlier count, with drill-down examples.
3. **Clean** — apply operations one at a time (drop/fill missing, remove
   outliers, remove duplicates, rename/remove columns, strip whitespace,
   standardize case, find & replace, convert types, filter rows, sort, or
   run the one-click "quick clean" preset). Every operation previews the
   result before you commit it.
4. **History** — every applied step is kept in an undo stack; jump back to
   any previous step or reset to the original upload at any time.
5. **Export** — download the cleaned data as CSV or XLSX.

## Notes

- State is kept in memory for a single session — restarting the server
  clears any uploaded data. This is by design for a local, single-user tool.
- The undo history stores a full copy of the dataframe at each step, so very
  large files with many cleaning steps will use more memory accordingly.
