"""
Data-cleaning operations.

Every function is pure: it takes a DataFrame and returns a NEW DataFrame
plus an `info` dict describing what changed. Nothing here touches
state.py or knows about HTTP -- that's main.py's job.
"""

import numpy as np
import pandas as pd


class CleaningError(Exception):
    """Raised when an operation can't be performed safely (bad column, bad type, etc.)."""


# --- Column summary (the "quick look" table) --------------------------------

def detect_outliers_iqr(df: pd.DataFrame, column: str, multiplier: float = 1.5) -> pd.Series:
    """Boolean mask of rows flagged as outliers using the standard IQR rule."""
    series = df[column]
    if not _is_numeric_non_bool(series):
        raise CleaningError(f"'{column}' must be numeric (not boolean/text) to detect outliers.")
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - multiplier * iqr, q3 + multiplier * iqr
    return (series < lower) | (series > upper)
def remove_outliers(df: pd.DataFrame, column: str, multiplier: float = 1.5):
    if not pd.api.types.is_numeric_dtype(df[column]):
        raise CleaningError(f"'{column}' must be numeric to remove outliers.")
    mask = detect_outliers_iqr(df, column, multiplier)
    new_df = df[~mask]
    return new_df, {
        "column": column,
        "rows_before": len(df),
        "rows_after": len(new_df),
        "rows_removed": int(mask.sum()),
    }


def _is_numeric_non_bool(series: pd.Series) -> bool:
    """
    pandas treats bool columns as numeric (is_numeric_dtype returns True for
    them), which breaks quantile-based outlier detection since NumPy can't
    do arithmetic on booleans. This excludes them explicitly.
    """
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def column_summary(df: pd.DataFrame) -> list[dict]:
    """
    One row per column: dtype, missing count/%, unique count, whitespace-issue
    count (text columns), and an outlier count (numeric columns). This is the
    per-column 'quick look' table shown after upload -- no charts, just counts.
    """
    n_rows = len(df)
    summary = []
    for col in df.columns:
        series = df[col]
        is_numeric = _is_numeric_non_bool(series)
        is_text = _is_text_column(series)
        missing = int(series.isna().sum())

        outlier_count = None
        if is_numeric and series.notna().sum() > 0:
            outlier_count = int(detect_outliers_iqr(df, col).sum())

        whitespace_count = None
        if is_text:
            whitespace_count = int(series.map(lambda v: isinstance(v, str) and v != v.strip()).sum())

        if pd.api.types.is_bool_dtype(series):
            col_type = "Boolean"
        elif is_numeric:
            col_type = "Integer" if pd.api.types.is_integer_dtype(series) else "Float"
        elif pd.api.types.is_datetime64_any_dtype(series):
            col_type = "Datetime"
        else:
            col_type = "Text"

        summary.append({
            "column": col,
            "type": col_type,
            "missing_count": missing,
            "missing_pct": round(missing / n_rows * 100, 1) if n_rows else 0.0,
            "whitespace_count": whitespace_count,   # None for non-text columns
            "unique_count": int(series.nunique(dropna=True)),
            "outlier_count": outlier_count,          # None for non-numeric columns
        })
    return summary
def column_issue_examples(df: pd.DataFrame, column: str, max_examples: int = 3) -> dict:
    """
    Real example values behind each warning flag, for the 'Details' toggle:
    which rows are missing, which text values have stray whitespace, and
    which numbers are flagged as outliers.
    """
    series = df[column]
    result = {"missing_rows": [], "whitespace_examples": [], "outlier_examples": []}

    missing_mask = series.isna()
    if missing_mask.any():
        result["missing_rows"] = df.index[missing_mask][:max_examples].tolist()

    if _is_text_column(series):
        ws_mask = series.map(lambda v: isinstance(v, str) and v != v.strip())
        if ws_mask.any():
            result["whitespace_examples"] = [f"'{v}'" for v in series[ws_mask].head(max_examples).tolist()]

    if _is_numeric_non_bool(series) and series.notna().sum() > 0:
        outlier_mask = detect_outliers_iqr(df, column)
        if outlier_mask.any():
            result["outlier_examples"] = series[outlier_mask].head(max_examples).tolist()

    return result


def quick_clean(df: pd.DataFrame):
    """
    A single-click preset for the most common first-pass cleanup: trims
    whitespace on every text column, then removes exact duplicate rows.
    Still goes through the normal preview/apply flow -- nothing commits
    silently.
    """
    step1, ws_info = strip_whitespace(df)
    step2, dup_info = remove_duplicate_rows(step1, keep="first")
    return step2, {"whitespace": ws_info, "duplicates": dup_info}
