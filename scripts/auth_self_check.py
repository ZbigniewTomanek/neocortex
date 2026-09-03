#!/usr/bin/env python3
"""Verify the explicit admin and MCP dev-token paths without exposing tokens."""

from __future__ import annotations

import argparse
import asyncio
import os

import httpx
from fastmcp import Client


async def _check(args: argparse.Namespace) -> int:
    admin_token = os.environ.get(args.admin_token_env)
    mcp_token = os.environ.get(args.mcp_token_env)
    if not admin_token:
        raise RuntimeError(f"{args.admin_token_env} is required")
    if not mcp_token:
        raise RuntimeError(f"{args.mcp_token_env} is required")

    admin_url = args.admin_url.rstrip("/") + "/admin/graphs"
    async with httpx.AsyncClient(timeout=10.0) as client:
        invalid = await client.get(admin_url, headers={"Authorization": "Bearer invalid-measurement-token"})
        if invalid.status_code != 401:
            raise RuntimeError(f"invalid admin credential returned HTTP {invalid.status_code}, expected 401")
        valid = await client.get(admin_url, headers={"Authorization": f"Bearer {admin_token}"})
        valid.raise_for_status()

    invalid_mcp_rejected = False
    try:
        async with Client(args.mcp_url, auth="invalid-measurement-token") as client:
            await client.call_tool("discover_graphs", {})
    except Exception:
        invalid_mcp_rejected = True
    if not invalid_mcp_rejected:
        raise RuntimeError("invalid MCP credential was accepted")

    async with Client(args.mcp_url, auth=mcp_token) as client:
        result = await client.call_tool("discover_graphs", {})
    if result.structured_content is None:
        raise RuntimeError("valid MCP credential returned no structured discover_graphs result")

    print("admin auth: PASS (invalid credential rejected; valid credential accepted)")
    print("MCP auth: PASS (invalid credential rejected; valid credential accepted)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-url", default=os.environ.get("NEOCORTEX_INGESTION_BASE_URL", "http://127.0.0.1:8001"))
    parser.add_argument("--mcp-url", default=os.environ.get("NEOCORTEX_MCP_URL", "http://127.0.0.1:8000/mcp"))
    parser.add_argument("--admin-token-env", default="NEOCORTEX_ADMIN_TOKEN")
    parser.add_argument("--mcp-token-env", default="NEOCORTEX_MCP_TOKEN")
    args = parser.parse_args()
    return asyncio.run(_check(args))


if __name__ == "__main__":
    raise SystemExit(main())
