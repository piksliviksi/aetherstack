"""E1 control-plane authentication tests."""
from __future__ import annotations

import os
from unittest import mock

import auth
import tenancy


def test_require_auth_from_edition_team() -> None:
    with mock.patch.dict(os.environ, {"AETHER_EDITION": "team", "AETHER_REQUIRE_AUTH": ""}, clear=False):
        # clear=False keeps other env; force empty require flag
        os.environ.pop("AETHER_REQUIRE_AUTH", None)
        assert auth.require_auth() is True
        assert auth.allow_non_loopback_bind() is True


def test_desktop_default_open() -> None:
    with mock.patch.dict(
        os.environ,
        {"AETHER_EDITION": "desktop", "AETHER_REQUIRE_AUTH": "0", "LITELLM_MASTER_KEY": "sk-test-master"},
        clear=False,
    ):
        ctx, err = auth.resolve_request_auth(
            method="GET",
            path="/api/discover",
            authorization=None,
        )
        assert err is None
        assert ctx is not None
        assert ctx.auth_method == "desktop_open"


def test_team_requires_bearer() -> None:
    with mock.patch.dict(
        os.environ,
        {
            "AETHER_EDITION": "team",
            "AETHER_REQUIRE_AUTH": "1",
            "LITELLM_MASTER_KEY": "sk-test-master-key-aaa",
            "AETHER_JWT_SECRET": "jwt-secret-for-tests-bbb",
        },
        clear=False,
    ):
        ctx, err = auth.resolve_request_auth(
            method="GET",
            path="/api/discover",
            authorization=None,
        )
        assert ctx is None
        assert err == "unauthorized"

        # health stays public
        ctx2, err2 = auth.resolve_request_auth(
            method="GET",
            path="/api/health",
            authorization=None,
        )
        assert err2 is None
        assert ctx2 is None


def test_master_key_and_local_jwt() -> None:
    with mock.patch.dict(
        os.environ,
        {
            "AETHER_EDITION": "team",
            "AETHER_REQUIRE_AUTH": "1",
            "LITELLM_MASTER_KEY": "sk-test-master-key-aaa",
            "AETHER_JWT_SECRET": "jwt-secret-for-tests-bbb",
            "AETHER_OIDC_AUDIENCE": "aetherstack",
        },
        clear=False,
    ):
        mk = auth.authenticate_authorization_header("Bearer sk-test-master-key-aaa")
        assert mk is not None
        assert mk.is_admin()
        assert mk.auth_method == "master_key"

        minted = auth.mint_local_jwt(user_id="alice", email="a@example.com", role="member")
        token = minted["access_token"]
        alice = auth.authenticate_authorization_header(f"Bearer {token}")
        assert alice is not None
        assert alice.user_id == "alice"
        assert alice.email == "a@example.com"
        assert alice.auth_method == "local_jwt"

        ctx, err = auth.resolve_request_auth(
            method="GET",
            path="/api/discover",
            authorization=f"Bearer {token}",
        )
        assert err is None
        assert ctx is not None
        assert ctx.user_id == "alice"


def test_mint_token_from_master_request() -> None:
    with mock.patch.dict(
        os.environ,
        {
            "AETHER_REQUIRE_AUTH": "1",
            "LITELLM_MASTER_KEY": "sk-test-master-key-aaa",
            "AETHER_JWT_SECRET": "jwt-secret-for-tests-bbb",
        },
        clear=False,
    ):
        out = auth.mint_token_from_master_request(
            {"master_key": "sk-test-master-key-aaa", "user_id": "bob", "role": "owner"}
        )
        assert "access_token" in out
        bob = auth.authenticate_authorization_header(f"Bearer {out['access_token']}")
        assert bob is not None and bob.user_id == "bob"

        try:
            auth.mint_token_from_master_request({"master_key": "wrong", "user_id": "x"})
            assert False, "expected PermissionError"
        except PermissionError:
            pass


def test_tenancy_acl(tmp_path) -> None:
    tenancy.reset_for_tests(tmp_path / "tenancy.json")
    with mock.patch.dict(
        os.environ,
        {
            "AETHER_REQUIRE_AUTH": "1",
            "LITELLM_MASTER_KEY": "sk-test-master-key-aaa",
            "AETHER_JWT_SECRET": "jwt-secret-for-tests-bbb",
        },
        clear=False,
    ):
        proj = tenancy.create_project(name="Alpha", owner_user_id="alice")
        pid = proj["project_id"]
        tenancy.add_member(pid, "bob", "member")
        tenancy.add_member(pid, "carol", "viewer")

        alice = auth.AuthContext(user_id="alice", auth_method="local_jwt", role="owner")
        bob = auth.AuthContext(user_id="bob", auth_method="local_jwt", role="member")
        carol = auth.AuthContext(user_id="carol", auth_method="local_jwt", role="viewer")
        eve = auth.AuthContext(user_id="eve", auth_method="local_jwt", role="member")

        assert tenancy.authorize_project(alice, pid, "owner") == "owner"
        assert tenancy.authorize_project(bob, pid, "member") == "member"
        try:
            tenancy.authorize_project(carol, pid, "member")
            assert False, "viewer should not pass member"
        except PermissionError:
            pass
        try:
            tenancy.authorize_project(eve, pid, "viewer")
            assert False, "non-member should fail"
        except PermissionError:
            pass

        admin = auth.AuthContext(
            user_id="platform-admin",
            auth_method="master_key",
            claims={"role": "admin"},
        )
        assert tenancy.authorize_project(admin, pid, "owner") == "owner"
        assert tenancy.memory_namespace_for_project(pid) == f"project:{pid}"


def test_public_auth_config_shape() -> None:
    cfg = auth.public_auth_config()
    assert "require_auth" in cfg
    assert "oidc" in cfg
    assert cfg["token_endpoint"] == "/api/auth/token"
