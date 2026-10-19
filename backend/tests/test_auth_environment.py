"""Sign-in environment surface: demo credentials and account provisioning.

CheckR is institution-controlled infrastructure. Two properties must hold no
matter how the deployment is configured:

* the seeded demo account is never advertised in production, and
* self-service account creation is closed unless it is deliberately enabled.
"""

from __future__ import annotations

from app.core.config import Settings
from tests.conftest import TEACHER


def _settings(**overrides) -> Settings:
    """Build an isolated Settings instance (init kwargs outrank env/.env)."""
    base = {
        "environment": "development",
        "seed_on_startup": True,
        "seed_teacher_email": "teacher@checkr.edu",
        "seed_teacher_password": "CheckR!2026",
        "expose_demo_credentials": None,
        "self_registration_enabled": False,
    }
    base.update(overrides)
    return Settings(**base)


# --------------------------------------------------------------------------- #
# Demo-credential policy (pure)
# --------------------------------------------------------------------------- #
class TestDemoCredentialPolicy:
    def test_development_advertises_the_seeded_account(self):
        s = _settings(environment="development")
        assert s.show_demo_credentials is True
        assert s.demo_credentials == ("teacher@checkr.edu", "CheckR!2026")

    def test_development_can_opt_out(self):
        s = _settings(environment="development", expose_demo_credentials=False)
        assert s.show_demo_credentials is False
        assert s.demo_credentials is None

    def test_credentials_are_withheld_when_seeding_is_off(self):
        # Advertising an account that was never created would be a lie.
        s = _settings(environment="development", seed_on_startup=False)
        assert s.demo_credentials is None

    def test_test_environment_is_quiet_by_default(self):
        s = _settings(environment="test")
        assert s.show_demo_credentials is False
        assert s.demo_credentials is None

    def test_production_never_exposes_credentials(self):
        s = _settings(environment="production")
        assert s.show_demo_credentials is False
        assert s.demo_credentials is None

    def test_production_ignores_an_explicit_opt_in(self):
        s = _settings(environment="production", expose_demo_credentials=True)
        assert s.show_demo_credentials is False
        assert s.demo_credentials is None

    def test_production_reports_the_ignored_setting(self):
        s = _settings(environment="production", expose_demo_credentials=True)
        assert any("EXPOSE_DEMO_CREDENTIALS" in w for w in s.warnings())


# --------------------------------------------------------------------------- #
# Public endpoint
# --------------------------------------------------------------------------- #
async def test_environment_endpoint_is_public_and_reports_registration(client):
    """No token required: the screen must know this before anyone signs in."""
    resp = await client.get("/api/auth/environment")
    assert resp.status_code == 200
    body = resp.json()
    assert body["environment"] == "test"
    # The suite opts into self-registration; seeding is off, so no demo hint.
    assert body["self_registration_enabled"] is True
    assert body["demo_credentials"] is None


async def test_environment_endpoint_exposes_demo_credentials_in_development(
    client, monkeypatch
):
    from app.api.routes import auth as auth_routes

    monkeypatch.setattr(auth_routes.settings, "environment", "development")
    monkeypatch.setattr(auth_routes.settings, "seed_on_startup", True)
    monkeypatch.setattr(auth_routes.settings, "seed_teacher_email", "teacher@checkr.edu")
    monkeypatch.setattr(auth_routes.settings, "seed_teacher_password", "CheckR!2026")

    body = (await client.get("/api/auth/environment")).json()
    assert body["demo_credentials"] == {
        "email": "teacher@checkr.edu",
        "password": "CheckR!2026",
    }


async def test_environment_endpoint_hides_demo_credentials_in_production(
    client, monkeypatch
):
    from app.api.routes import auth as auth_routes

    settings = auth_routes.settings
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "seed_on_startup", True)
    monkeypatch.setattr(settings, "expose_demo_credentials", True)

    body = (await client.get("/api/auth/environment")).json()
    assert body["environment"] == "production"
    assert body["demo_credentials"] is None


# --------------------------------------------------------------------------- #
# Account provisioning
# --------------------------------------------------------------------------- #
async def test_registration_is_rejected_when_disabled(client, monkeypatch):
    from app.api.routes import auth as auth_routes

    monkeypatch.setattr(auth_routes.settings, "self_registration_enabled", False)

    resp = await client.post("/api/auth/register", json=TEACHER)
    assert resp.status_code == 403
    assert "institution" in resp.json()["detail"].lower()


async def test_registration_succeeds_when_explicitly_enabled(client):
    resp = await client.post("/api/auth/register", json=TEACHER)
    assert resp.status_code == 201, resp.text


async def test_provisioned_account_can_sign_in_while_registration_is_closed(
    client, monkeypatch, db
):
    """An administrator-provisioned account works even though sign-up is closed."""
    from app.api.routes import auth as auth_routes
    from app.services import auth_service

    monkeypatch.setattr(auth_routes.settings, "self_registration_enabled", False)

    # Out-of-band provisioning (seed script / administrator console).
    await auth_service.register_user(
        db,
        email=TEACHER["email"],
        full_name=TEACHER["full_name"],
        password=TEACHER["password"],
        department=TEACHER["department"],
    )
    await db.commit()

    assert (await client.post("/api/auth/register", json=TEACHER)).status_code == 403
    resp = await client.post(
        "/api/auth/login",
        json={"email": TEACHER["email"], "password": TEACHER["password"]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == TEACHER["email"]
