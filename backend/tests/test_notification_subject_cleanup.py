"""Tests for A2: wiring ``delete_for_subject`` into the instance / definition
delete paths (notif-hygiene design doc §5).

Bug (A2, from ``follow-ups.md``): deleting a stock instance or an item
definition left its notification rows behind — stale bell entries, and
(because SQLite reuses integer PKs) a recreated subject reusing the old PK +
same target date was silently deduped away, so a legitimate reminder never
fired again.  ``NotificationRepository.delete_for_subject`` already existed
and was wired into ``MaintenanceScheduleService.delete`` (see
``test_maint_delete_notif_cleanup.py``); this module covers the two remaining
delete paths:

- ``StockInstanceService.delete`` — cleans the lot's own ``subject_type=
  "instance"`` notifications (best_before / warranty), AND the notifications
  of any maintenance schedules that get cascade-deleted with the instance
  (``maintenance_schedules.instance_id`` is ``ondelete=CASCADE``, which drops
  the schedule rows but NOT their notification rows).
- ``ItemDefinitionService.delete`` — cleans the definition's own
  ``subject_type="definition"`` low_stock notifications.  The existing 409
  ``has_instances_for_definition`` guard means a definition can only be
  deleted once it has no instances, so there is nothing instance- or
  maintenance-scoped to clean up here.
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
# In-memory session factory (mirrors test_maint_delete_notif_cleanup.py)
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
    import app.repositories.item_definition as idef_repo_mod
    import app.repositories.maintenance_schedule as ms_repo_mod
    import app.repositories.notification as notif_repo_mod
    import app.repositories.stock_instance as si_repo_mod

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

    # Reload repositories AFTER models so their class references are fresh.
    for repo_mod in (notif_repo_mod, ms_repo_mod, si_repo_mod, idef_repo_mod):
        importlib.reload(repo_mod)

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


def _durable_kind_id(session: DBSession) -> int:
    from app.models.item_kind import ItemKind

    kind = session.execute(select(ItemKind).where(ItemKind.code == "durable")).scalar_one()
    return kind.id  # type: ignore[no-any-return]


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
# 1. Instance delete cleans its own date-source ("instance") notifications
# ---------------------------------------------------------------------------


class TestInstanceDeleteCleansOwnNotifications:
    def test_delete_removes_best_before_and_warranty_notifications(self, db: DBSession) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        inst = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_id: int = inst.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=inst_id,
            dedup_key=f"best_before:u{u.id}:i{inst_id}:2026-07-15",  # type: ignore[attr-defined]
            message_code="reminder.best_before",
        )
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="warranty",
            subject_type="instance",
            subject_id=inst_id,
            dedup_key=f"warranty:u{u.id}:i{inst_id}:2026-08-01",  # type: ignore[attr-defined]
            message_code="reminder.warranty",
        )
        db.commit()
        assert len(_notifs_for_subject(db, "instance", inst_id)) == 2

        from app.services.stock_instance import StockInstanceService

        StockInstanceService(db).delete(inst_id)
        db.commit()

        assert _notifs_for_subject(db, "instance", inst_id) == [], (
            "Deleting the instance must clean up its own date-source notifications."
        )

    def test_delete_leaves_other_instances_notifications_untouched(self, db: DBSession) -> None:
        """delete_for_subject is scoped -- an unrelated instance's rows must survive."""
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        inst_a = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_b = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_a_id: int = inst_a.id  # type: ignore[attr-defined]
        inst_b_id: int = inst_b.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=inst_a_id,
            dedup_key=f"best_before:i{inst_a_id}",
            message_code="reminder.best_before",
        )
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=inst_b_id,
            dedup_key=f"best_before:i{inst_b_id}",
            message_code="reminder.best_before",
        )
        db.commit()

        from app.services.stock_instance import StockInstanceService

        StockInstanceService(db).delete(inst_a_id)
        db.commit()

        assert _notifs_for_subject(db, "instance", inst_a_id) == []
        assert len(_notifs_for_subject(db, "instance", inst_b_id)) == 1, (
            "Unrelated instance's notifications must survive the delete."
        )


