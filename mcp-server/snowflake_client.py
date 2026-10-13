"""
Snowflake backends for the MCP server.

Two implementations share one interface so the MCP tools are identical whether
you run the local demo (mock) or connect to a real Snowflake account (real).

Credential handling (real mode):
  - Uses key-pair authentication (RSA private key), NOT a static password in the
    request path. The private key path and passphrase come from environment
    variables that in production should be sourced from Azure Key Vault.
  - Never hard-code credentials. See .env.example / docs/snowflake-setup.md.
"""

import os
import re
from abc import ABC, abstractmethod

# Guardrail: only allow read-only statements through the demo tool.
_READ_ONLY = re.compile(r"^\s*(select|with|show|describe|desc|explain)\b", re.IGNORECASE)


def _ensure_read_only(sql: str) -> None:
    if not _READ_ONLY.match(sql or ""):
        raise ValueError(
            "Only read-only statements (SELECT/WITH/SHOW/DESCRIBE/EXPLAIN) are allowed."
        )


class Backend(ABC):
    @abstractmethod
    def query(self, sql: str) -> dict: ...

    @abstractmethod
    def describe(self, table: str) -> dict: ...

    @abstractmethod
    def list_tables(self) -> dict: ...


class MockBackend(Backend):
    """In-process mock that serves the sample data in mock-snowflake/seed.sql.

    Keeps the demo fully runnable without a Snowflake account. The dataset is a
    tiny CUSTOMERS / ORDERS star so queries feel real.
    """

    def __init__(self) -> None:
        self._tables = {
            "CUSTOMERS": {
                "columns": [
                    ("CUSTOMER_ID", "NUMBER"),
                    ("NAME", "VARCHAR"),
                    ("REGION", "VARCHAR"),
                    ("SIGNUP_DATE", "DATE"),
                ],
                "rows": [
                    [1, "Acme Corp", "AMER", "2023-01-15"],
                    [2, "Globex", "EMEA", "2023-03-02"],
                    [3, "Initech", "AMER", "2023-06-21"],
                    [4, "Umbrella", "APAC", "2024-02-10"],
                ],
            },
            "ORDERS": {
                "columns": [
                    ("ORDER_ID", "NUMBER"),
                    ("CUSTOMER_ID", "NUMBER"),
                    ("AMOUNT", "NUMBER"),
                    ("ORDER_DATE", "DATE"),
                ],
                "rows": [
                    [1001, 1, 2500, "2024-05-01"],
                    [1002, 2, 1800, "2024-05-03"],
                    [1003, 1, 3200, "2024-06-12"],
                    [1004, 3, 900, "2024-06-15"],
                    [1005, 4, 4100, "2024-07-01"],
                ],
            },
        }

    def query(self, sql: str) -> dict:
        _ensure_read_only(sql)
        s = sql.strip().rstrip(";")
        low = s.lower()

        # Minimal pattern support so the demo returns meaningful data.
        if low.startswith("show tables"):
            return self.list_tables()

        m = re.match(r"select\s+(.+?)\s+from\s+([a-z0-9_\.]+)", low, re.IGNORECASE)
        if m:
            table = m.group(2).split(".")[-1].upper()
            if table not in self._tables:
                raise ValueError(f"Unknown table: {table}")
            t = self._tables[table]
            cols = [c[0] for c in t["columns"]]
            select_part = m.group(1).strip()
            if select_part == "*":
                return {"columns": cols, "rows": [list(r) for r in t["rows"]]}
            wanted = [c.strip().upper() for c in select_part.split(",")]
            # count(*) convenience
            if len(wanted) == 1 and wanted[0].replace(" ", "") in ("COUNT(*)", "COUNT(1)"):
                return {"columns": ["COUNT"], "rows": [[len(t["rows"])]]}
            idx = [cols.index(w) for w in wanted if w in cols]
            return {
                "columns": [cols[i] for i in idx],
                "rows": [[r[i] for i in idx] for r in t["rows"]],
            }

        # Fallback: echo a single-cell result so the tool never hard-fails in demo.
        return {"columns": ["RESULT"], "rows": [[f"mock executed: {s}"]]}

    def describe(self, table: str) -> dict:
        name = table.split(".")[-1].upper()
        if name not in self._tables:
            raise ValueError(f"Unknown table: {name}")
        return {
            "table": name,
            "columns": [{"name": c[0], "type": c[1]} for c in self._tables[name]["columns"]],
        }

    def list_tables(self) -> dict:
        return {"columns": ["TABLE_NAME"], "rows": [[t] for t in self._tables.keys()]}


class SnowflakeBackend(Backend):
    """Real Snowflake backend using key-pair authentication.

    Lazily imports the connector so the mock demo has no hard dependency on it.
    """

    def __init__(self) -> None:
        self._conn = None

    def _connect(self):
        if self._conn is not None:
            return self._conn

        import snowflake.connector  # type: ignore
        from cryptography.hazmat.primitives import serialization

        account = _require("SNOWFLAKE_ACCOUNT")
        user = _require("SNOWFLAKE_USER")
        role = os.environ.get("SNOWFLAKE_ROLE", "MCP_DEMO_ROLE")
        warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE", "MCP_DEMO_WH")
        database = os.environ.get("SNOWFLAKE_DATABASE", "MCP_DEMO_DB")
        schema = os.environ.get("SNOWFLAKE_SCHEMA", "PUBLIC")

        key_path = _require("SNOWFLAKE_PRIVATE_KEY_PATH")
        passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        with open(key_path, "rb") as f:
            p_key = serialization.load_pem_private_key(
                f.read(),
                password=passphrase.encode() if passphrase else None,
            )
        pkb = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        self._conn = snowflake.connector.connect(
            account=account,
            user=user,
            private_key=pkb,
            role=role,
            warehouse=warehouse,
            database=database,
            schema=schema,
        )
        return self._conn

    def query(self, sql: str) -> dict:
        _ensure_read_only(sql)
        cur = self._connect().cursor()
        try:
            cur.execute(sql)
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = [list(r) for r in cur.fetchall()]
            return {"columns": cols, "rows": rows}
        finally:
            cur.close()

    def describe(self, table: str) -> dict:
        cur = self._connect().cursor()
        try:
            cur.execute(f"DESCRIBE TABLE {table}")
            rows = cur.fetchall()
            return {
                "table": table,
                "columns": [{"name": r[0], "type": r[1]} for r in rows],
            }
        finally:
            cur.close()

    def list_tables(self) -> dict:
        return self.query("SHOW TABLES")


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


def get_backend() -> Backend:
    mode = os.environ.get("SNOWFLAKE_MODE", "mock").lower()
    if mode == "real":
        return SnowflakeBackend()
    return MockBackend()
