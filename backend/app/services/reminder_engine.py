"""Reminder engine — unified source-pluggable scan (M4 §4.1 / §4.2–§4.4 / §9 Step 3).

``ReminderEngine.run_scan()`` evaluates all date sources (best_before, warranty)
across all active recipients and writes idempotent notification rows.

Locked decisions implemented here (M4 §2)
------------------------------------------
- **One engine, source-pluggable**: each date source is a small ``_DateSource``
  descriptor; the engine loops sources × recipients × lots in a single pass.
  The low-stock source (Step 4) slots in via ``_DateSource`` without touching
  the existing two sources.
- **Recipients = all active users (M4)**: ``UserRepository.list_active()``.
- **"Today" honours ``household.timezone``**: ``today_local`` is computed from
  the current UTC time localised into ``household.timezone`` via
  ``zoneinfo.ZoneInfo``; never via ``date.today()`` (which returns the system
  local date and is wrong for deployments with a non-local timezone).
- **Lead resolution per-item > per-user > global** (§4.3): first non-None wins.
- **Date sources fire once per (recipient, lot, target-date)** (§4.4): the
  dedup key ``"{source}:u{uid}:i{lot_id}:{target_date}"`` makes re-runs no-ops.

Testability
-----------
``run_scan(today_local=None)``  When ``None`` (the default) the scan computes
    ``today_local`` from ``household.timezone``; tests inject a fixed ``date``
    to remove clock dependency.  Tests should *also* verify the tz-aware
    default path by constructing a household with a timezone that differs from
    UTC on a known offset boundary (see ``test_m4_step3.py``).

Out of scope (Step 3)
---------------------
- Low-stock source (Step 4)
- APScheduler wiring (Step 5)
- Inbox list / mark-read API (Step 6)
- External channels (Steps 7–10)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.stock_instance import StockInstance
from app.models.user import User
from app.notifications.dispatcher import NotificationDispatcher
from app.repositories.household import HouseholdRepository
from app.repositories.notification import NotificationRepository
from app.repositories.stock_instance import StockInstanceRepository
from app.repositories.user import UserRepository
from app.services.settings import SettingsService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source descriptor (pluggable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _DateSource:
    """Descriptor for a date-based reminder source.

    Parameters
    ----------
    name:
        Stable source identifier used in the dedup key and ``notifications.source``
        column (e.g. ``"best_before"``, ``"warranty"``).
    get_target_date:
        Callable that extracts the relevant date from a ``StockInstance``; returns
        ``None`` when the date is not applicable to this lot.
    get_per_user_lead:
        Callable that extracts the per-user lead-days override from a ``User``;
        returns ``None`` when the user has no override for this source.
    message_code:
        i18n code stored in ``notifications.message_code`` (e.g.
        ``"reminder.best_before"``).
    get_lots:
        Callable that retrieves all live lots carrying this date from the
        repository.
    """

    name: str
    get_target_date: Callable[[StockInstance], date | None]
    get_per_user_lead: Callable[[User], int | None]
    message_code: str
    get_lots: Callable[[StockInstanceRepository], list[StockInstance]]


# The two date sources (best_before and warranty).
_DATE_SOURCES: list[_DateSource] = [
    _DateSource(
        name="best_before",
        get_target_date=lambda lot: lot.best_before_date,
        get_per_user_lead=lambda user: user.reminder_best_before_lead_days,
        message_code="reminder.best_before",
        get_lots=lambda repo: repo.list_live_with_best_before(),
    ),
    _DateSource(
        name="warranty",
        get_target_date=lambda lot: lot.warranty_expires,
        get_per_user_lead=lambda user: user.reminder_warranty_lead_days,
        message_code="reminder.warranty",
        get_lots=lambda repo: repo.list_live_with_warranty(),
    ),
]


# ---------------------------------------------------------------------------
# Lead resolution chain (§4.3)
# ---------------------------------------------------------------------------


def _resolve_lead(
    source: _DateSource,
    definition_lead: int | None,
    user: User,
    settings_service: SettingsService,
) -> int:
    """Resolve the effective lead-time in days for a source / definition / user.

    Resolution chain (§4.3, first non-None wins):
    1. ``definition.reminder_lead_days`` — per-item override (applies to all
       date sources on this definition's lots).
    2. Per-user override — ``user.reminder_best_before_lead_days`` for
       ``best_before``, ``user.reminder_warranty_lead_days`` for ``warranty``.
    3. Global default — ``settings_service.best_before_lead_days()`` or
       ``settings_service.warranty_lead_days()``.

    All resolved values are ``≥ 0`` (Pydantic-validated at write time).
    A lead of 0 means fire on the target date itself.

    Parameters
    ----------
    source:
        The ``_DateSource`` descriptor for the current source.
    definition_lead:
        ``definition.reminder_lead_days`` (may be ``None`` = "inherit").
    user:
        The recipient; carries per-user overrides.
    settings_service:
        Provides the global defaults.
    """
    # 1. Per-item override wins first
    if definition_lead is not None:
        return definition_lead

    # 2. Per-user override
    per_user = source.get_per_user_lead(user)
    if per_user is not None:
        return per_user

    # 3. Global default
    if source.name == "best_before":
        return settings_service.best_before_lead_days()
    # warranty
    return settings_service.warranty_lead_days()


# ---------------------------------------------------------------------------
# Run summary dataclass (mirrors ReminderRunSummary schema)
# ---------------------------------------------------------------------------


@dataclass
class ScanSummary:
    """Created-notification counts returned by ``run_scan()``."""

    best_before: int = 0
    warranty: int = 0
    low_stock: int = 0  # Step 4 fills this; Step 3 always returns 0.


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ReminderEngine:
    """Orchestrates the reminder scan across all sources and recipients.

    Instantiate once per request/job run; the engine is stateless between
    ``run_scan()`` calls.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._user_repo = UserRepository(db)
        self._instance_repo = StockInstanceRepository(db)
        self._notification_repo = NotificationRepository(db)
        self._household_repo = HouseholdRepository(db)
        self._settings_service = SettingsService(db)
        self._dispatcher = NotificationDispatcher()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scan(self, today_local: date | None = None) -> ScanSummary:
        """Evaluate all date sources for all active recipients.

        Parameters
        ----------
        today_local:
            The reference date for this scan.  When ``None`` (the default in
            production), the date is computed from ``household.timezone`` so
            that the scan honours the household's clock.  Tests inject a fixed
            date to remove clock dependency (but should also verify the tz-aware
            path separately).

        Returns
        -------
        ScanSummary
            Per-source counts of newly created notification rows.
        """
        # ---- Resolve today ------------------------------------------------
        if today_local is None:
            household = self._household_repo.ensure()
            today_local = self._today_in_tz(household.timezone)

        # ---- Collect recipients -------------------------------------------
        recipients = self._user_repo.list_active()
        if not recipients:
            logger.debug("run_scan: no active users — skipping.")
            return ScanSummary()

        # ---- Evaluate each date source ------------------------------------
        summary = ScanSummary()
        all_new: list[Notification] = []

        for source in _DATE_SOURCES:
            lots = source.get_lots(self._instance_repo)
            count, new_notifications = self._evaluate_date_source(
                source=source,
                lots=lots,
                recipients=recipients,
                today_local=today_local,
            )
            # Map source name to summary field
            if source.name == "best_before":
                summary.best_before += count
            elif source.name == "warranty":
                summary.warranty += count
            all_new.extend(new_notifications)

        # ---- Dispatch (in-app = implicit; external channels are no-ops
        #     in Step 3; caller commits before calling dispatch) --------
        # NOTE: dispatch is called here but the caller (the route handler) is
        # responsible for committing the DB session BEFORE calling run_scan OR
        # the route must commit after and the dispatcher runs post-commit.
        #
        # Per M4 §4.6: "Network I/O happens after the notification rows commit".
        # The route handler pattern is:
        #   engine.run_scan() → route commits via get_db → then dispatch.
        #
        # For Step 3: the dispatcher is a no-op (no external channels), so the
        # ordering does not matter yet.  The dispatch call is placed here as the
        # structural hook for Phase C (Steps 7–9) to wire into.
        self._dispatcher.dispatch(all_new, include_email_digest=True)

        logger.info(
            "run_scan complete: best_before=%d, warranty=%d, low_stock=%d",
            summary.best_before,
            summary.warranty,
            summary.low_stock,
        )
        return summary

    # ------------------------------------------------------------------
    # Internal: date-source evaluation
    # ------------------------------------------------------------------

    def _evaluate_date_source(
        self,
        *,
        source: _DateSource,
        lots: list[StockInstance],
        recipients: list[User],
        today_local: date,
    ) -> tuple[int, list[Notification]]:
        """Evaluate one date source across all recipients × lots.

        Returns (created_count, list_of_new_notifications).
        """
        created_count = 0
        new_notifications: list[Notification] = []

        for user in recipients:
            for lot in lots:
                target_date = source.get_target_date(lot)
                if target_date is None:
                    continue  # Defensive: the query should already filter these out.

                definition_lead: int | None = lot.definition.reminder_lead_days
                lead = _resolve_lead(source, definition_lead, user, self._settings_service)

                window: date = target_date - timedelta(days=lead)
                if today_local < window:
                    continue  # Too early — fire when today_local >= window.

                dedup = f"{source.name}:u{user.id}:i{lot.id}:{target_date.isoformat()}"
                params = {
                    "name": lot.definition.name,
                    "date": target_date.isoformat(),
                    "days_remaining": (target_date - today_local).days,
                    "location_id": lot.location_id,
                }

                notification, created = self._notification_repo.create_if_absent(
                    user_id=user.id,
                    source=source.name,
                    subject_type="instance",
                    subject_id=lot.id,
                    dedup_key=dedup,
                    message_code=source.message_code,
                    params=params,
                )

                if created:
                    created_count += 1
                    new_notifications.append(notification)

        return created_count, new_notifications

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today_in_tz(timezone: str) -> date:
        """Return today's date in the given IANA timezone.

        Uses ``zoneinfo.ZoneInfo`` (stdlib since Python 3.9) to convert the
        current UTC instant to the household-local date.  Never uses
        ``date.today()`` which returns the system's local date and is wrong
        when the deployment timezone differs from the household timezone.
        """
        from datetime import datetime

        tz = ZoneInfo(timezone)
        now_utc = datetime.now(tz=UTC)
        return now_utc.astimezone(tz).date()
