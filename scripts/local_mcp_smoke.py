"""
Local MCP smoke test — exercises the Snowflake MCP server end to end.

By default it talks to the LOCAL MCP server (http://localhost:8080/mcp) with no
auth header, which matches the local mock demo (APIM/Okta are bypassed locally).

To test THROUGH APIM instead, set:
    export MCP_ENDPOINT=https://<apim-host>/mcp-snowflake/mcp
    export OKTA_ACCESS_TOKEN=<token with snowflake.query scope>

Usage:
    python scripts/local_mcp_smoke.py
"""

import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _endpoint_and_headers():
    endpoint = os.environ.get("MCP_ENDPOINT", "http://localhost:8080/mcp")
    headers = {}
    token = os.environ.get("OKTA_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return endpoint, headers


async def main():
    endpoint, headers = _endpoint_and_headers()
    print(f"-> connecting to MCP endpoint: {endpoint}")
    async with streamablehttp_client(endpoint, headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("\nTools advertised by the MCP server:")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.splitlines()[0] if t.description else ''}")

            print("\n[1] snowflake_list_tables()")
            res = await session.call_tool("snowflake_list_tables", {})
            _print(res)

            print("\n[2] snowflake_describe(table='CUSTOMERS')")
            res = await session.call_tool("snowflake_describe", {"table": "CUSTOMERS"})
            _print(res)

            print("\n[3] snowflake_query(sql='SELECT * FROM CUSTOMERS')")
            res = await session.call_tool(
                "snowflake_query", {"sql": "SELECT * FROM CUSTOMERS"}
            )
            _print(res)

    print("\nSmoke test complete.")


def _print(result):
    for c in result.content:
        text = getattr(c, "text", None)
        print("   ", text if text is not None else c)


if __name__ == "__main__":
    asyncio.run(main())
