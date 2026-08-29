"""
In-memory application state.

Holds the current dataset and a simple linear history of cleaning steps.
FastAPI itself has no memory between requests, so this module is what lets
"upload", "clean", and "export" work together as one session.
"""

import pandas as pd


class AppState:
    def __init__(self):
        self.history: list[tuple[str, pd.DataFrame]] = []
        self.filename: str | None = None

    def load_dataset(self, filename: str, df: pd.DataFrame):
        """Called once, right after a file is uploaded."""
        self.filename = filename
        self.history = [("Original dataset", df.copy())]

    @property
    def current(self) -> pd.DataFrame:
        if not self.history:
            raise ValueError("No dataset loaded yet.")
        return self.history[-1][1]

    @property
    def original(self) -> pd.DataFrame:
        if not self.history:
            raise ValueError("No dataset loaded yet.")
        return self.history[0][1]

    def record(self, label: str, df: pd.DataFrame):
        """Called after every cleaning operation the user applies."""
        self.history.append((label, df.copy()))

    def labels(self) -> list[str]:
        return [label for label, _ in self.history]

    def undo_last(self):
        if len(self.history) > 1:
            self.history.pop()

    def reset_to_original(self):
        if self.history:
            self.history = [self.history[0]]
    def snapshot_at(self, index: int) -> pd.DataFrame:
        """Return the dataframe as it existed at a specific history step, without changing state."""
        if index < 0 or index >= len(self.history):
            raise ValueError("That history step no longer exists.")
        return self.history[index][1]

    def restore_to(self, index: int):
        """Jump directly to any earlier step, discarding everything after it."""
        if index < 0 or index >= len(self.history):
            raise ValueError("That history step no longer exists.")
        self.history = self.history[: index + 1]

    def is_loaded(self) -> bool:
        return len(self.history) > 0


# A single shared instance -- this app is local/single-user, so one global
# state object is enough (no per-user sessions needed).
state = AppState()