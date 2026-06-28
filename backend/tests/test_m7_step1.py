"""Tests for M7 Step 1: shopping_list_items table, CRUD service and endpoints.

Coverage
--------
- Add manual item (definition-linked + free-text).
- Cross-field name/definition guard (neither → 422 validation.invalid_input).
- Definition existence check (missing definition_id → 404 item_definition.not_found).
- Edit (PATCH semantics — model_fields_set; only supplied fields updated).
- Check-off stamps purchased_at (non-null); uncheck clears it.
- Clear-purchased deletes all checked items; returns correct count.
- 404 (shopping_list.not_found) on PATCH / check / uncheck / DELETE for missing id.
- Permission gating: viewer → 403 on mutations; 200 on GET.
- Name / unit resolution: definition-linked rows show definition's current name/unit;
  free-text rows show the row's own name/unit.
- include_purchased query param.
- Migration 0033 upgrade + downgrade cleanly.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# Fixture infrastructure
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> Generator[None]:
    """Reset lru_cache on get_settings / get_engine before and after each test."""
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture()
def temp_db(monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Temp-file SQLite DB; patches DATABASE_URL so get_engine() uses it."""
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_m7_step1_")
    os.close(fd)
    db_path = Path(path_str)
    db_path.unlink()
    url = f"sqlite:///{path_str}"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-m7-step1")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    yield db_path
    if db_path.exists():
        db_path.unlink()


def _reload_all_models() -> None:
    """Reload model modules to pick up fresh DB engine after monkeypatch."""
    import app.db.base as db_base_mod
    import app.models.app_config as app_config_mod
    import app.models.attachment as attachment_mod
    import app.models.audit_log as audit_log_mod
    import app.models.barcode as barcode_mod
    import app.models.category as cat_mod
    import app.models.household as hh_mod
    import app.models.item_definition as idef_mod
    import app.models.item_kind as ikind_mod
    import app.models.location as loc_mod
    import app.models.media_file as media_file_mod
    import app.models.note as note_mod
    import app.models.notification as notif_mod
    import app.models.session as sess_mod
    import app.models.setting as setting_mod
    import app.models.shopping_list_item as sli_mod
    import app.models.stock_instance as stock_instance_mod
    import app.models.stock_movement as stock_movement_mod
    import app.models.tag as tag_mod
    import app.models.user as user_mod
    import app.models.user_token as user_token_mod

    importlib.reload(db_base_mod)
    importlib.reload(hh_mod)
    importlib.reload(user_mod)
    importlib.reload(sess_mod)
    importlib.reload(app_config_mod)
    importlib.reload(cat_mod)
    importlib.reload(ikind_mod)
    importlib.reload(idef_mod)
    importlib.reload(stock_instance_mod)
    importlib.reload(stock_movement_mod)
    importlib.reload(loc_mod)
    importlib.reload(setting_mod)
    importlib.reload(notif_mod)
    importlib.reload(media_file_mod)
    importlib.reload(attachment_mod)
    importlib.reload(tag_mod)
    importlib.reload(note_mod)
    importlib.reload(barcode_mod)
    importlib.reload(user_token_mod)
    importlib.reload(audit_log_mod)
    importlib.reload(sli_mod)