def handle_outliers(df: pd.DataFrame, column: str, method: str, custom_value=None, multiplier: float = 1.5):
    """method: 'remove' | 'mean' | 'custom'"""
    if not _is_numeric_non_bool(df[column]):
        raise CleaningError(f"'{column}' must be numeric to handle outliers.")
    mask = detect_outliers_iqr(df, column, multiplier)
    outlier_count = int(mask.sum())

    if method == "remove":
        new_df = df[~mask]
        return new_df, {"column": column, "method": method, "outliers_removed": outlier_count}

    new_df = df.copy()
    if method == "mean":
        replacement = df.loc[~mask, column].mean()
    elif method == "custom":
        try:
            replacement = float(custom_value)
        except (TypeError, ValueError):
            raise CleaningError(f"'{custom_value}' isn't a valid number for column '{column}'.")
    else:
        raise CleaningError(f"Unknown outlier method: {method}")

    new_df.loc[mask, column] = replacement
    return new_df, {"column": column, "method": method, "outliers_replaced": outlier_count, "replacement_value": str(replacement)}

# --- Missing values ----------------------------------------------------

def drop_missing_rows(df: pd.DataFrame, columns: list[str] | None = None):
    subset = columns if columns else None
    new_df = df.dropna(subset=subset)
    return new_df, {
        "rows_before": len(df),
        "rows_after": len(new_df),
        "rows_removed": len(df) - len(new_df),
    }


def fill_missing(df: pd.DataFrame, column: str, method: str, custom_value=None):
    """method: 'mean' | 'median' | 'mode' | 'zero' | 'ffill' | 'bfill' | 'custom'"""
    if column not in df.columns:
        raise CleaningError(f"Column '{column}' not found.")
    new_df = df.copy()
    series = new_df[column]

    if method == "mean":

        if not _is_numeric_non_bool(series):
             raise CleaningError(f"'{column}' is not numeric; can't fill with mean.")
        fill_value = series.mean()
        new_df[column] = series.fillna(fill_value)
    elif method == "median":
        if not _is_numeric_non_bool(series):
            raise CleaningError(f"'{column}' is not numeric; can't fill with median.")
        fill_value = series.median()
        new_df[column] = series.fillna(fill_value)
    elif method == "mode":
        modes = series.mode(dropna=True)
        if modes.empty:
            raise CleaningError(f"'{column}' has no mode (all values missing).")
        fill_value = modes.iloc[0]
        new_df[column] = series.fillna(fill_value)
    elif method == "zero":
        fill_value = 0
        new_df[column] = series.fillna(0)
    elif method == "ffill":
        # Copies the value from the row above -- useful for sorted/sequential data.
        new_df[column] = series.ffill()
        fill_value = "(value from row above)"
    elif method == "bfill":
        # Copies the value from the row below.
        new_df[column] = series.bfill()
        fill_value = "(value from row below)"
    elif method == "custom":
        fill_value = custom_value
        new_df[column] = series.fillna(custom_value)
    else:
        raise CleaningError(f"Unknown fill method: {method}")

    return new_df, {"column": column, "method": method, "fill_value": str(fill_value)}


# --- Duplicate rows ------------------------------------------------------

def remove_duplicate_rows(df: pd.DataFrame, keep: str = "first"):
    new_df = df.drop_duplicates(keep=keep)
    return new_df, {
        "rows_before": len(df),
        "rows_after": len(new_df),
        "rows_removed": len(df) - len(new_df),
    }


# --- Column management ---------------------------------------------------

def rename_column(df: pd.DataFrame, old_name: str, new_name: str):
    if old_name not in df.columns:
        raise CleaningError(f"Column '{old_name}' not found.")
    return df.rename(columns={old_name: new_name}), {"renamed": {old_name: new_name}}


def remove_columns(df: pd.DataFrame, columns: list[str]):
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise CleaningError(f"Column(s) not found: {', '.join(missing)}")
    new_df = df.drop(columns=columns)
    return new_df, {"columns_before": df.shape[1], "columns_after": new_df.shape[1]}


# --- Whitespace & text standardization ------------------------------------

