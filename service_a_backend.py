import os
import jwt
import logging
import secrets
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, status, Cookie
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from msal import ConfidentialClientApplication
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS (demo: allow all - restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOWED_ORIGINS", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ENV VARS
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")  # IMPORTANT: for local, set to your HTML page URL
COOKIE_SECRET = os.getenv("COOKIE_SECRET", "changeme")
COOKIE_NAME = os.getenv("COOKIE_NAME", "sso_session")
AUTH_BASE_URL = os.getenv("AUTH_BASE_URL", "http://localhost:8000")

# Validate required environment variables
REQUIRED_ENV_VARS = {
    "TENANT_ID": TENANT_ID,
    "CLIENT_ID": CLIENT_ID,
    "CLIENT_SECRET": CLIENT_SECRET,
    "REDIRECT_URI": REDIRECT_URI,
}

missing_vars = [var for var, value in REQUIRED_ENV_VARS.items() if not value]
if missing_vars:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing_vars)}. "
        "Please set them in your .env file or environment."
    )

# MSAL config
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]  # Graph scope; openid/profile/OfflineAccess added by MSAL

# SSL verification (local only: can be disabled)
DISABLE_SSL_VERIFY = os.getenv("DISABLE_SSL_VERIFY", "False").lower() == "true"
if DISABLE_SSL_VERIFY:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Session state storage (demo: in-memory)
session_states = {}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/login")
def auth_login():
    """
    Start login: return a redirect to Azure authorize endpoint.
    The redirect_uri here MUST match REDIRECT_URI / Entra app config.
    """
    app_msal = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        verify=not DISABLE_SSL_VERIFY,
    )
    state = secrets.token_urlsafe(32)
    session_states[state] = True
    auth_url = app_msal.get_authorization_request_url(
        scopes=SCOPE,
        redirect_uri=REDIRECT_URI,
        state=state,
    )
    logger.info(f"Login initiated with state: {state[:10]}...")
    return RedirectResponse(auth_url)


@app.get("/auth/callback")
def auth_callback(
    request: Request,
    response: Response,
    code: Optional[str] = None,
    state: Optional[str] = None,
):
    """
    Exchange the auth code for tokens.

    NOTE: redirect_uri here MUST be the same value Azure used
    when issuing the code (i.e., your HTML page URL when
    using the front-end redirect pattern).
    """
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")

    # Validate state
    if state and state in session_states:
        session_states.pop(state)
        logger.info(f"State validated: {state[:10]}...")
    else:
        logger.warning(f"Invalid or missing state: {state}")

    app_msal = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        verify=not DISABLE_SSL_VERIFY,
    )

    result = app_msal.acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=REDIRECT_URI,
    )

    if "id_token" not in result:
        logger.error(f"Token acquisition failed: {result.get('error')}")
        raise HTTPException(status_code=401, detail="Failed to authenticate")

    logger.info("Token acquired successfully")

    # Set session cookie (demo: id_token only; use proper session in prod)
    resp = RedirectResponse(url="/post-login")
    resp.set_cookie(
        key=COOKIE_NAME,
        value=result["id_token"],
        httponly=True,
        # LOCAL DEV: set to False so it works over http://localhost
        secure=False,
        samesite="lax",
    )
    return resp


@app.get("/auth/me")
def auth_me(sso_session: Optional[str] = Cookie(None)):
    if not sso_session:
        logger.debug("No session cookie found")
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"error": "unauthenticated"})

    try:
        # Demo: decode without verification. In production, verify signature.
        decoded = jwt.decode(sso_session, options={"verify_signature": False})

        user_info = {
            "sub": decoded.get("sub", decoded.get("oid")),
            "email": decoded.get(
                "email",
                decoded.get("preferred_username", decoded.get("upn")),
            ),
            "name": decoded.get("name", "Unknown User"),
        }

        logger.info(f"User authenticated: {user_info.get('email', 'unknown')}")
        return {"user": user_info}
    except jwt.DecodeError as e:
        logger.error(f"JWT decode error: {e}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "invalid_token"},
        )
    except Exception as e:
        logger.error(f"Unexpected error in auth_me: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "internal_error"},
        )




@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    logger.info("User logged out")
    return {"status": "ok"}
