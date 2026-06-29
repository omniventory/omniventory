"""Tests for maintenance schedule delete → notification cleanup.

Bug: deleting a maintenance schedule did NOT remove its notification rows,
causing two problems:
1. Orphaned bell entries.
2. Silent dedup suppression when a new schedule reused the same SQLite PK
   (INTEGER PRIMARY KEY without AUTOINCREMENT reuses freed ids) and the same
   next_due_date, making the new reminder invisible in the bell.

Fix: ``MaintenanceScheduleService.delete`` now calls
``NotificationRepository.delete_for_subject("maintenance_schedule", schedule_id)``
before removing the schedule row.
"""

from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker

from tests.conftest import drop_all_sqlite

# ---------------------------------------------------------------------------
# In-memory session factory (mirrors test_m7_step5.py)
# ---------------------------------------------------------------------------


def _make_in_memory_session() -> tuple[DBSession, object]:
    """Create a fresh in-memory SQLite session with all models registered."""
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
    import app.models.maintenance_schedule as ms_mod
    import app.models.media_file as media_file_mod
    import app.models.note as note_mod
    import app.models.notification as notif_mod
    import app.models.notification_delivery as notif_delivery_mod
    import app.models.session as sess_mod
    import app.models.setting as setting_mod
    import app.models.shopping_list_item as sli_mod
    import app.models.stock_instance as si_mod
    import app.models.stock_movement as sm_mod
    import app.models.tag as tag_mod
    import app.models.user as user_mod
    import app.models.user_token as user_token_mod
    import app.repositories.maintenance_schedule as ms_repo_mod

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
        si_mod,
        sm_mod,
        setting_mod,
        notif_mod,
        notif_delivery_mod,
        media_file_mod,
        attachment_mod,
        tag_mod,
        note_mod,
        barcode_mod,
        user_token_mod,
        audit_log_mod,
        sli_mod,
        ms_mod,
    ):
        importlib.reload(mod)

    # Reload repository AFTER models so its class references are fresh.
    importlib.reload(ms_repo_mod)

    from app.db.base import Base as _Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enforce_fk(dbapi_conn: object, _: object) -> None:  # type: ignore[type-arg]
        import sqlite3

        if isinstance(dbapi_conn, sqlite3.Connection):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    _Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = factory()
    return session, engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_caches() -> object:
    from app.config import get_settings
    from app.db.base import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture()
def db() -> object:
    """Fresh in-memory SQLite session with all models."""
    session, engine = _make_in_memory_session()
    from app.db.base import Base as _Base

    try:
        yield session
    finally:
        session.close()
    drop_all_sqlite(_Base, engine)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_base(session: DBSession) -> None:
    """Seed Household + all three ItemKinds (required by tests)."""
    from app.models.household import Household
    from app.models.item_kind import ItemKind

    session.add(Household(id=1, name="Test Home", currency="USD", timezone="UTC"))
    session.flush()
    for code, name in (
        ("durable", "Durable"),
        ("consumable", "Consumable"),
        ("perishable", "Perishable"),
    ):
        session.add(ItemKind(code=code, name=name, is_system=True))
    session.flush()
    session.commit()


def _make_user(session: DBSession, email: str) -> object:
    from app.auth.passwords import hash_password
    from app.models.user import User

    u = User(
        email=email,
        password_hash=hash_password("pw"),
        role="admin",
        is_active=True,
        notify_in_app=True,
        notify_email_digest=True,
    )
    session.add(u)
    session.flush()
    session.commit()
    return u


def _make_definition(session: DBSession, kind_id: int, name: str = "AC Unit") -> object:
    from app.models.item_definition import ItemDefinition

    d = ItemDefinition(
        name=name,
        kind_id=kind_id,
        stock_tracking_mode="exact",
        unit="unit",
    )
    session.add(d)
    session.flush()
    session.commit()
    return d


def _make_instance(session: DBSession, definition_id: int) -> object:
    from app.models.stock_instance import StockInstance

    inst = StockInstance(definition_id=definition_id, quantity=Decimal("1"))
    session.add(inst)
    session.flush()
    session.commit()
    return inst