def _is_text_column(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def strip_whitespace(df: pd.DataFrame, columns: list[str] | None = None):
    target_cols = columns if columns else [c for c in df.columns if _is_text_column(df[c])]
    new_df = df.copy()
    for col in target_cols:
        if col in new_df.columns and _is_text_column(new_df[col]):
            new_df[col] = new_df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    return new_df, {"columns": target_cols}


def standardize_text_case(df: pd.DataFrame, columns: list[str], case: str):
    """case: 'lower' | 'upper' | 'title'"""
    new_df = df.copy()
    for col in columns:
        if col not in new_df.columns or not _is_text_column(new_df[col]):
            continue
        if case == "lower":
            new_df[col] = new_df[col].map(lambda v: v.lower() if isinstance(v, str) else v)
        elif case == "upper":
            new_df[col] = new_df[col].map(lambda v: v.upper() if isinstance(v, str) else v)
        elif case == "title":
            new_df[col] = new_df[col].map(lambda v: v.title() if isinstance(v, str) else v)
        else:
            raise CleaningError(f"Unknown case option: {case}")
    return new_df, {"columns": columns, "case": case}


# --- Find & replace --------------------------------------------------------

def find_replace(df: pd.DataFrame, find_value: str, replace_value: str, columns: list[str] | None = None):
    target_cols = columns if columns else list(df.columns)
    new_df = df.copy()
    replacements = 0
    for col in target_cols:
        if col not in new_df.columns:
            continue
        mask = new_df[col].astype(str) == find_value
        replacements += int(mask.sum())
        new_df.loc[mask, col] = replace_value
    return new_df, {"find": find_value, "replace": replace_value, "replacements": replacements}


# --- Data type conversion ---------------------------------------------------

def convert_column_type(df: pd.DataFrame, column: str, target_type: str, invalid_action: str = "missing"):
    """target_type: 'String' | 'Integer' | 'Float' | 'Boolean' | 'Datetime'
    invalid_action: 'missing' (bad values -> NaN) or 'reject' (raise an error)"""
    if column not in df.columns:
        raise CleaningError(f"Column '{column}' not found.")
    new_df = df.copy()
    series = new_df[column]
    invalid_count = 0

    if target_type == "String":
        new_series = series.astype(str).where(series.notna(), other=np.nan)
    elif target_type in ("Integer", "Float"):
        cleaned = series.astype(str).str.replace(",", "").where(series.notna())
        numeric = pd.to_numeric(cleaned, errors="coerce")
        invalid_count = int((numeric.isna() & series.notna()).sum())
        if invalid_count and invalid_action == "reject":
            raise CleaningError(f"{invalid_count} value(s) in '{column}' aren't valid numbers.")
        new_series = numeric.astype("Int64") if target_type == "Integer" else numeric.astype("float64")
    elif target_type == "Boolean":
        truthy, falsy = {"true", "1", "yes", "y"}, {"false", "0", "no", "n"}
        def to_bool(v):
            if pd.isna(v):
                return np.nan
            t = str(v).strip().lower()
            return True if t in truthy else (False if t in falsy else np.nan)
        new_series = series.map(to_bool)
        invalid_count = int((new_series.isna() & series.notna()).sum())
        if invalid_count and invalid_action == "reject":
            raise CleaningError(f"{invalid_count} value(s) in '{column}' aren't valid booleans.")
    elif target_type == "Datetime":
        new_series = pd.to_datetime(series, errors="coerce")
        invalid_count = int((new_series.isna() & series.notna()).sum())
        if invalid_count and invalid_action == "reject":
            raise CleaningError(f"{invalid_count} value(s) in '{column}' aren't valid dates.")
    else:
        raise CleaningError(f"Unknown target type: {target_type}")

    new_df[column] = new_series
    return new_df, {"column": column, "target_type": target_type, "invalid_count": invalid_count}


# --- Row filtering -----------------------------------------------------------

def apply_filter(df: pd.DataFrame, column: str, operator: str, value: str):
    """operator: '==', '!=', '>', '>=', '<', '<=', 'contains'"""
    if column not in df.columns:
        raise CleaningError(f"Column '{column}' not found.")
    series = df[column]

    if operator == "contains":
        mask = series.astype(str).str.contains(value, na=False, regex=False)
    else:
        if pd.api.types.is_numeric_dtype(series):
            try:
                value = float(value)
            except ValueError:
                raise CleaningError(f"'{value}' is not a valid number for column '{column}'.")
            comparable = series
        else:
            comparable = series.astype(str)
        ops = {
            "==": comparable.eq, "!=": comparable.ne,
            ">": comparable.gt, ">=": comparable.ge,
            "<": comparable.lt, "<=": comparable.le,
        }
        if operator not in ops:
            raise CleaningError(f"Unknown operator: {operator}")
        mask = ops[operator](value)

    new_df = df[mask]
    return new_df, {"rows_before": len(df), "rows_after": len(new_df)}


# --- Sorting ------------------------------------------------------------------

def sort_dataframe(df: pd.DataFrame, columns: list[str], ascending: bool = True):
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise CleaningError(f"Column(s) not found: {', '.join(missing)}")
    new_df = df.sort_values(by=columns, ascending=ascending).reset_index(drop=True)
    return new_df, {"columns": columns, "ascending": ascending}