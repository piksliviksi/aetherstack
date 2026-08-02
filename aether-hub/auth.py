"""Control-plane authentication for Team Server / Cloud (E1 / MULTI-USER M0).

Desktop default (AETHER_REQUIRE_AUTH unset/0): open loopback control plane as today.
Team/Cloud (AETHER_REQUIRE_AUTH=1 or AETHER_EDITION in team|cloud): every /api/*
request needs a valid bearer credential except public auth/health endpoints.

Accepted credentials when auth is required:
  1. Bearer <LITELLM_MASTER_KEY> — platform admin (local)
  2. Bearer <HS256 JWT> signed with AETHER_JWT_SECRET (or master key) — local tokens
  3. Bearer <OIDC access/id token> — when AETHER_OIDC_ISSUER (+ JWKS) is configured

This module does not implement full IdP UI; it validates tokens and builds AuthContext.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

# Optional OIDC RS256 support
try:
    import jwt as pyjwt  # PyJWT
    from jwt import PyJWKClient

    _HAS_PYJWT = True
except ImportError:  # pragma: no cover
    pyjwt = None  # type: ignore
    PyJWKClient = None  # type: ignore
    _HAS_PYJWT = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def edition() -> str:
    return (os.environ.get("AETHER_EDITION") or "desktop").strip().lower()


def require_auth() -> bool:
    """True when control-plane APIs must be authenticated."""
    if _env_bool("AETHER_REQUIRE_AUTH", False):
        return True
    return edition() in {"team", "cloud"}


def master_key() -> str:
    return (os.environ.get("LITELLM_MASTER_KEY") or "").strip()


def jwt_secret() -> str:
    return (os.environ.get("AETHER_JWT_SECRET") or master_key() or "").strip()


def oidc_issuer() -> str:
    return (os.environ.get("AETHER_OIDC_ISSUER") or "").strip().rstrip("/")


def oidc_audience() -> str:
    return (os.environ.get("AETHER_OIDC_AUDIENCE") or "aetherstack").strip()


def oidc_jwks_url() -> str:
    explicit = (os.environ.get("AETHER_OIDC_JWKS_URL") or "").strip()
    if explicit:
        return explicit
    iss = oidc_issuer()
    if not iss:
        return ""
    return f"{iss}/.well-known/jwks.json"


def local_token_ttl_sec() -> int:
    try:
        return max(60, min(86400 * 7, int(os.environ.get("AETHER_JWT_TTL_SEC", "86400"))))
    except ValueError:
        return 86400


@dataclass
class AuthContext:
    user_id: str
    email: str | None = None
    display_name: str | None = None
    tenant_id: str | None = None
    team_ids: list[str] = field(default_factory=list)
    project_id: str | None = None
    role: str | None = None  # owner|member|viewer for active project
    edition: str = "desktop"
    auth_method: str = "desktop_open"  # master_key|local_jwt|oidc|desktop_open
    claims: dict[str, Any] = field(default_factory=dict)

    def is_admin(self) -> bool:
        if self.auth_method == "master_key":
            return True
        if self.claims.get("role") == "admin" or self.claims.get("aether_role") == "admin":
            return True
        return self.user_id in {"admin", "platform-admin"}

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        # Never echo raw token material
        data.pop("claims", None)
        data["claims_keys"] = sorted(self.claims.keys())
        return data


def desktop_open_context() -> AuthContext:
    return AuthContext(
        user_id="local-operator",
        email=None,
        display_name="Local operator",
        edition=edition(),
        auth_method="desktop_open",
        role="owner",
    )


# Paths that remain reachable without a bearer when require_auth() is True.
_PUBLIC_API_EXACT = frozenset(
    {
        "/api/health",
        "/api/auth/config",
    }
)
_PUBLIC_API_PREFIXES = (
    # token mint is authenticated via body master key, not bearer
)


def is_public_api_path(method: str, path: str) -> bool:
    method = method.upper()
    path = path.rstrip("/") or "/"
    if path in _PUBLIC_API_EXACT:
        return True
    if method == "POST" and path == "/api/auth/token":
        return True
    return False


def is_static_or_ui_path(path: str) -> bool:
    path = path.rstrip("/") or "/"
    if path in {
        "/",
        "/index.html",
        "/simple",
        "/simple.html",
        "/advanced",
        "/advanced.html",
        "/graph",
        "/graph.html",
        "/aetherstack-icon.png",
        "/favicon.png",
    }:
        return True
    if path.startswith("/static/"):
        return True
    return False


def public_auth_config() -> dict[str, Any]:
    return {
        "edition": edition(),
        "require_auth": require_auth(),
        "oidc": {
            "enabled": bool(oidc_issuer()),
            "issuer": oidc_issuer() or None,
            "audience": oidc_audience() if oidc_issuer() else None,
            "client_id": (os.environ.get("AETHER_OIDC_CLIENT_ID") or "").strip() or None,
            "jwks_url": oidc_jwks_url() or None,
            "pyjwt_available": _HAS_PYJWT,
        },
        "local_jwt": {
            "enabled": bool(jwt_secret()),
            "ttl_sec": local_token_ttl_sec(),
        },
        "token_endpoint": "/api/auth/token",
        "me_endpoint": "/api/auth/me",
    }


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def mint_local_jwt(
    *,
    user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    tenant_id: str | None = None,
    team_ids: list[str] | None = None,
    role: str = "member",
    ttl_sec: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mint an HS256 local access token. Requires jwt_secret()."""
    secret = jwt_secret()
    if not secret:
        raise ValueError("AETHER_JWT_SECRET or LITELLM_MASTER_KEY required to mint tokens")
    now = int(time.time())
    exp = now + int(ttl_sec if ttl_sec is not None else local_token_ttl_sec())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": exp,
        "iss": "aetherstack-local",
        "aud": oidc_audience() or "aetherstack",
        "aether_role": role,
        "edition": edition(),
    }
    if email:
        payload["email"] = email
    if display_name:
        payload["name"] = display_name
    if tenant_id:
        payload["tenant_id"] = tenant_id
    if team_ids:
        payload["team_ids"] = list(team_ids)
    if extra_claims:
        payload.update(extra_claims)
    segments = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    )
    signing_input = f"{segments[0]}.{segments[1]}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    token = f"{segments[0]}.{segments[1]}.{_b64url_encode(sig)}"
    return {"access_token": token, "token_type": "Bearer", "expires_in": exp - now, "expires_at": exp}