def _seed_kinds(engine: object) -> None:
    """Seed item kinds (required by item definitions)."""
    from sqlalchemy.orm import sessionmaker as SM

    from app.models.item_kind import ItemKind

    factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
    db = factory()
    try:
        for code, name in [
            ("durable", "Durable"),
            ("consumable", "Consumable"),
            ("perishable", "Perishable"),
        ]:
            db.add(ItemKind(code=code, name=name, is_system=True))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def base_client(
    temp_db: Path,  # noqa: ARG001
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, object]]:
    """TestClient + engine with schema created but no users."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _reload_all_models()

    from app.config import get_settings
    from app.db.base import Base, get_engine
    from app.main import create_app

    get_settings.cache_clear()
    engine = get_engine()
    Base.metadata.create_all(engine)
    _seed_kinds(engine)
    app = create_app()

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client, engine

    drop_all_sqlite(Base, engine)


def _create_user_and_login(
    engine: object,
    client: TestClient,
    email: str,
    password: str,
    role: str = "admin",
) -> None:
    """Insert a user with the given role and log in."""
    from sqlalchemy.orm import sessionmaker as SM

    from app.auth.passwords import hash_password
    from app.repositories.user import UserRepository

    factory = SM(bind=engine, autocommit=False, autoflush=False)  # type: ignore[arg-type]
    db = factory()
    try:
        repo = UserRepository(db)
        repo.create(email=email, password_hash=hash_password(password), role=role)
        db.commit()
    finally:
        db.close()

    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.json()}"


@pytest.fixture()
def admin_client(base_client: tuple[TestClient, object]) -> TestClient:
    """TestClient authenticated as an admin user."""
    client, engine = base_client
    _create_user_and_login(engine, client, "admin@test.com", "adminpass", "admin")
    return client


@pytest.fixture()
def viewer_client(base_client: tuple[TestClient, object]) -> TestClient:
    """TestClient with two users: admin (creates data) and viewer (test subject)."""
    client, engine = base_client
    _create_user_and_login(engine, client, "admin@test.com", "adminpass", "admin")
    return client


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def _create_definition(
    client: TestClient,
    name: str = "Widget",
    unit: str = "pcs",
    tracking_mode: str = "exact",
) -> dict:  # type: ignore[type-arg]
    resp = client.post(
        "/api/definitions",
        json={"name": name, "unit": unit, "stock_tracking_mode": tracking_mode},
    )
    assert resp.status_code == 201, f"create_definition failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _add_item(client: TestClient, payload: dict) -> dict:  # type: ignore[type-arg]
    resp = client.post("/api/shopping-list", json=payload)
    assert resp.status_code == 201, f"add_item failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _list_items(client: TestClient, include_purchased: bool = False) -> list[dict]:  # type: ignore[type-arg]
    params = {"include_purchased": "true" if include_purchased else "false"}
    resp = client.get("/api/shopping-list", params=params)
    assert resp.status_code == 200, f"list_items failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 1. Add manual items (definition-linked + free-text)
# ---------------------------------------------------------------------------


class TestAddManualItem:
    """POST /shopping-list — happy paths."""

    def test_add_free_text_item(self, admin_client: TestClient) -> None:
        """Free-text item: name is required, no definition_id."""
        item = _add_item(
            admin_client, {"name": "Paper towels", "desired_quantity": "2", "unit": "rolls"}
        )
        assert item["source"] == "manual"
        assert item["definition_id"] is None
        assert item["name"] == "Paper towels"
        assert item["unit"] == "rolls"
        assert item["desired_quantity"] is not None
        assert item["purchased_at"] is None  # open
        assert "id" in item
        assert "created_at" in item
        assert "updated_at" in item

    def test_add_definition_linked_item(self, admin_client: TestClient) -> None:
        """Definition-linked item: name/unit resolved live from definition."""
        defn = _create_definition(admin_client, "Milk", "L")
        item = _add_item(admin_client, {"definition_id": defn["id"], "desired_quantity": "2"})
        assert item["source"] == "manual"
        assert item["definition_id"] == defn["id"]
        # Name and unit resolved live from the definition.
        assert item["name"] == "Milk"
        assert item["unit"] == "L"
        assert item["purchased_at"] is None

    def test_add_item_with_note(self, admin_client: TestClient) -> None:
        """Note is optional but stored correctly."""
        item = _add_item(admin_client, {"name": "Salt", "note": "Low sodium preferred"})
        assert item["note"] == "Low sodium preferred"

    def test_add_definition_linked_name_not_snapshotted(self, admin_client: TestClient) -> None:
        """For definition-linked rows, name is resolved live (row's name field is NULL)."""
        defn = _create_definition(admin_client, "Original Name", "kg")
        item = _add_item(admin_client, {"definition_id": defn["id"]})
        # Name is resolved from definition; row stores NULL for name.
        assert item["name"] == "Original Name"
        assert item["unit"] == "kg"


# ---------------------------------------------------------------------------
# 2. Cross-field name/definition guard
# ---------------------------------------------------------------------------


class TestCrossFieldGuard:
    """Neither definition_id nor name → 422 validation.invalid_input."""

    def test_no_name_no_definition_returns_422(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list", json={})
        assert resp.status_code == 422
        assert resp.json()["code"] == "validation.invalid_input"

    def test_null_name_null_definition_returns_422(self, admin_client: TestClient) -> None:
        resp = admin_client.post(
            "/api/shopping-list",
            json={"name": None, "definition_id": None},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "validation.invalid_input"

    def test_empty_name_no_definition_returns_422(self, admin_client: TestClient) -> None:
        """Empty string name is treated as absent (falsy)."""
        resp = admin_client.post(
            "/api/shopping-list",
            json={"name": "", "definition_id": None},
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "validation.invalid_input"

    def test_name_alone_is_accepted(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list", json={"name": "Paper"})
        assert resp.status_code == 201

    def test_definition_alone_is_accepted(self, admin_client: TestClient) -> None:
        defn = _create_definition(admin_client, "Cheese")
        resp = admin_client.post("/api/shopping-list", json={"definition_id": defn["id"]})
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 3. Definition existence check
# ---------------------------------------------------------------------------


class TestDefinitionExistence:
    """Missing definition_id → 404 item_definition.not_found."""

    def test_missing_definition_returns_404(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list", json={"definition_id": 99999})
        assert resp.status_code == 404
        assert resp.json()["code"] == "item_definition.not_found"


# ---------------------------------------------------------------------------
# 4. Edit (PATCH semantics)
# ---------------------------------------------------------------------------


class TestEditItem:
    """PATCH /shopping-list/{id} — only supplied fields are updated."""

    def test_edit_desired_quantity(self, admin_client: TestClient) -> None:
        from decimal import Decimal

        item = _add_item(admin_client, {"name": "Sugar", "desired_quantity": "1"})
        resp = admin_client.patch(
            f"/api/shopping-list/{item['id']}", json={"desired_quantity": "3"}
        )
        assert resp.status_code == 200
        # Decimal serialized as string; compare numerically.
        assert Decimal(resp.json()["desired_quantity"]) == Decimal("3")
        # name unchanged
        assert resp.json()["name"] == "Sugar"

    def test_edit_name(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Old name"})
        resp = admin_client.patch(f"/api/shopping-list/{item['id']}", json={"name": "New name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New name"

    def test_edit_note(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Bread", "note": "Whole grain"})
        resp = admin_client.patch(f"/api/shopping-list/{item['id']}", json={"note": "Sourdough"})
        assert resp.status_code == 200
        assert resp.json()["note"] == "Sourdough"

    def test_edit_only_note_leaves_name_unchanged(self, admin_client: TestClient) -> None:
        """PATCH semantics: only supplied fields change; others stay the same."""
        item = _add_item(admin_client, {"name": "Coffee", "note": "Original note"})
        resp = admin_client.patch(f"/api/shopping-list/{item['id']}", json={"note": "Updated note"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Coffee"  # unchanged
        assert data["note"] == "Updated note"  # updated

    def test_edit_missing_item_returns_404(self, admin_client: TestClient) -> None:
        resp = admin_client.patch("/api/shopping-list/99999", json={"note": "ghost"})
        assert resp.status_code == 404
        assert resp.json()["code"] == "shopping_list.not_found"

    def test_updated_at_changes_after_patch(self, admin_client: TestClient) -> None:
        """updated_at must advance after a PATCH."""
        import time

        item = _add_item(admin_client, {"name": "Tea"})
        time.sleep(1.1)  # SQLite time resolution is 1s
        resp = admin_client.patch(f"/api/shopping-list/{item['id']}", json={"note": "updated"})
        assert resp.status_code == 200
        assert resp.json()["updated_at"] > item["updated_at"]


# ---------------------------------------------------------------------------
# 5. Check-off stamps purchased_at; uncheck clears it
# ---------------------------------------------------------------------------


class TestCheckOffUncheck:
    """POST /shopping-list/{id}/check and /uncheck."""

    def test_check_off_stamps_purchased_at(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Butter"})
        assert item["purchased_at"] is None

        resp = admin_client.post(f"/api/shopping-list/{item['id']}/check")
        assert resp.status_code == 200
        data = resp.json()
        # Step 3: response is now ShoppingListCheckResponse {item, created_instance_id}.
        assert data["item"]["purchased_at"] is not None
        # Item is still there (not deleted on check-off).
        assert data["item"]["id"] == item["id"]
        # No intake body → no lot created.
        assert data["created_instance_id"] is None

    def test_uncheck_clears_purchased_at(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Flour"})
        admin_client.post(f"/api/shopping-list/{item['id']}/check")

        resp = admin_client.post(f"/api/shopping-list/{item['id']}/uncheck")
        assert resp.status_code == 200
        assert resp.json()["purchased_at"] is None

    def test_check_missing_item_returns_404(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list/99999/check")
        assert resp.status_code == 404
        assert resp.json()["code"] == "shopping_list.not_found"

    def test_uncheck_missing_item_returns_404(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list/99999/uncheck")
        assert resp.status_code == 404
        assert resp.json()["code"] == "shopping_list.not_found"

    def test_check_then_uncheck_round_trip(self, admin_client: TestClient) -> None:
        """Check off then uncheck should leave the item open again."""
        item = _add_item(admin_client, {"name": "Oil"})
        admin_client.post(f"/api/shopping-list/{item['id']}/check")
        admin_client.post(f"/api/shopping-list/{item['id']}/uncheck")

        items = _list_items(admin_client)
        ids = [i["id"] for i in items]
        assert item["id"] in ids

    def test_checked_items_excluded_from_default_list(self, admin_client: TestClient) -> None:
        """Default list (include_purchased=false) excludes checked items."""
        item = _add_item(admin_client, {"name": "Vinegar"})
        admin_client.post(f"/api/shopping-list/{item['id']}/check")

        items = _list_items(admin_client, include_purchased=False)
        ids = [i["id"] for i in items]
        assert item["id"] not in ids

    def test_checked_items_included_when_include_purchased(self, admin_client: TestClient) -> None:
        """include_purchased=true includes checked items."""
        item = _add_item(admin_client, {"name": "Soy sauce"})
        admin_client.post(f"/api/shopping-list/{item['id']}/check")

        items = _list_items(admin_client, include_purchased=True)
        ids = [i["id"] for i in items]
        assert item["id"] in ids


# ---------------------------------------------------------------------------
# 6. Clear-purchased
# ---------------------------------------------------------------------------


class TestClearPurchased:
    """POST /shopping-list/clear-purchased."""

    def test_clear_purchased_deletes_checked_items(self, admin_client: TestClient) -> None:
        a = _add_item(admin_client, {"name": "Rice"})
        b = _add_item(admin_client, {"name": "Pasta"})
        c = _add_item(admin_client, {"name": "Lentils"})

        # Check off a and b; leave c open.
        admin_client.post(f"/api/shopping-list/{a['id']}/check")
        admin_client.post(f"/api/shopping-list/{b['id']}/check")

        resp = admin_client.post("/api/shopping-list/clear-purchased")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 2

        # Only c remains.
        remaining = _list_items(admin_client, include_purchased=True)
        remaining_ids = [i["id"] for i in remaining]
        assert a["id"] not in remaining_ids
        assert b["id"] not in remaining_ids
        assert c["id"] in remaining_ids

    def test_clear_purchased_when_none_checked_returns_zero(self, admin_client: TestClient) -> None:
        _add_item(admin_client, {"name": "Oats"})
        resp = admin_client.post("/api/shopping-list/clear-purchased")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 0

    def test_clear_purchased_empty_list_returns_zero(self, admin_client: TestClient) -> None:
        resp = admin_client.post("/api/shopping-list/clear-purchased")
        assert resp.status_code == 200
        assert resp.json()["deleted_count"] == 0


# ---------------------------------------------------------------------------
# 7. Delete
# ---------------------------------------------------------------------------


class TestDeleteItem:
    """DELETE /shopping-list/{id}."""

    def test_delete_item_returns_204(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Thyme"})
        resp = admin_client.delete(f"/api/shopping-list/{item['id']}")
        assert resp.status_code == 204

    def test_deleted_item_no_longer_listed(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Sage"})
        admin_client.delete(f"/api/shopping-list/{item['id']}")

        items = _list_items(admin_client, include_purchased=True)
        assert all(i["id"] != item["id"] for i in items)

    def test_delete_missing_item_returns_404(self, admin_client: TestClient) -> None:
        resp = admin_client.delete("/api/shopping-list/99999")
        assert resp.status_code == 404
        assert resp.json()["code"] == "shopping_list.not_found"


# ---------------------------------------------------------------------------
# 8. Permission gating (M6)
# ---------------------------------------------------------------------------


class TestPermissionGating:
    """viewer → 403 on mutations; viewer can read (GET)."""

    def _make_viewer_client(self, base_client: tuple[TestClient, object]) -> TestClient:
        """Create an admin, add some data, then switch to a viewer session."""
        client, engine = base_client

        # Create admin and add a list item.
        _create_user_and_login(engine, client, "admin2@test.com", "adminpass", "admin")
        _add_item(client, {"name": "Admin item"})

        # Create viewer and log in (same TestClient, new session replaces admin cookie).
        _create_user_and_login(engine, client, "viewer@test.com", "viewerpass", "viewer")
        return client

    def test_viewer_can_get_list(self, base_client: tuple[TestClient, object]) -> None:
        client = self._make_viewer_client(base_client)
        resp = client.get("/api/shopping-list")
        assert resp.status_code == 200

    def test_viewer_cannot_add_item(self, base_client: tuple[TestClient, object]) -> None:
        client = self._make_viewer_client(base_client)
        resp = client.post("/api/shopping-list", json={"name": "Viewer item"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_viewer_cannot_check_off(self, base_client: tuple[TestClient, object]) -> None:
        client, engine = base_client
        _create_user_and_login(engine, client, "admin3@test.com", "adminpass", "admin")
        item = _add_item(client, {"name": "To check"})
        _create_user_and_login(engine, client, "viewer2@test.com", "viewerpass", "viewer")

        resp = client.post(f"/api/shopping-list/{item['id']}/check")
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_viewer_cannot_uncheck(self, base_client: tuple[TestClient, object]) -> None:
        client, engine = base_client
        _create_user_and_login(engine, client, "admin4@test.com", "adminpass", "admin")
        item = _add_item(client, {"name": "To uncheck"})
        client.post(f"/api/shopping-list/{item['id']}/check")
        _create_user_and_login(engine, client, "viewer3@test.com", "viewerpass", "viewer")

        resp = client.post(f"/api/shopping-list/{item['id']}/uncheck")
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_viewer_cannot_delete(self, base_client: tuple[TestClient, object]) -> None:
        client, engine = base_client
        _create_user_and_login(engine, client, "admin5@test.com", "adminpass", "admin")
        item = _add_item(client, {"name": "To delete"})
        _create_user_and_login(engine, client, "viewer4@test.com", "viewerpass", "viewer")

        resp = client.delete(f"/api/shopping-list/{item['id']}")
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_viewer_cannot_patch(self, base_client: tuple[TestClient, object]) -> None:
        client, engine = base_client
        _create_user_and_login(engine, client, "admin6@test.com", "adminpass", "admin")
        item = _add_item(client, {"name": "To patch"})
        _create_user_and_login(engine, client, "viewer5@test.com", "viewerpass", "viewer")

        resp = client.patch(f"/api/shopping-list/{item['id']}", json={"note": "nope"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_viewer_cannot_clear_purchased(self, base_client: tuple[TestClient, object]) -> None:
        client = self._make_viewer_client(base_client)
        resp = client.post("/api/shopping-list/clear-purchased")
        assert resp.status_code == 403
        assert resp.json()["code"] == "auth.forbidden"

    def test_member_can_add_item(self, base_client: tuple[TestClient, object]) -> None:
        """member role has EDIT permission — should be able to mutate."""
        client, engine = base_client
        _create_user_and_login(engine, client, "member@test.com", "memberpass", "member")
        resp = client.post("/api/shopping-list", json={"name": "Member item"})
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# 9. Name / unit resolution
# ---------------------------------------------------------------------------


class TestNameUnitResolution:
    """Definition-linked rows resolve name/unit live from the definition."""

    def test_definition_linked_name_matches_definition(self, admin_client: TestClient) -> None:
        defn = _create_definition(admin_client, "Organic Milk", "L")
        item = _add_item(admin_client, {"definition_id": defn["id"]})
        # List also resolves correctly.
        items = _list_items(admin_client)
        found = next(i for i in items if i["id"] == item["id"])
        assert found["name"] == "Organic Milk"
        assert found["unit"] == "L"

    def test_free_text_name_and_unit_used_directly(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Pasta", "unit": "kg"})
        items = _list_items(admin_client)
        found = next(i for i in items if i["id"] == item["id"])
        assert found["name"] == "Pasta"
        assert found["unit"] == "kg"


# ---------------------------------------------------------------------------
# 10. List ordering (open first)
# ---------------------------------------------------------------------------


class TestListOrdering:
    """Open items come before purchased items when include_purchased=True."""

    def test_open_items_come_before_purchased(self, admin_client: TestClient) -> None:
        a = _add_item(admin_client, {"name": "A open"})
        b = _add_item(admin_client, {"name": "B purchased"})
        c = _add_item(admin_client, {"name": "C open"})

        admin_client.post(f"/api/shopping-list/{b['id']}/check")

        items = _list_items(admin_client, include_purchased=True)
        ids = [i["id"] for i in items]
        # a and c (open) must appear before b (purchased).
        idx_a = ids.index(a["id"])
        idx_b = ids.index(b["id"])
        idx_c = ids.index(c["id"])
        assert idx_a < idx_b
        assert idx_c < idx_b


# ---------------------------------------------------------------------------
# 11. source field is always 'manual' for user-created items
# ---------------------------------------------------------------------------


class TestSourceField:
    """All user-created items have source='manual'."""

    def test_manual_source_on_free_text(self, admin_client: TestClient) -> None:
        item = _add_item(admin_client, {"name": "Honey"})
        assert item["source"] == "manual"

    def test_manual_source_on_definition_linked(self, admin_client: TestClient) -> None:
        defn = _create_definition(admin_client, "Jam")
        item = _add_item(admin_client, {"definition_id": defn["id"]})
        assert item["source"] == "manual"


# ---------------------------------------------------------------------------
# 12. Migration round-trip (0033)
# ---------------------------------------------------------------------------


class TestMigration0033:
    """Migration 0033 (shopping_list_items) upgrades and downgrades cleanly."""

    def _run_alembic(self, *args: str, url: str) -> tuple[int, str]:
        import subprocess

        backend_root = Path(__file__).parent.parent
        env = {
            **os.environ,
            "SECRET_KEY": "test",
            "DATABASE_URL": url,
        }
        result = subprocess.run(
            [".venv/bin/alembic", *args],
            cwd=str(backend_root),
            env=env,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def test_migration_0033_up_down(self) -> None:
        """Upgrade through 0033; downgrade back to 0032 cleanly."""
        from sqlalchemy import create_engine as sa_create_engine
        from sqlalchemy import inspect as sa_inspect

        fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_mig_0033_")
        os.close(fd)
        db_path = Path(path_str)
        db_path.unlink()
        url = f"sqlite:///{path_str}"

        try:
            # Upgrade to HEAD (applies 0033).
            rc, output = self._run_alembic("upgrade", "head", url=url)
            assert rc == 0, f"alembic upgrade head failed:\n{output}"

            eng = sa_create_engine(url)
            tables = set(sa_inspect(eng).get_table_names())
            indexes = {
                idx["name"]
                for table in sa_inspect(eng).get_table_names()
                for idx in sa_inspect(eng).get_indexes(table)
            }
            eng.dispose()

            assert "shopping_list_items" in tables, (
                f"shopping_list_items table missing. Tables: {tables}"
            )
            assert "uq_shopping_list_one_auto_per_def" in indexes, (
                f"partial-unique index missing. Indexes: {indexes}"
            )
            assert "ix_shopping_list_items_purchased_at" in indexes, (
                f"purchased_at index missing. Indexes: {indexes}"
            )

            # Downgrade to 0032 — removes shopping_list_items.
            rc, output = self._run_alembic("downgrade", "0032", url=url)
            assert rc == 0, f"alembic downgrade to 0032 failed:\n{output}"

            eng = sa_create_engine(url)
            tables = set(sa_inspect(eng).get_table_names())
            eng.dispose()

            assert "shopping_list_items" not in tables, (
                "shopping_list_items table must be gone after downgrade to 0032"
            )
            assert "audit_log" in tables, "audit_log must survive downgrade to 0032"

        finally:
            if db_path.exists():
                db_path.unlink()
