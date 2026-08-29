"""
FastAPI application entry point.

Handles HTTP only: receiving requests, calling cleaning.py functions,
reading/writing state.py, and returning JSON. No pandas logic lives here.
"""

import io
from typing import Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import cleaning
from state import state

app = FastAPI(title="Data Cleaner")


# --- Serve the frontend --------------------------------------------------

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")


# --- File loading ----------------------------------------------------------

def _read_dataframe(contents: bytes, filename: str, sheet_name: Optional[str] = None):
    ext = filename.lower().rsplit(".", 1)[-1]
    try:
        if ext == "csv":
            for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    return pd.read_csv(io.BytesIO(contents), encoding=encoding)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not decode CSV with common encodings.")
        elif ext in ("xls", "xlsx"):
            engine = "xlrd" if ext == "xls" else "openpyxl"
            excel_file = pd.ExcelFile(io.BytesIO(contents), engine=engine)
            target_sheet = sheet_name or excel_file.sheet_names[0]
            return excel_file.parse(sheet_name=target_sheet)
        else:
            raise ValueError(f"Unsupported file type: .{ext}")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read file: {exc}")


@app.post("/sheets")
async def list_sheets(file: UploadFile = File(...)):
    """For XLS/XLSX uploads: return sheet names so the user can pick one."""
    ext = file.filename.lower().rsplit(".", 1)[-1]
    if ext not in ("xls", "xlsx"):
        return {"sheets": []}
    contents = await file.read()
    engine = "xlrd" if ext == "xls" else "openpyxl"
    try:
        excel_file = pd.ExcelFile(io.BytesIO(contents), engine=engine)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not open workbook: {exc}")
    return {"sheets": excel_file.sheet_names}


@app.post("/upload")
async def upload(file: UploadFile = File(...), sheet_name: Optional[str] = None):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    df = _read_dataframe(contents, file.filename, sheet_name)
    if df.shape[1] == 0:
        raise HTTPException(status_code=400, detail="File has no columns.")

    state.load_dataset(file.filename, df)
    return {"filename": file.filename, "rows": len(df), "columns": df.shape[1]}


# --- Inspection --------------------------------------------------------------

@app.get("/inspect")
def inspect():
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    df = state.current
    return {
        "rows": len(df),
        "columns": df.shape[1],
        "duplicate_rows": int(df.duplicated().sum()),
        "column_summary": cleaning.column_summary(df),
    }
@app.get("/column-details/{column}")
def column_details(column: str):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    df = state.current
    if column not in df.columns:
        raise HTTPException(status_code=404, detail=f"Column '{column}' not found.")
    return cleaning.column_issue_examples(df, column)

@app.get("/preview")
def preview(n: int = 10, from_end: bool = False):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    df = state.current
    subset = df.tail(n) if from_end else df.head(n)
    return {"rows": subset.fillna("").to_dict(orient="records"), "columns": list(df.columns)}


# --- Cleaning operations (preview vs. apply) --------------------------------

class CleanRequest(BaseModel):
    operation: str
    params: dict = {}
    apply: bool = False   # False = just preview the result, True = commit it


OPERATIONS = {
    "drop_missing_rows": lambda df, p: cleaning.drop_missing_rows(df, p.get("columns")),
    "remove_outliers": lambda df, p: cleaning.remove_outliers(df, p["column"], p.get("multiplier", 1.5)),
    "fill_missing": lambda df, p: cleaning.fill_missing(df, p["column"], p["method"], p.get("custom_value")),
    "remove_duplicates": lambda df, p: cleaning.remove_duplicate_rows(df, p.get("keep", "first")),
    "rename_column": lambda df, p: cleaning.rename_column(df, p["old_name"], p["new_name"]),
    "remove_columns": lambda df, p: cleaning.remove_columns(df, p["columns"]),
    "strip_whitespace": lambda df, p: cleaning.strip_whitespace(df, p.get("columns")),
    "standardize_case": lambda df, p: cleaning.standardize_text_case(df, p["columns"], p["case"]),
    "find_replace": lambda df, p: cleaning.find_replace(df, p["find"], p["replace"], p.get("columns")),
    "convert_type": lambda df, p: cleaning.convert_column_type(df, p["column"], p["target_type"], p.get("invalid_action", "missing")),
    "filter_rows": lambda df, p: cleaning.apply_filter(df, p["column"], p["operator"], p["value"]),
    "sort": lambda df, p: cleaning.sort_dataframe(df, p["columns"], p.get("ascending", True)),
    "handle_outliers": lambda df, p: cleaning.handle_outliers(df, p["column"], p["method"], p.get("custom_value"), p.get("multiplier", 1.5)),
    "quick_clean": lambda df, p: cleaning.quick_clean(df)
}


@app.post("/clean")
def clean(request: CleanRequest):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    if request.operation not in OPERATIONS:
        raise HTTPException(status_code=400, detail=f"Unknown operation: {request.operation}")

    try:
        new_df, info = OPERATIONS[request.operation](state.current, request.params)
    except cleaning.CleaningError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing required parameter: {exc}")

    if request.apply:
        label = f"{request.operation} -> {info}"
        state.record(label, new_df)

    preview_rows = new_df.head(10).fillna("").to_dict(orient="records")
    return {
        "applied": request.apply,
        "info": info,
        "rows_before": len(state.original) if request.apply else len(state.current),
        "rows_after": len(new_df),
        "preview": preview_rows,
    }


# --- History / undo / reset --------------------------------------------------

@app.get("/history")
def history():
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    return {"steps": state.labels(), "at_original": len(state.history) <= 1}


@app.post("/undo")
def undo():
    state.undo_last()
    return {"steps": state.labels()}


@app.post("/reset")
def reset():
    state.reset_to_original()
    return {"steps": state.labels()}

@app.get("/history/{index}/preview")
def history_step_preview(index: int, n: int = 10):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    try:
        df = state.snapshot_at(index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    subset = df.head(n)
    return {"rows": subset.fillna("").to_dict(orient="records"), "columns": list(df.columns), "row_count": len(df)}


@app.post("/history/{index}/restore")
def history_restore(index: int):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    try:
        state.restore_to(index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"steps": state.labels()}
# --- Export --------------------------------------------------------------------

@app.get("/export")
def export(format: str = "csv", filename: str = "cleaned_data"):
    if not state.is_loaded():
        raise HTTPException(status_code=400, detail="No dataset loaded yet.")
    df = state.current

    if format == "csv":
        buffer = io.StringIO()
        df.to_csv(buffer, index=False)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    elif format == "xlsx":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Cleaned Data")
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    else:
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'xlsx'.")