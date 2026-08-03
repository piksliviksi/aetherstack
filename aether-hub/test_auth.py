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


def test_tenancy_listing_is_scoped_to_the_caller_not_the_whole_org(tmp_path) -> None:
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
        alpha = tenancy.create_project(name="Alpha", owner_user_id="alice")
        beta = tenancy.create_project(name="Beta", owner_user_id="bob")
        tenancy.add_member(alpha["project_id"], "carol", "viewer")

        alice = auth.AuthContext(user_id="alice", auth_method="local_jwt", role="owner")
        carol = auth.AuthContext(user_id="carol", auth_method="local_jwt", role="viewer")
        eve = auth.AuthContext(user_id="eve", auth_method="local_jwt", role="member")
        admin = auth.AuthContext(user_id="platform-admin", auth_method="master_key", claims={"role": "admin"})
        desktop = auth.AuthContext(user_id="local", auth_method="desktop_open")

        # A member of exactly one project must not see the other org's projects.
        alice_ids = {p["project_id"] for p in tenancy.list_projects_for(alice)}
        assert alice_ids == {alpha["project_id"]}

        carol_ids = {p["project_id"] for p in tenancy.list_projects_for(carol)}
        assert carol_ids == {alpha["project_id"]}

        # A user with no membership anywhere sees nothing, not the whole org.
        assert tenancy.list_projects_for(eve) == []

        # Admin and desktop-open (single-user local mode) still see everything.
        admin_ids = {p["project_id"] for p in tenancy.list_projects_for(admin)}
        assert admin_ids == {alpha["project_id"], beta["project_id"]}
        desktop_ids = {p["project_id"] for p in tenancy.list_projects_for(desktop)}
        assert desktop_ids == {alpha["project_id"], beta["project_id"]}

        # snapshot_for() applies the same scoping to its "projects"/"project_count".
        snap = tenancy.snapshot_for(eve)
        assert snap["projects"] == []
        assert snap["project_count"] == 0
        # team_count/membership_count remain org-wide (no per-user secret there)
        assert snap["membership_count"] >= 3


def test_public_auth_config_shape() -> None:
    cfg = auth.public_auth_config()
    assert "require_auth" in cfg
    assert "oidc" in cfg
    assert cfg["token_endpoint"] == "/api/auth/token"


def test_is_admin_ignores_a_bare_role_claim_from_an_external_oidc_token() -> None:
    # Many IdPs project a single generic "role" attribute across every client
    # app. A viewer-level external token for some unrelated system must not
    # grant AetherStack platform admin just because its role claim happens to
    # say "admin" - only the namespaced aether_role claim (which only
    # mint_local_jwt ever sets, gated by the platform master key) may.
    oidc_ctx = auth.AuthContext(user_id="alice", auth_method="oidc", claims={"role": "admin"})
    assert oidc_ctx.is_admin() is False


def test_is_admin_ignores_a_bare_role_claim_on_a_local_jwt_too() -> None:
    ctx = auth.AuthContext(user_id="alice", auth_method="local_jwt", claims={"role": "admin"})
    assert ctx.is_admin() is False


def test_is_admin_requires_the_namespaced_aether_role_claim() -> None:
    ctx = auth.AuthContext(user_id="alice", auth_method="local_jwt", claims={"aether_role": "admin"})
    assert ctx.is_admin() is True


def test_is_admin_does_not_trust_a_user_id_string_match_alone() -> None:
    # A locally minted token for a user literally named "admin" with a
    # non-admin role must not become platform admin by virtue of the name.
    ctx = auth.AuthContext(user_id="admin", auth_method="local_jwt", claims={"aether_role": "viewer"})
    assert ctx.is_admin() is False


def test_mint_local_jwt_admin_role_is_granted_via_the_namespaced_claim() -> None:
    # The legitimate path: master-key-gated mint with role="admin" sets
    # aether_role, which is_admin() does trust.
    with mock.patch.dict(os.environ, {"AETHER_JWT_SECRET": "jwt-secret-for-tests-ccc"}, clear=False):
        minted = auth.mint_local_jwt(user_id="alice", role="admin")
        claims = auth._verify_local_hs256(minted["access_token"])
        ctx = auth._context_from_claims(claims, "local_jwt")
        assert ctx.is_admin() is True