def _verify_local_hs256(token: str) -> dict[str, Any] | None:
    secret = jwt_secret()
    if not secret or token.count(".") != 2:
        return None
    try:
        h_b64, p_b64, s_b64 = token.split(".")
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(s_b64)):
            return None
        header = json.loads(_b64url_decode(h_b64))
        if header.get("alg") != "HS256":
            return None
        payload = json.loads(_b64url_decode(p_b64))
        exp = int(payload.get("exp") or 0)
        if exp and time.time() > exp:
            return None
        iss = payload.get("iss")
        if iss and iss not in {"aetherstack-local", oidc_issuer()}:
            # Local mint always uses aetherstack-local
            if iss != "aetherstack-local":
                return None
        return payload if isinstance(payload, dict) else None
    except (ValueError, json.JSONDecodeError, KeyError):
        return None


_jwks_lock = threading.Lock()
_jwks_client: Any = None
_jwks_url_cached = ""


def _get_jwks_client():
    global _jwks_client, _jwks_url_cached
    url = oidc_jwks_url()
    if not url or not _HAS_PYJWT:
        return None
    with _jwks_lock:
        if _jwks_client is None or _jwks_url_cached != url:
            _jwks_client = PyJWKClient(url, cache_keys=True, lifespan=3600)
            _jwks_url_cached = url
        return _jwks_client


def _verify_oidc(token: str) -> dict[str, Any] | None:
    if not oidc_issuer():
        return None
    if not _HAS_PYJWT:
        return None
    client = _get_jwks_client()
    if client is None:
        return None
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        options = {"require": ["exp", "sub"]}
        kwargs: dict[str, Any] = {
            "algorithms": ["RS256", "ES256", "RS384", "RS512"],
            "issuer": oidc_issuer(),
            "options": options,
        }
        aud = oidc_audience()
        if aud:
            kwargs["audience"] = aud
        return pyjwt.decode(token, signing_key.key, **kwargs)
    except Exception:
        # Retry without audience if IdP omits aud (common for some access tokens)
        try:
            signing_key = client.get_signing_key_from_jwt(token)
            return pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "RS384", "RS512"],
                issuer=oidc_issuer(),
                options={"require": ["exp", "sub"], "verify_aud": False},
            )
        except Exception:
            return None