def _make_schedule(
    session: DBSession,
    instance_id: int,
    *,
    next_due_date: date,
    lead_days: int = 0,
) -> object:
    from app.models.maintenance_schedule import MaintenanceSchedule

    s = MaintenanceSchedule(
        instance_id=instance_id,
        name="Filter change",
        interval_unit="month",
        interval_count=3,
        next_due_date=next_due_date,
        lead_days=lead_days,
        is_active=True,
    )
    session.add(s)
    session.flush()
    session.commit()
    return s


def _notifs_for_subject(
    session: DBSession,
    subject_type: str,
    subject_id: int,
) -> list[object]:
    from app.models.notification import Notification

    stmt = select(Notification).where(
        Notification.subject_type == subject_type,
        Notification.subject_id == subject_id,
    )
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# 1. Repository unit test — delete_for_subject
# ---------------------------------------------------------------------------


class TestDeleteForSubject:
    """Unit tests for ``NotificationRepository.delete_for_subject``."""

    def test_deletes_matching_rows_and_returns_count(self, db: DBSession) -> None:
        """Rows with the exact (subject_type, subject_id) are deleted; count returned."""
        _seed_base(db)
        u = _make_user(db, "u@test.com")

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        # Two rows for subject_id=10.
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=10,
            dedup_key="dedup-a",
            message_code="reminder.maintenance",
        )
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=10,
            dedup_key="dedup-b",
            message_code="reminder.maintenance",
        )
        # One row for a different subject_id — must survive.
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=99,
            dedup_key="dedup-c",
            message_code="reminder.maintenance",
        )
        db.commit()

        count = repo.delete_for_subject("maintenance_schedule", 10)
        db.commit()

        assert count == 2
        assert _notifs_for_subject(db, "maintenance_schedule", 10) == []
        assert len(_notifs_for_subject(db, "maintenance_schedule", 99)) == 1

    def test_noop_returns_zero_when_nothing_matches(self, db: DBSession) -> None:
        """No rows matched → return 0 without error."""
        _seed_base(db)
        from app.repositories.notification import NotificationRepository

        count = NotificationRepository(db).delete_for_subject("maintenance_schedule", 999)
        assert count == 0

    def test_does_not_delete_different_subject_type(self, db: DBSession) -> None:
        """delete_for_subject("maintenance_schedule", N) leaves "instance" rows untouched."""
        _seed_base(db)
        u = _make_user(db, "u2@test.com")

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=10,
            dedup_key="dedup-instance-10",
            message_code="reminder.best_before",
        )
        db.commit()

        count = repo.delete_for_subject("maintenance_schedule", 10)
        assert count == 0
        # The "instance" notification is untouched.
        assert len(_notifs_for_subject(db, "instance", 10)) == 1


# ---------------------------------------------------------------------------
# 2. Service integration — delete cleans up notifications
# ---------------------------------------------------------------------------


class TestDeleteScheduleCleansNotifications:
    """MaintenanceScheduleService.delete removes the schedule's notifications."""

    def test_delete_removes_schedule_notifications_not_unrelated(
        self,
        db: DBSession,
    ) -> None:
        """Deleting a schedule purges its notifications but preserves unrelated ones."""
        _seed_base(db)
        u = _make_user(db, "u@test.com")

        from app.models.item_kind import ItemKind

        kind = db.execute(select(ItemKind).where(ItemKind.code == "durable")).scalar_one()
        defn = _make_definition(db, kind.id)
        inst = _make_instance(db, defn.id)

        today = date(2026, 7, 10)
        schedule = _make_schedule(db, inst.id, next_due_date=today, lead_days=0)
        schedule_id = schedule.id  # type: ignore[attr-defined]

        # Run the scan so the notification row is created.
        from app.services.reminder_engine import ReminderEngine

        summary = ReminderEngine(db).run_scan(today_local=today)
        db.commit()
        assert summary.maintenance >= 1, "Scan must have produced at least one notification"
        assert len(_notifs_for_subject(db, "maintenance_schedule", schedule_id)) >= 1

        # Plant an UNRELATED notification (different subject_id) to verify scoped delete.
        from app.repositories.notification import NotificationRepository

        NotificationRepository(db).create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=schedule_id + 1000,
            dedup_key=f"unrelated-notif-{schedule_id}",
            message_code="reminder.maintenance",
        )
        db.commit()

        # Delete the schedule via the service.
        from app.services.maintenance_schedule import MaintenanceScheduleService

        MaintenanceScheduleService(db).delete(schedule_id)
        db.commit()

        # Notifications for the deleted schedule are gone.
        assert _notifs_for_subject(db, "maintenance_schedule", schedule_id) == [], (
            "Orphaned notification rows must be removed when the schedule is deleted."
        )

        # The unrelated notification is untouched.
        assert len(_notifs_for_subject(db, "maintenance_schedule", schedule_id + 1000)) == 1, (
            "delete_for_subject must be scoped — unrelated notifications must survive."
        )


