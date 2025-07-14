import os

import duckdb


class DuckDBLocalContext:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._conn = None

    def _install_load_extension(self, ext_list):
        for ext in ext_list:
            self._conn.install_extension(ext)
            self._conn.load_extension(ext)

    def __enter__(self) -> "duckdb.DuckDBPyConnection":
        if not os.path.exists(os.path.dirname(self.database_path)):
            raise ValueError(
                f"Directory {os.path.dirname(self.database_path)} does not exist."
            )

        self._conn = duckdb.connect(self.database_path)
        self._install_load_extension(["json", "fts", "vss"])

        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn:
            self._conn.close()