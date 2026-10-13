"""
Agent core (Pattern B) — the Azure-hosted model is the agent that selects and
invokes MCP tools.

Loop:
  user question + user's Okta token
    -> Azure OpenAI chat.completions, advertising the MCP tools as functions
    -> model emits a tool call (the model SELECTS the tool)
    -> OBO: exchange the user's token for an MCP-scoped token (preserves identity)
    -> call the MCP tool through APIM with the OBO token
    -> feed the tool result back to the model
    -> model returns the final natural-language answer

The MCP endpoint is the APIM MCP API (so APIM validates the OBO JWT on this hop).
Azure OpenAI is reached with the agent's own AAD identity or an API key — that is
the inference credential, separate from the user-delegation chain.

Env (see .env.example):
  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT
  MCP_ENDPOINT                 APIM MCP API, e.g. https://<apim>/mcp-snowflake/mcp
  OKTA_ISSUER, OKTA_AGENT_CLIENT_ID, OKTA_AGENT_CLIENT_SECRET, OKTA_MCP_AUDIENCE
"""

import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from obo import exchange_for_mcp_token

SYSTEM_PROMPT = (
    "You answer questions about enterprise data by calling the Snowflake MCP "
    "tools. Prefer snowflake_list_tables and snowflake_describe to discover the "
    "schema before querying. Only use the provided tools."
)


def _mcp_tools_to_openai(tools) -> list[dict]:
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
    parts = []
    for c in result.content:
        if getattr(c, "type", None) == "text":
            parts.append(c.text)
        else:
            parts.append(str(c))
    return "\n".join(parts) if parts else "(no content)"


async def run_agent(question: str, user_token: str) -> str:
    """Run the full Pattern B agent loop for one question.

    Args:
        question:   the end user's natural-language question.
        user_token: the end user's Okta access token (subject of the OBO exchange).
    """
    from openai import AzureOpenAI

    # 1. OBO: mint the downstream MCP-scoped token on behalf of the user.
    mcp_token = await exchange_for_mcp_token(user_token)

    endpoint = os.environ["MCP_ENDPOINT"]
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
        api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01"),
    )

    headers = {"Authorization": f"Bearer {mcp_token}"}
    async with streamablehttp_client(endpoint, headers=headers) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tool_specs = _mcp_tools_to_openai(await session.list_tools())

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]

            for _ in range(6):  # bounded tool-calling loop
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
                        {"role": "tool", "tool_call_id": tc.id, "content": out}
                    )

            return "Stopped after max tool iterations."


if __name__ == "__main__":
    # CLI test: supply the user's Okta token via OKTA_ACCESS_TOKEN.
    import asyncio
    import sys

    token = os.environ.get("OKTA_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set OKTA_ACCESS_TOKEN (end-user token) to run the CLI test.")
    q = " ".join(sys.argv[1:]) or "Which region has the most customers?"
    print(asyncio.run(run_agent(q, token)))