def _context_from_claims(claims: dict[str, Any], method: str) -> AuthContext:
    user_id = str(claims.get("sub") or claims.get("user_id") or "").strip()
    if not user_id:
        raise ValueError("token missing sub")
    team_ids = claims.get("team_ids") or claims.get("groups") or []
    if isinstance(team_ids, str):
        team_ids = [team_ids]
    if not isinstance(team_ids, list):
        team_ids = []
    return AuthContext(
        user_id=user_id,
        email=(str(claims["email"]) if claims.get("email") else None),
        display_name=(str(claims.get("name") or claims.get("preferred_username") or "") or None),
        tenant_id=(str(claims["tenant_id"]) if claims.get("tenant_id") else (
            str(claims["tid"]) if claims.get("tid") else None
        )),
        team_ids=[str(t) for t in team_ids],
        project_id=(str(claims["project_id"]) if claims.get("project_id") else None),
        role=(str(claims.get("aether_role") or claims.get("role") or "member")),
        edition=edition(),
        auth_method=method,
        claims=dict(claims),
    )


def authenticate_authorization_header(value: str | None) -> AuthContext | None:
    """Parse Authorization: Bearer … into AuthContext, or None if invalid/missing."""
    raw = (value or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    if not token:
        return None

    # 1) Platform master key
    mk = master_key()
    if mk and hmac.compare_digest(token, mk):
        return AuthContext(
            user_id="platform-admin",
            display_name="Platform admin",
            edition=edition(),
            auth_method="master_key",
            role="owner",
            claims={"role": "admin"},
        )

    # 2) Local HS256 JWT
    local_claims = _verify_local_hs256(token)
    if local_claims:
        try:
            return _context_from_claims(local_claims, "local_jwt")
        except ValueError:
            return None

    # 3) OIDC
    oidc_claims = _verify_oidc(token)
    if oidc_claims:
        try:
            return _context_from_claims(oidc_claims, "oidc")
        except ValueError:
            return None

    return None


def resolve_request_auth(
    *,
    method: str,
    path: str,
    authorization: str | None,
) -> tuple[AuthContext | None, str | None]:
    """
    Returns (context, error_code).
    - When auth not required: always desktop_open context, error None.
    - When public path: (None, None) — caller should not require context.
    - When required and ok: (ctx, None)
    - When required and fail: (None, "unauthorized")
    """
    path_n = path.rstrip("/") or "/"
    if not require_auth():
        return desktop_open_context(), None
    if is_static_or_ui_path(path_n):
        return None, None
    if not path_n.startswith("/api") and not path_n.startswith("/v1"):
        return None, None
    if is_public_api_path(method, path_n):
        return None, None
    # OpenAI façade keeps using gateway master key via its own check; still require
    # a valid control-plane credential when require_auth so /v1 is not a bypass.
    ctx = authenticate_authorization_header(authorization)
    if ctx is None:
        return None, "unauthorized"
    return ctx, None


def allow_non_loopback_bind() -> bool:
    """Non-loopback publish only when control-plane auth is enforced."""
    return require_auth()


def mint_token_from_master_request(body: dict[str, Any]) -> dict[str, Any]:
    """
    POST /api/auth/token body:
      { "master_key": "...", "user_id": "alice", "email": "...", "role": "member", ... }
    Or { "token": "<master_key>", ... } for convenience.
    """
    if not require_auth() and not _env_bool("AETHER_ALLOW_TOKEN_MINT", False):
        # Allow mint even on desktop if master key provided — useful for tests.
        pass
    supplied = str(body.get("master_key") or body.get("token") or "").strip()
    mk = master_key()
    if not mk or not supplied or not hmac.compare_digest(supplied, mk):
        raise PermissionError("invalid master key")
    user_id = str(body.get("user_id") or body.get("sub") or "user").strip() or "user"
    if user_id == "platform-admin":
        raise ValueError("user_id platform-admin is reserved")
    role = str(body.get("role") or "member").strip() or "member"
    if role not in {"owner", "member", "viewer", "admin"}:
        raise ValueError("role must be owner|member|viewer|admin")
    ttl = body.get("ttl_sec")
    return mint_local_jwt(
        user_id=user_id,
        email=(str(body["email"]) if body.get("email") else None),
        display_name=(str(body["display_name"]) if body.get("display_name") else None),
        tenant_id=(str(body["tenant_id"]) if body.get("tenant_id") else None),
        team_ids=list(body.get("team_ids") or []) or None,
        role=role,
        ttl_sec=int(ttl) if ttl is not None else None,
        extra_claims={"project_id": body["project_id"]} if body.get("project_id") else None,
    )
