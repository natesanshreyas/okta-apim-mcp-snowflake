"""
MCP server exposing Snowflake query capabilities as MCP tools.

Transport: Streamable HTTP (so it can sit behind Azure API Management).
Tools:
  - snowflake_query(sql)      run a read-only SQL query
  - snowflake_describe(table) describe a table's columns
  - snowflake_list_tables()   list tables in the configured schema

Backend selection is controlled by SNOWFLAKE_MODE:
  - mock : serve data from the in-process mock backend (no Snowflake account needed)
  - real : connect to Snowflake via key-pair auth (no static password in path)

Run locally:
    export SNOWFLAKE_MODE=mock
    python server.py
    # MCP endpoint: http://localhost:8080/mcp
"""

import os

from mcp.server.fastmcp import FastMCP

from snowflake_client import get_backend

# Host/port are configurable so the same image runs locally and behind APIM.
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8080"))

mcp = FastMCP(
    name="snowflake-mcp",
    host=HOST,
    port=PORT,
    # Streamable HTTP exposes the MCP endpoint at /mcp by default.
    streamable_http_path="/mcp",
)

backend = get_backend()


@mcp.tool()
def snowflake_query(sql: str) -> dict:
    """Run a read-only SQL query against Snowflake and return rows.

    Only SELECT / SHOW / DESCRIBE style statements are permitted. Any attempt to
    run DML/DDL is rejected to keep the demo capability read-only.

    Args:
        sql: The SQL text to execute.

    Returns:
        A dict with "columns" (list[str]) and "rows" (list[list]).
    """
    return backend.query(sql)


@mcp.tool()
def snowflake_describe(table: str) -> dict:
    """Describe the columns of a table in the configured Snowflake schema.

    Args:
        table: Table name (optionally schema-qualified).

    Returns:
        A dict with "columns" describing name/type for each column.
    """
    return backend.describe(table)


@mcp.tool()
def snowflake_list_tables() -> dict:
    """List tables available in the configured Snowflake database/schema."""
    return backend.list_tables()


if __name__ == "__main__":
    mode = os.environ.get("SNOWFLAKE_MODE", "mock")
    print(f"[snowflake-mcp] starting on http://{HOST}:{PORT}/mcp (mode={mode})")
    # FastMCP's streamable-http transport runs an ASGI server on HOST:PORT.
    mcp.run(transport="streamable-http")
