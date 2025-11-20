import os
import logging
from typing import Optional, Dict, Any

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://localhost:8000")

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sso_agent")

# In-memory cookie jar for the agent session (demo only)
session_cookies: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="SSO Agent")

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
# Helper Functions
# ---------------------------------------------------------------------------


def handle_sso_login() -> dict:
    """
    Start SSO login and return the Azure auth URL.
    Calls the backend /auth/login endpoint.
    """
    try:
        logger.info(f"Calling backend /auth/login at {BACKEND_BASE_URL}")
        with httpx.Client(base_url=BACKEND_BASE_URL, follow_redirects=False, timeout=30.0) as client:
            resp = client.get("/auth/login")
            
            logger.info(f"Backend response status: {resp.status_code}")
            logger.info(f"Backend response headers: {dict(resp.headers)}")
            
            if resp.is_redirect:
                auth_url = resp.headers.get("location")
                logger.info(f"SSO login initiated, auth_url: {auth_url}")
                return {"auth_url": auth_url}
            
            # Not a redirect - log response body for debugging
            try:
                body = resp.text
                logger.error(f"Backend /auth/login did not redirect. Status: {resp.status_code}, Body: {body}")
                
                # Try to parse as JSON
                try:
                    json_data = resp.json()
                    return {"error": f"backend_error: {json_data}"}
                except:
                    return {"error": f"backend_error: {body}"}
            except Exception as e:
                logger.error(f"Login failed (could not read response): {e}")
                return {"error": "login failed - no response body"}
                
    except httpx.ConnectError as e:
        logger.error(f"Cannot connect to backend at {BACKEND_BASE_URL}: {e}")
        return {"error": f"connection_error: Cannot reach backend. Is service_a_backend.py running on port 8000?"}
    except httpx.TimeoutException as e:
        logger.error(f"Timeout connecting to backend: {e}")
        return {"error": "connection_error: Backend timeout"}
    except Exception as e:
        logger.error(f"Unexpected error during login: {e}", exc_info=True)
        return {"error": f"connection_error: {str(e)}"}


def handle_sso_callback(code: str, state: Optional[str] = None) -> dict:
    """
    Handle SSO callback and store session cookies for the agent.
    Calls the backend /auth/callback endpoint.
    """
    try:
        logger.info(f"handle_sso_callback called with code: {code[:20]}...")
        params = {"code": code}
        if state:
            params["state"] = state

        with httpx.Client(base_url=BACKEND_BASE_URL, follow_redirects=False, timeout=30.0) as client:
            resp = client.get("/auth/callback", params=params)

            logger.info(f"Callback response status: {resp.status_code}")
            
            # Store cookies from backend in our in-memory jar
            if resp.cookies:
                session_cookies.clear()
                session_cookies.update(resp.cookies)
                logger.info(f"Session cookies stored: {len(resp.cookies)} cookie(s)")

            if resp.is_redirect:
                # Backend redirects to /post-login on success
                logger.info("Callback successful, session established")
                return {"status": "OK"}

            # If backend returned JSON instead of redirect, pass it through
            try:
                json_data = resp.json()
                logger.warning(f"Callback did not redirect, returned: {json_data}")
                return json_data
            except Exception as e:
                body = resp.text
                logger.error(f"Callback failed. Status: {resp.status_code}, Body: {body}")
                return {"error": f"callback failed: {body}"}
                
    except httpx.ConnectError as e:
        logger.error(f"Cannot connect to backend: {e}")
        return {"error": "connection_error: Cannot reach backend"}
    except Exception as e:
        logger.error(f"Connection error during callback: {e}", exc_info=True)
        return {"error": f"connection_error: {str(e)}"}


def handle_sso_me() -> dict:
    """
    Get user info if authenticated.
    Uses the session_cookies stored during callback.
    Calls the backend /auth/me endpoint.
    """
    try:
        logger.info(f"Calling /auth/me with {len(session_cookies)} cookies")
        with httpx.Client(base_url=BACKEND_BASE_URL, cookies=session_cookies, timeout=30.0) as client:
            resp = client.get("/auth/me")
            result = resp.json()
            
            if resp.status_code == 200:
                logger.info(
                    f"User info retrieved: "
                    f"{result.get('user', {}).get('email', 'unknown')}"
                )
            else:
                logger.debug(f"Not authenticated or error (status {resp.status_code}): {result}")
            return result
            
    except httpx.ConnectError as e:
        logger.error(f"Cannot connect to backend: {e}")
        return {"error": "connection_error: Cannot reach backend"}
    except Exception as e:
        logger.error(f"Error getting user info: {e}", exc_info=True)
        return {"error": f"me failed: {str(e)}"}


def handle_sso_logout() -> dict:
    """
    Logout and clear agent session cookies.
    Calls the backend /auth/logout endpoint.
    """
    try:
        logger.info("Logging out user")
        with httpx.Client(base_url=BACKEND_BASE_URL, cookies=session_cookies, timeout=30.0) as client:
            resp = client.post("/auth/logout")
            session_cookies.clear()
            logger.info("User logged out, session cleared")
            try:
                return resp.json()
            except Exception as e:
                logger.error(f"Logout response parse error: {e}")
                return {"status": "ok"}  # Still clear session even if parse fails
                
    except httpx.ConnectError as e:
        logger.error(f"Cannot connect to backend: {e}")
        session_cookies.clear()  # Clear local session anyway
        return {"error": "connection_error: Cannot reach backend (session cleared locally)"}
    except Exception as e:
        logger.error(f"Connection error during logout: {e}", exc_info=True)
        session_cookies.clear()  # Clear local session anyway
        return {"error": f"connection_error: {str(e)}"}
    

# ---------------------------------------------------------------------------
# HTTP endpoints for frontend
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "sso_agent",
        "backend_url": BACKEND_BASE_URL,
        "active_sessions": len(session_cookies)
    }


@app.post("/sso_login")
async def sso_login_endpoint(request: Request):
    """
    Frontend endpoint: POST /sso_login
    Returns the Azure authorization URL for SSO login.
    """
    logger.info("HTTP /sso_login called")
    result = handle_sso_login()
    status_code = 200 if "error" not in result else 500
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_callback")
async def sso_callback_endpoint(request: Request):
    """
    Frontend endpoint: POST /sso_callback
    Body: { "code": "...", "state": "..."? }
    Exchanges authorization code for tokens via backend.
    """
    logger.info("HTTP /sso_callback called")
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse request body: {e}")
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    
    code = body.get("code")
    state = body.get("state")

    if not code:
        return JSONResponse({"error": "missing code"}, status_code=400)

    result = handle_sso_callback(code=code, state=state)
    status_code = 200 if result.get("status") == "OK" and "error" not in result else 500
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_me")
async def sso_me_endpoint(request: Request):
    """
    Frontend endpoint: POST /sso_me
    Returns authenticated user information.
    """
    logger.info("HTTP /sso_me called")
    result = handle_sso_me()
    status_code = 200 if "user" in result else 401
    return JSONResponse(result, status_code=status_code)


@app.post("/sso_logout")
async def sso_logout_endpoint(request: Request):
    """
    Frontend endpoint: POST /sso_logout
    Logs out the user and clears session.
    """
    logger.info("HTTP /sso_logout called")
    result = handle_sso_logout()
    status_code = 200 if result.get("status") == "ok" else 500
    return JSONResponse(result, status_code=status_code)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("Starting SSO Agent on port 8090")
    logger.info(f"Backend URL: {BACKEND_BASE_URL}")
    logger.info("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8090)