# ---------------------------------------------------------------------------
# 2. Instance delete cleans notifications for its CASCADE-deleted maintenance
#    schedules
# ---------------------------------------------------------------------------


class TestInstanceDeleteCleansCascadedMaintenanceNotifications:
    def test_delete_removes_cascaded_schedule_and_its_notification(self, db: DBSession) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        inst = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_id: int = inst.id  # type: ignore[attr-defined]

        schedule = _make_schedule(db, inst_id, next_due_date=date(2026, 7, 20))
        schedule_id: int = schedule.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=schedule_id,
            dedup_key=f"maintenance:s{schedule_id}:2026-07-20",
            message_code="reminder.maintenance",
        )
        db.commit()
        assert len(_notifs_for_subject(db, "maintenance_schedule", schedule_id)) == 1

        from app.models.maintenance_schedule import MaintenanceSchedule
        from app.services.stock_instance import StockInstanceService

        StockInstanceService(db).delete(inst_id)
        db.commit()

        # The schedule itself is gone (DB-level ON DELETE CASCADE).
        remaining_schedule = db.execute(
            select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id)
        ).scalar_one_or_none()
        assert remaining_schedule is None, (
            "Schedule row must be gone via ondelete=CASCADE on maintenance_schedules.instance_id."
        )

        # Its notification is also gone -- this is the part the DB cascade does
        # NOT handle on its own; the service must clean it up explicitly.
        assert _notifs_for_subject(db, "maintenance_schedule", schedule_id) == [], (
            "Instance delete must also purge notifications for cascade-deleted "
            "maintenance schedules, since the FK cascade only removes the "
            "schedule row itself, not its notification rows."
        )

    def test_delete_leaves_other_instance_schedule_notifications_untouched(
        self, db: DBSession
    ) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        inst_a = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_b = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_a_id: int = inst_a.id  # type: ignore[attr-defined]
        inst_b_id: int = inst_b.id  # type: ignore[attr-defined]

        sched_a = _make_schedule(db, inst_a_id, next_due_date=date(2026, 7, 20))
        sched_b = _make_schedule(db, inst_b_id, next_due_date=date(2026, 7, 20))
        sched_a_id: int = sched_a.id  # type: ignore[attr-defined]
        sched_b_id: int = sched_b.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=sched_a_id,
            dedup_key=f"maintenance:s{sched_a_id}",
            message_code="reminder.maintenance",
        )
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="maintenance",
            subject_type="maintenance_schedule",
            subject_id=sched_b_id,
            dedup_key=f"maintenance:s{sched_b_id}",
            message_code="reminder.maintenance",
        )
        db.commit()

        from app.services.stock_instance import StockInstanceService

        StockInstanceService(db).delete(inst_a_id)
        db.commit()

        assert _notifs_for_subject(db, "maintenance_schedule", sched_a_id) == []
        assert len(_notifs_for_subject(db, "maintenance_schedule", sched_b_id)) == 1, (
            "Another instance's schedule notification must survive the delete."
        )


# ---------------------------------------------------------------------------
# 3. Definition delete cleans its own low_stock ("definition") notifications
# ---------------------------------------------------------------------------


class TestDefinitionDeleteCleansLowStockNotifications:
    def test_delete_removes_low_stock_notifications(self, db: DBSession) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        defn_id: int = defn.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="low_stock",
            subject_type="definition",
            subject_id=defn_id,
            dedup_key=f"low_stock:d{defn_id}:2026-07-01",
            message_code="reminder.low_stock",
            episode_started_on=date(2026, 7, 1),
            offset_days=0,
        )
        db.commit()
        assert len(_notifs_for_subject(db, "definition", defn_id)) == 1

        from app.services.item_definition import ItemDefinitionService

        ItemDefinitionService(db).delete(defn_id)
        db.commit()

        assert _notifs_for_subject(db, "definition", defn_id) == [], (
            "Deleting the definition must clean up its own low_stock notifications."
        )

    def test_delete_blocked_by_instances_guard_leaves_notifications_untouched(
        self, db: DBSession
    ) -> None:
        """The existing 409 has_instances_for_definition guard still fires first."""
        from app.core.errors import AppError

        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        defn_id: int = defn.id  # type: ignore[attr-defined]
        _make_instance(db, defn_id)

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="low_stock",
            subject_type="definition",
            subject_id=defn_id,
            dedup_key=f"low_stock:d{defn_id}",
            message_code="reminder.low_stock",
        )
        db.commit()

        from app.services.item_definition import ItemDefinitionService

        with pytest.raises(AppError) as exc_info:
            ItemDefinitionService(db).delete(defn_id)
        assert exc_info.value.status_code == 409

        # Guard fired before any cleanup/delete happened.
        assert len(_notifs_for_subject(db, "definition", defn_id)) == 1


