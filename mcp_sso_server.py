# mcp_sso_server.py

import os
import logging
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp_sso_server")

# In-memory cookie jar for the MCP agent session (demo only)
session_cookies: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app for browser + HTTP clients
# ---------------------------------------------------------------------------

app = FastAPI(title="SSO MCP Server")

# CORS for your static HTML (adjust origins if needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*",  # demo: allow all; tighten this in prod
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# FastMCP server (for MCP tools / LLM clients)
# ---------------------------------------------------------------------------

mcp = FastMCP("SSO MCP Server")

# ------------------------ MCP TOOLS (LLM side) -----------------------------


@mcp.tool()
def sso_login() -> dict:
    """
    Start SSO login and return the Azure auth URL.

    Called by either:
    - HTTP endpoint /sso_login (browser)
    - MCP tool (LLM client)
    """
    try:
        with httpx.Client(base_url=BACKEND_BASE_URL, follow_redirects=False) as client:
            resp = client.get("/auth/login")
            if resp.is_redirect:
                auth_url = resp.headers.get("location")
                logger.info("SSO login initiated, auth_url obtained")
                return {"auth_url": auth_url}
            # Non-redirect – try to parse JSON error
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"Login failed (no JSON body): {e}")
                return {"error": "login failed"}
    except Exception as e:
        logger.error(f"Connection error during login: {e}")
        return {"error": f"connection_error: {str(e)}"}


@mcp.tool()
def sso_callback(code: str, state: Optional[str] = None) -> dict:
    """
    Handle SSO callback and store session cookies for the MCP agent.
    """
    try:
        logger.info("sso_callback called")
        params = {"code": code}
        if state:
            params["state"] = state

        with httpx.Client(base_url=BACKEND_BASE_URL, follow_redirects=False) as client:
            resp = client.get("/auth/callback", params=params)

            # Store cookies from backend in our in-memory jar
            if resp.cookies:
                session_cookies.clear()
                session_cookies.update(resp.cookies)
                logger.info(f"Session cookies stored: {len(resp.cookies)} cookie(s)")

            if resp.is_redirect:
                # In our backend, /auth/callback redirects to /post-login
                logger.info("Callback successful, session established")
                return {"status": "OK"}

            # If backend returned JSON instead of redirect, pass it through
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"Callback failed (no JSON body): {e}")
                return {"error": "callback failed"}
    except Exception as e:
        logger.error(f"Connection error during callback: {e}")
        return {"error": f"connection_error: {str(e)}"}


@mcp.tool()
def sso_me() -> dict:
    """
    Get user info if authenticated.
    Uses the session_cookies stored during sso_callback.
    """
    try:
        with httpx.Client(base_url=BACKEND_BASE_URL, cookies=session_cookies) as client:
            resp = client.get("/auth/me")
            result = resp.json()
            if resp.status_code == 200:
                logger.info(
                    f"User info retrieved: "
                    f"{result.get('user', {}).get('email', 'unknown')}"
                )
            else:
                logger.debug(f"Not authenticated or error: {result}")
            return result
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        return {"error": f"me failed: {str(e)}"}


@mcp.tool()
def sso_logout() -> dict:
    """
    Logout and clear MCP agent session cookies.
    """
    try:
        with httpx.Client(base_url=BACKEND_BASE_URL, cookies=session_cookies) as client:
            resp = client.post("/auth/logout")
            session_cookies.clear()
            logger.info("User logged out, session cleared")
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"Logout response parse error: {e}")
                return {"error": "logout failed"}
    except Exception as e:
        logger.error(f"Connection error during logout: {e}")
        return {"error": f"connection_error: {str(e)}"}


# ---------------------------------------------------------------------------
# HTTP endpoints for your frontend (call these from the HTML)
# ---------------------------------------------------------------------------


@app.post("/sso_login")
async def sso_login_http(request: Request):
    """
    Browser-accessible endpoint: POST /sso_login
    """
    logger.info("HTTP /sso_login called")
    result = sso_login()
    status_code = 200 if "error" not in result else 500
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_callback")
async def sso_callback_http(request: Request):
    """
    Browser-accessible endpoint: POST /sso_callback
    Body: { "code": "...", "state": "..."? }
    """
    logger.info("HTTP /sso_callback called")
    body = await request.json()
    code = body.get("code")
    state = body.get("state")

    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    result = sso_callback(code=code, state=state)
    status_code = 200 if result.get("status") == "OK" and "error" not in result else 500
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_me")
async def sso_me_http(request: Request):
    """
    Browser-accessible endpoint: POST /sso_me
    """
    logger.info("HTTP /sso_me called")
    result = sso_me()
    status_code = 200 if "user" in result else 401
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_logout")
async def sso_logout_http(request: Request):
    """
    Browser-accessible endpoint: POST /sso_logout
    """
    logger.info("HTTP /sso_logout called")
    result = sso_logout()
    status_code = 200 if result.get("status") == "ok" else 500
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# Mount MCP app at /mcp for LLM clients (Streamable HTTP)
# ---------------------------------------------------------------------------

# Important: do NOT mount at "/" or you'll hide /sso_login etc.
mcp_app = mcp.http_app()  # default path; we'll mount under /mcp
app.mount("/mcp", mcp_app)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting MCP SSO Server on port 8090")
    logger.info(f"Backend URL: {BACKEND_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8090)
