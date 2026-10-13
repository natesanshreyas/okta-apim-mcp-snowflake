"""
Azure-hosted LLM agent that calls the MCP Snowflake tool.

This closes the loop in the architecture: the Azure-hosted model is the "agent"
that, given a natural-language question, decides to call the Snowflake MCP tool
(through APIM), runs the query, and composes an answer.

Flow:
  user question
    -> Azure OpenAI chat completion with the MCP tools advertised as functions
    -> model emits a tool call (snowflake_query / snowflake_describe / ...)
    -> we invoke that tool over MCP (through APIM, Okta-bearer attached)
    -> feed tool result back to the model
    -> model returns the final natural-language answer

Auth to APIM uses the SAME Okta access token the user holds (OBO / passthrough).
For this demo, supply OKTA_ACCESS_TOKEN in the environment (obtained via the
device/PKCE flow). The MCP endpoint is the APIM gateway URL.

Env:
  AZURE_OPENAI_ENDPOINT      https://<resource>.openai.azure.com
  AZURE_OPENAI_API_KEY       (or use DefaultAzureCredential for AAD)
  AZURE_OPENAI_DEPLOYMENT    e.g. gpt-4o
  MCP_ENDPOINT               e.g. https://<apim-host>/mcp-snowflake/mcp
  OKTA_ACCESS_TOKEN          Okta access token with snowflake.query scope
"""

import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _mcp_headers() -> dict:
    token = os.environ.get("OKTA_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "OKTA_ACCESS_TOKEN is required so APIM can validate the Okta JWT. "
            "Obtain it via the Okta Auth Code + PKCE flow (see docs/okta-setup.md)."
        )
    return {"Authorization": f"Bearer {token}"}


async def _list_mcp_tools(session: ClientSession) -> list[dict]:
    tools = await session.list_tools()
    specs = []
    for t in tools.tools:
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
        )
    return specs


async def _call_mcp_tool(session: ClientSession, name: str, args: dict) -> str:
    result = await session.call_tool(name, args)
    # Concatenate text content blocks from the MCP tool result.
    parts = []
    for c in result.content:
        if getattr(c, "type", None) == "text":
            parts.append(c.text)
        else:
            parts.append(str(c))
    return "\n".join(parts) if parts else "(no content)"


async def ask(question: str) -> str:
    from openai import AzureOpenAI

    endpoint = os.environ["MCP_ENDPOINT"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
    )

    async with streamablehttp_client(endpoint, headers=_mcp_headers()) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tool_specs = await _list_mcp_tools(session)

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You answer questions about enterprise data by calling the "
                        "Snowflake MCP tools. Prefer snowflake_list_tables and "
                        "snowflake_describe to discover schema before querying."
                    ),
                },
                {"role": "user", "content": question},
            ]

            # Simple tool-calling loop (bounded to avoid runaway iterations).
            for _ in range(6):
                resp = client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    tools=tool_specs,
                    tool_choice="auto",
                )
                msg = resp.choices[0].message
                if not msg.tool_calls:
                    return msg.content or "(no answer)"

                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    }
                )
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or "{}")
                    out = await _call_mcp_tool(session, tc.function.name, args)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": out,
                        }
                    )

            return "Stopped after max tool iterations."


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "Which region has the most customers?"
    print(asyncio.run(ask(q)))