# ---------------------------------------------------------------------------
# 3. Regression — id-reuse + same due-date no longer silently suppressed
# ---------------------------------------------------------------------------


class TestIdReuseDeduplicationFixed:
    """Regression: new schedule reusing a deleted schedule's PK gets its notification.

    SQLite's ``INTEGER PRIMARY KEY`` (without ``AUTOINCREMENT``) reuses freed
    row-ids: once the only schedule is deleted the next insert gets id=1 again.
    Before the fix, the stale dedup key ``maintenance:u{uid}:s{id}:{date}``
    was still in the DB, so ``create_if_absent`` returned ``created=False`` and
    the new reminder never appeared in the bell.
    """

    def test_recreate_same_due_date_creates_new_notification(
        self,
        db: DBSession,
    ) -> None:
        """
        Full regression path:
        1. Create schedule (id=N), scan → notification created.
        2. Delete schedule → notification rows deleted (the fix).
        3. Create new schedule (same instance, same next_due_date).
        4. Assert new_id == old_id (SQLite PK reuse — non-vacuous check).
        5. Scan again → NEW notification created (not suppressed).
        """
        _seed_base(db)
        _make_user(db, "u@test.com")

        from app.models.item_kind import ItemKind

        kind = db.execute(select(ItemKind).where(ItemKind.code == "durable")).scalar_one()
        defn = _make_definition(db, kind.id)
        inst = _make_instance(db, defn.id)

        today = date(2026, 7, 10)
        next_due = today  # lead_days=0 → fires on the due date itself

        # --- Step 1: create first schedule and scan ---
        sched1 = _make_schedule(db, inst.id, next_due_date=next_due, lead_days=0)
        old_id: int = sched1.id  # type: ignore[attr-defined]

        from app.services.reminder_engine import ReminderEngine

        summary1 = ReminderEngine(db).run_scan(today_local=today)
        db.commit()
        assert summary1.maintenance >= 1, "Initial scan must create at least one notification"
        assert len(_notifs_for_subject(db, "maintenance_schedule", old_id)) >= 1

        # --- Step 2: delete via service (fix cleans up notifications) ---
        from app.services.maintenance_schedule import MaintenanceScheduleService

        MaintenanceScheduleService(db).delete(old_id)
        db.commit()
        assert _notifs_for_subject(db, "maintenance_schedule", old_id) == [], (
            "delete must clean up notifications so the dedup key slot is free"
        )

        # --- Step 3: recreate with same instance + same next_due_date ---
        sched2 = _make_schedule(db, inst.id, next_due_date=next_due, lead_days=0)
        new_id: int = sched2.id  # type: ignore[attr-defined]

        # --- Step 4: non-vacuous check — SQLite must reuse the PK ---
        assert new_id == old_id, (
            f"Test requires SQLite to reuse the deleted schedule's PK "
            f"(old_id={old_id}, new_id={new_id}).  "
            "maintenance_schedules.id uses INTEGER PRIMARY KEY (no AUTOINCREMENT), "
            "so after the table becomes empty the next insert gets id=1 again.  "
            "If this assertion fails, check the model definition."
        )

        # --- Step 5: scan again — must produce a new notification ---
        summary2 = ReminderEngine(db).run_scan(today_local=today)
        db.commit()
        assert summary2.maintenance >= 1, (
            "Scan after delete+recreate must produce at least one maintenance notification.  "
            "Before the fix, the stale dedup key suppressed the new reminder."
        )

        fresh_notifs = _notifs_for_subject(db, "maintenance_schedule", new_id)
        assert len(fresh_notifs) >= 1, (
            "Bell must contain a fresh maintenance notification for the recreated schedule."
        )
