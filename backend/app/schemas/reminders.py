"""Reminder-related response schemas (M4 §4.11 / §9 Step 3).

``ReminderRunSummary``
    Returned by ``POST /reminders/run``.  Reports how many new notification
    rows were created per source in the just-completed scan.

    All three fields are present from Step 3 onward to keep the schema stable:
    ``low_stock`` is always 0 in Step 3; Step 4 fills it without contract drift.
"""

from pydantic import BaseModel


class ReminderRunSummary(BaseModel):
    """Summary of a single reminder scan run.

    Fields
    ------
    best_before
        Number of new best-before notifications created in this scan.
    warranty
        Number of new warranty notifications created in this scan.
    low_stock
        Number of new low-stock notifications created in this scan.
        Always 0 in Step 3; Step 4 fills it in.
    """

    best_before: int
    warranty: int
    low_stock: int
