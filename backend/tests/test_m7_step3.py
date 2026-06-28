"""Tests for M7 Step 3: shopping-list check-off with stock intake.

Required coverage (M7.md §5 / §9 Step 3 / §10 Step 3):

Check-off → intake algorithm (§4.2)
- check-off without intake only stamps purchased_at; created_instance_id=None
- check-off with intake creates a ledger-backed lot (quantity == SUM(deltas))
- intake quantity defaults to desired_quantity when intake.quantity omitted
- both NULL (no intake.quantity, no desired_quantity) → validation.invalid_input (422)
- non-'exact' definition → stock.movement_not_applicable (409)
- atomic rollback: intake failure (bad location_id) → purchased_at stays NULL,
  no lot or movement created
- free-text row (no definition_id) + intake body → just stamps, created_instance_id=None
- post-intake reconcile: the now-recovered definition drops off the open list

Atomicity guarantee
- The service performs StockInstanceService.create BEFORE stamping purchased_at.
  If create raises, purchased_at is never set (one transaction, committed only
  by the route after the service returns successfully).
"""

from __future__ import annotations

import importlib
import os
import tempfile
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# Fixture infrastructure (mirrors test_m7_step2.py)
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
    fd, path_str = tempfile.mkstemp(suffix=".db", prefix="omniventory_m7_step3_")
    os.close(fd)
    db_path = Path(path_str)
    db_path.unlink()
    url = f"sqlite:///{path_str}"
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-m7-step3")
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

    for mod in (
        db_base_mod,
        hh_mod,
        user_mod,
        sess_mod,
        app_config_mod,
        cat_mod,
        ikind_mod,
        idef_mod,
        loc_mod,
        stock_instance_mod,
        stock_movement_mod,
        setting_mod,
        notif_mod,
        audit_log_mod,
        sli_mod,
        media_file_mod,
        attachment_mod,
        tag_mod,
        note_mod,
        barcode_mod,
        user_token_mod,
    ):
        importlib.reload(mod)


def _seed_kinds(engine: Any) -> None:
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
) -> Generator[tuple[TestClient, Any]]:
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
    engine: Any,
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
def admin_client(base_client: tuple[TestClient, Any]) -> tuple[TestClient, Any]:
    """TestClient + engine authenticated as an admin user."""
    client, engine = base_client
    _create_user_and_login(engine, client, "admin@test.com", "adminpass", "admin")
    return client, engine


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def _create_definition(
    client: TestClient,
    *,
    name: str = "Widget",
    unit: str = "pcs",
    tracking_mode: str = "exact",
    min_stock: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "unit": unit,
        "stock_tracking_mode": tracking_mode,
    }
    if min_stock is not None:
        payload["min_stock"] = min_stock
    resp = client.post("/api/definitions", json=payload)
    assert resp.status_code == 201, f"create_definition failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _create_location(client: TestClient, name: str = "Pantry") -> dict[str, Any]:
    resp = client.post("/api/locations", json={"name": name})
    assert resp.status_code == 201, f"create_location failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _create_instance(
    client: TestClient, definition_id: int, location_id: int | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"definition_id": definition_id}
    if location_id is not None:
        payload["location_id"] = location_id
    resp = client.post("/api/instances", json=payload)
    assert resp.status_code == 201, f"create_instance failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _intake_movement(client: TestClient, instance_id: int, quantity: str) -> None:
    """Record a stock intake on an existing instance (to set up stock level)."""
    resp = client.post(f"/api/instances/{instance_id}/intake", json={"quantity": quantity})
    assert resp.status_code == 200, f"intake_movement failed: {resp.json()}"