# ---------------------------------------------------------------------------
# 4. Regression -- the stale dedup anchor is gone after delete
# ---------------------------------------------------------------------------


class TestStaleDedupAnchorRemovedRegression:
    """Regression for the silent-dedup symptom described in the design doc.

    Before the fix: deleting a subject left its notification row (and dedup
    key) in place, so a fresh ``create_if_absent`` call reusing that same
    dedup key was silently suppressed (``created=False``) -- e.g. because
    SQLite reuses freed integer PKs, a brand-new subject could land on the
    same id + target date and produce the identical dedup key as the deleted
    row's, and the "new" reminder would never appear in the bell.
    """

    def test_instance_delete_frees_the_dedup_key_for_reuse(self, db: DBSession) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        inst = _make_instance(db, defn.id)  # type: ignore[attr-defined]
        inst_id: int = inst.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        dedup_key = f"best_before:u{u.id}:i{inst_id}:2026-07-15"  # type: ignore[attr-defined]
        _notif1, created1 = repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=inst_id,
            dedup_key=dedup_key,
            message_code="reminder.best_before",
        )
        db.commit()
        assert created1 is True

        from app.services.stock_instance import StockInstanceService

        StockInstanceService(db).delete(inst_id)
        db.commit()

        # A fresh notification reusing the exact same dedup key must now be
        # created (not silently suppressed as a "duplicate").
        _notif2, created2 = repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="best_before",
            subject_type="instance",
            subject_id=inst_id,
            dedup_key=dedup_key,
            message_code="reminder.best_before",
        )
        db.commit()

        # ``created2 is True`` is the meaningful proof: a brand-new row was
        # inserted rather than the call being silently suppressed as a
        # duplicate.  We deliberately do NOT assert the new row's id differs
        # from the old one -- SQLite reuses freed integer PKs, so the fresh
        # row may legitimately land on the deleted row's former id.
        assert created2 is True, (
            "The stale dedup anchor from the deleted instance's notification "
            "must be gone, so a new notification reusing the same dedup key "
            "is created rather than silently suppressed."
        )

    def test_definition_delete_frees_the_dedup_key_for_reuse(self, db: DBSession) -> None:
        _seed_base(db)
        u = _make_user(db, "u@test.com")
        defn = _make_definition(db, _durable_kind_id(db))
        defn_id: int = defn.id  # type: ignore[attr-defined]

        from app.repositories.notification import NotificationRepository

        repo = NotificationRepository(db)
        dedup_key = f"low_stock:d{defn_id}:2026-07-01"
        _notif1, created1 = repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="low_stock",
            subject_type="definition",
            subject_id=defn_id,
            dedup_key=dedup_key,
            message_code="reminder.low_stock",
            episode_started_on=date(2026, 7, 1),
            offset_days=0,
        )
        db.commit()
        assert created1 is True

        from app.services.item_definition import ItemDefinitionService

        ItemDefinitionService(db).delete(defn_id)
        db.commit()

        _notif2, created2 = repo.create_if_absent(
            user_id=u.id,  # type: ignore[attr-defined]
            source="low_stock",
            subject_type="definition",
            subject_id=defn_id,
            dedup_key=dedup_key,
            message_code="reminder.low_stock",
            episode_started_on=date(2026, 7, 1),
            offset_days=0,
        )
        db.commit()

        # See the instance-delete regression above: ``created2 is True`` is the
        # proof; we do not compare ids because SQLite reuses freed PKs.
        assert created2 is True, (
            "The stale dedup anchor from the deleted definition's low_stock "
            "notification must be gone, so a new notification reusing the "
            "same dedup key is created rather than silently suppressed."
        )