def _add_item(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    resp = client.post("/api/shopping-list", json=payload)
    assert resp.status_code == 201, f"add_item failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _list_items(client: TestClient, *, include_purchased: bool = False) -> list[dict[str, Any]]:
    params = {"include_purchased": "true" if include_purchased else "false"}
    resp = client.get("/api/shopping-list", params=params)
    assert resp.status_code == 200
    return resp.json()  # type: ignore[return-value]


def _refresh(client: TestClient) -> list[dict[str, Any]]:
    resp = client.post("/api/shopping-list/refresh")
    assert resp.status_code == 200, f"refresh failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _get_movements_for_instance(client: TestClient, instance_id: int) -> list[dict[str, Any]]:
    """Return all movements for an instance (used to verify ledger-derivation)."""
    resp = client.get(f"/api/instances/{instance_id}/movements")
    assert resp.status_code == 200, f"get_movements failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _get_instance(client: TestClient, instance_id: int) -> dict[str, Any]:
    resp = client.get(f"/api/instances/{instance_id}")
    assert resp.status_code == 200, f"get_instance failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


def _list_instances(client: TestClient) -> list[dict[str, Any]]:
    resp = client.get("/api/instances")
    assert resp.status_code == 200, f"list_instances failed: {resp.json()}"
    return resp.json()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 1. Check-off without intake (backward-compatible Step 1 behaviour)
# ---------------------------------------------------------------------------


class TestCheckOffWithoutIntake:
    """POST /shopping-list/{id}/check with no body — stamps only, no lot created."""

    def test_check_off_without_body_stamps_only(self, admin_client: tuple[TestClient, Any]) -> None:
        """No body → purchased_at stamped, created_instance_id=None."""
        client, _ = admin_client
        item = _add_item(client, {"name": "Paper towels"})

        resp = client.post(f"/api/shopping-list/{item['id']}/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["purchased_at"] is not None
        assert data["item"]["id"] == item["id"]
        assert data["created_instance_id"] is None

    def test_check_off_with_empty_intake_stamps_only(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """Body with intake=null → only stamps purchased_at, no lot created."""
        client, _ = admin_client
        item = _add_item(client, {"name": "Soap"})

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["purchased_at"] is not None
        assert data["created_instance_id"] is None

    def test_free_text_row_plus_intake_body_just_stamps(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """A free-text row (no definition_id) + intake body → just stamps.

        M7 §4.2: intake is meaningful only for a definition-linked row.
        A manual free-text row has no definition_id so the intake is ignored.
        """
        client, _ = admin_client
        item = _add_item(client, {"name": "Paper towels"})
        assert item["definition_id"] is None

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"quantity": "5"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["item"]["purchased_at"] is not None
        # No lot should be created for a free-text row.
        assert data["created_instance_id"] is None


# ---------------------------------------------------------------------------
# 2. Check-off with intake — happy paths
# ---------------------------------------------------------------------------


class TestCheckOffWithIntake:
    """POST /shopping-list/{id}/check with {intake: {...}} on an exact-mode definition."""

    def test_intake_creates_ledger_backed_lot(self, admin_client: tuple[TestClient, Any]) -> None:
        """Intake creates a new lot whose quantity is ledger-derived (SUM(deltas)).

        Verifies the roadmap §2.3 red line: quantity is never blind-set;
        it comes from the initial intake movement via StockInstanceService.create.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Coffee", unit="kg", tracking_mode="exact")

        # Create a shopping-list item linked to the definition.
        item = _add_item(
            client,
            {"definition_id": defn["id"], "desired_quantity": "2"},
        )

        # Check off with explicit intake quantity.
        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"quantity": "3"}},
        )
        assert resp.status_code == 200
        data = resp.json()

        # The response carries the new lot's id.
        created_id = data["created_instance_id"]
        assert created_id is not None, "created_instance_id must be set when intake ran"

        # The item is marked as purchased.
        assert data["item"]["purchased_at"] is not None

        # The lot exists and its quantity is ledger-derived.
        lot = _get_instance(client, created_id)
        assert Decimal(lot["quantity"]) == Decimal("3")

        # Verify: an intake movement exists for the lot (ledger-backed).
        movements = _get_movements_for_instance(client, created_id)
        assert len(movements) >= 1
        intake_movements = [m for m in movements if m["type"] == "intake"]
        assert len(intake_movements) == 1, "Exactly one intake movement must exist"
        assert Decimal(intake_movements[0]["quantity_delta"]) == Decimal("3")

        # quantity == SUM(deltas) (the ledger-derived check, M7 §5).
        sum_deltas = sum(Decimal(m["quantity_delta"]) for m in movements)
        assert Decimal(lot["quantity"]) == sum_deltas

    def test_intake_creates_lot_in_specified_location(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """When intake.location_id is provided, the new lot uses that location."""
        client, _ = admin_client
        defn = _create_definition(client, name="Tea", unit="bags", tracking_mode="exact")
        loc = _create_location(client, "Kitchen shelf")
        item = _add_item(client, {"definition_id": defn["id"]})

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"location_id": loc["id"], "quantity": "10"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_instance_id"] is not None

        lot = _get_instance(client, data["created_instance_id"])
        assert lot["location_id"] == loc["id"]
        assert Decimal(lot["quantity"]) == Decimal("10")

    def test_intake_quantity_defaults_to_desired_quantity(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """When intake.quantity is omitted, desired_quantity is used as the intake qty.

        M7 §4.2: resolved qty = intake.quantity ?? desired_quantity.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Milk", unit="L", tracking_mode="exact")
        item = _add_item(
            client,
            {"definition_id": defn["id"], "desired_quantity": "4"},
        )

        # Omit intake.quantity → should fall back to desired_quantity=4.
        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {}},  # quantity key absent
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_instance_id"] is not None

        lot = _get_instance(client, data["created_instance_id"])
        assert Decimal(lot["quantity"]) == Decimal("4"), (
            "Intake qty should default to desired_quantity=4 when not explicitly set"
        )


# ---------------------------------------------------------------------------
# 3. Check-off with intake — error paths
# ---------------------------------------------------------------------------


class TestCheckOffIntakeErrors:
    """Error paths for POST /shopping-list/{id}/check with intake."""

    def test_both_quantity_null_raises_invalid_input(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """Both intake.quantity and desired_quantity NULL → 422 validation.invalid_input.

        M7 §4.2: the caller must say how many were bought.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Sugar", unit="kg", tracking_mode="exact")
        # No desired_quantity set on the item.
        item = _add_item(client, {"definition_id": defn["id"]})
        assert item["desired_quantity"] is None

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {}},  # no quantity in intake; no desired_quantity
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == "validation.invalid_input"

    def test_non_exact_definition_raises_movement_not_applicable(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """Intake on a non-'exact' (level-mode) definition → 409 stock.movement_not_applicable.

        M7 §4.2 / §10 Step 3: must use stock.movement_not_applicable, NOT
        instance.field_mode_mismatch.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Paper reams", unit="reams", tracking_mode="level")
        item = _add_item(client, {"definition_id": defn["id"]})

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"quantity": "3"}},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "stock.movement_not_applicable"

    def test_none_mode_definition_raises_movement_not_applicable(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """Intake on a 'none'-mode definition → 409 stock.movement_not_applicable."""
        client, _ = admin_client
        defn = _create_definition(client, name="Misc item", unit="unit", tracking_mode="none")
        item = _add_item(client, {"definition_id": defn["id"]})

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"quantity": "1"}},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "stock.movement_not_applicable"

    def test_missing_item_returns_404(self, admin_client: tuple[TestClient, Any]) -> None:
        """Non-existent item_id → 404 shopping_list.not_found (unchanged from Step 1)."""
        client, _ = admin_client
        resp = client.post(
            "/api/shopping-list/99999/check",
            json={"intake": {"quantity": "1"}},
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "shopping_list.not_found"


# ---------------------------------------------------------------------------
# 4. Atomic rollback
# ---------------------------------------------------------------------------


class TestAtomicRollback:
    """Intake failure must roll back both the lot creation AND the purchased_at stamp.

    M7 §4.2: "All of the above happen in ONE transaction — an intake failure
    must roll back the check-off."
    """

    def test_bad_location_id_rolls_back_purchased_at(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """Non-existent intake.location_id → 404; purchased_at stays NULL.

        The error is raised inside StockInstanceService.create (location
        existence check), before any instance or movement row is flushed.
        The route's db.commit() is never reached, so the whole request
        transaction rolls back — purchased_at is unchanged.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Flour", unit="kg", tracking_mode="exact")
        item = _add_item(
            client,
            {"definition_id": defn["id"], "desired_quantity": "5"},
        )

        # Snapshot the instance count before the failed check-off.
        instances_before = _list_instances(client)

        # Attempt check-off with a non-existent location_id.
        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"location_id": 99999, "quantity": "5"}},
        )
        # The location doesn't exist → StockInstanceService raises location.not_found.
        assert resp.status_code == 404
        assert resp.json()["code"] == "location.not_found"

        # purchased_at must still be NULL (rollback preserved the open state).
        all_items = _list_items(client, include_purchased=True)
        matching = [i for i in all_items if i["id"] == item["id"]]
        assert len(matching) == 1, "Item must still exist"
        assert matching[0]["purchased_at"] is None, (
            "purchased_at must remain NULL when intake failed (atomic rollback)"
        )

        # No new instances were created.
        instances_after = _list_instances(client)
        assert len(instances_after) == len(instances_before), (
            "No new stock lot must be created when intake failed (atomic rollback)"
        )

    def test_rollback_leaves_no_orphan_movements(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """After a failed intake, no orphan movement rows exist.

        Because the error is raised before any DB write in StockInstanceService.create
        (location existence check precedes the INSERT), the session has no pending
        changes to roll back — no movement or instance row is ever created.
        """
        client, _ = admin_client
        defn = _create_definition(client, name="Rice", unit="kg", tracking_mode="exact")
        item = _add_item(client, {"definition_id": defn["id"], "desired_quantity": "2"})

        resp = client.post(
            f"/api/shopping-list/{item['id']}/check",
            json={"intake": {"location_id": 88888, "quantity": "2"}},
        )
        assert resp.status_code == 404

        # No instances for this definition exist at all.
        instances = _list_instances(client)
        for inst in instances:
            assert inst["definition_id"] != defn["id"], (
                "No orphan instance may exist after failed intake"
            )


# ---------------------------------------------------------------------------
# 5. Post-intake reconcile drops the recovered row from the open list
# ---------------------------------------------------------------------------


class TestPostIntakeReconcile:
    """After check-off with intake, a recovered definition drops from the open list.

    Scenario (M7 §5):
    1. Definition is below min_stock → auto row appears in open list.
    2. User checks off the auto row with intake qty that brings definition above
       min_stock.
    3. Reconcile runs → definition is no longer low → no new open auto row appears.
    4. Open list shows no auto row for that definition.

    Note: the CHECKED auto row stays in the "purchased" section (M7 §4.3);
    it is only removed by clear-purchased.  What "drops off" is the definition
    from the *open* list — i.e., no new open auto row is created because the
    definition is above threshold.
    """

    def test_post_intake_open_list_clears(self, admin_client: tuple[TestClient, Any]) -> None:
        """After check-off + intake, reconcile shows no open auto row for the definition."""
        client, _ = admin_client

        # Create definition with min_stock=5.
        defn = _create_definition(
            client, name="Oat Milk", unit="L", tracking_mode="exact", min_stock="5"
        )

        # Create a stock instance with qty=2 (below min_stock=5).
        inst = _create_instance(client, defn["id"])
        _intake_movement(client, inst["id"], "2")  # qty=2 < min_stock=5 → definition is low

        # Refresh to trigger reconcile → auto row appears.
        open_items = _refresh(client)
        auto_rows = [
            i for i in open_items if i["source"] == "auto" and i["definition_id"] == defn["id"]
        ]
        assert len(auto_rows) == 1, "One open auto row must appear for the low definition"
        auto_item = auto_rows[0]

        # Check off the auto row with intake qty=10 (total: 2+10=12 > min_stock=5).
        resp = client.post(
            f"/api/shopping-list/{auto_item['id']}/check",
            json={"intake": {"quantity": "10"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_instance_id"] is not None, "A new lot must be created"

        # Reconcile again → definition is now above min_stock.
        open_after = _refresh(client)
        new_auto = [
            i for i in open_after if i["source"] == "auto" and i["definition_id"] == defn["id"]
        ]
        assert new_auto == [], (
            "No open auto row should exist after definition recovered above min_stock"
        )

    def test_checked_auto_row_visible_when_include_purchased(
        self, admin_client: tuple[TestClient, Any]
    ) -> None:
        """The checked auto row stays in the 'purchased' section until clear-purchased.

        M7 §4.3: a checked auto row survives recovery; it's removed only by
        clear-purchased, not by reconcile.
        """
        client, _ = admin_client

        defn = _create_definition(
            client, name="Butter", unit="kg", tracking_mode="exact", min_stock="5"
        )
        # _create_instance records the initial intake (default qty=1).
        # 1 < min_stock=5 → definition is low immediately after creation.
        inst = _create_instance(client, defn["id"])
        _intake_movement(client, inst["id"], "1")  # total qty=2 < min_stock=5 → still low

        open_items = _refresh(client)
        auto_item = next(
            i for i in open_items if i["source"] == "auto" and i["definition_id"] == defn["id"]
        )

        # Check off with intake (total: 2+10=12 > min_stock=5 → definition recovers).
        resp = client.post(
            f"/api/shopping-list/{auto_item['id']}/check",
            json={"intake": {"quantity": "10"}},
        )
        assert resp.status_code == 200

        # The checked auto row appears in the full list (include_purchased=true).
        all_items = _list_items(client, include_purchased=True)
        checked_auto = [
            i for i in all_items if i["id"] == auto_item["id"] and i["purchased_at"] is not None
        ]
        assert len(checked_auto) == 1, (
            "Checked auto row must remain in the full list until clear-purchased"
        )
