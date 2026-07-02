# Follow-ups & known deferrals

> 🌐 **Languages:** English (this doc) · [中文](./follow-ups_zh.md)

This is the running backlog of **non-blocking** follow-ups and known deferrals surfaced during milestone walkthroughs and blind reviews. None of these block a milestone's acceptance; they are recorded here so they aren't lost. Design-level deferrals that belong to a specific milestone stay in that milestone's design doc (e.g. `M7.md` §13); this file collects the cross-cutting, post-acceptance items.

Priority is advisory: **Robustness** > **UX** > **Cosmetic** / **Test hygiene**.

## Open

### Robustness / consistency

- **A1 — Uniform PATCH null-handling across repositories.** The repo-layer guard `reject_null_on_non_nullable` (`backend/app/repositories/_update_guard.py`) is applied to the two blind-`setattr`-loop repositories (`maintenance_schedule`, `shopping_list`), so an explicit `null` on a NOT NULL column returns a clean **422**. The other seven repositories (`category`, `location`, `item_definition`, `stock_instance`, `note`, `tag`, `attachment`) instead **silently ignore** an explicit `null` on a NOT NULL column (the `if x is not None` / `set_*`-flag pattern skips it and returns **200** unchanged). The two behaviours are inconsistent across PATCH endpoints. Follow-up: a consistency pass routing every PATCH update through the same guard (or an explicit decision to keep the silent-ignore and document it). *Source: `review-notes/patch-null-guard-review.md` MINOR #2.*

### UX

- **B1 — Shopping-list check-off intake: modal → inline action.** Checking off a definition-linked shopping item pops a modal to enter intake quantity/location. Suggested to make this an inline/quick action (or prefill-and-confirm) rather than interrupting with a modal. *Source: walkthrough note. Touches `frontend/src/pages/ShoppingList.tsx` (check-off flow).*

- **B2 — Maintenance schedule discoverability.** Maintenance schedules live on the InstanceDetail page (`/instances/:id`), one click into a specific lot from the item detail. Consider surfacing an affordance from the item-detail lot row (e.g. a "has maintenance" badge or quick link) so the feature is easier to find. *Touches `frontend/src/pages/Items.tsx` (lot rows) and `frontend/src/pages/InstanceDetail.tsx`.*

- **B3 — MaintenancePanel renders for every instance.** The panel is shown unconditionally for all instances, including consumables, because there is no clean durable/kind signal to gate on; a consumable lot shows an empty maintenance section (no functional harm). Gate it to durables once a clean signal exists. *Source: `review-notes/M7-report.md` §5 #3. Touches `frontend/src/pages/InstanceDetail.tsx`.*

- **B4 — LLM base URL field has no example/hint.** The provider config's **Base URL** input has no placeholder, so it isn't obvious that the value must **already include the version segment** (e.g. `https://openrouter.ai/api/v1`, not `https://openrouter.ai/api`). During the M9.1 walkthrough this ambiguity — combined with the now-fixed double-`/v1` bug — produced a confusing "model unavailable" error. Follow-up: add a placeholder / helper text (e.g. `https://openrouter.ai/api/v1`) to the Base URL field, and optionally a light client-side hint when the URL doesn't look version-suffixed. *Source: M9.1 walkthrough. Touches `frontend/src/pages/Configuration.tsx` (LLM section) + `frontend/src/i18n/locales/{en,zh}/llm.json`.*

### Cosmetic / i18n

- **C1 — "Due today" has no dedicated copy.** For maintenance (and the existing best_before / warranty templates), `days_remaining === 0` renders as "0 days remaining" instead of a dedicated "due today" string. Add a dedicated string across the reminder templates. *Source: `review-notes/M7-report.md` §5 #5. Touches `frontend/src/pages/Notifications.tsx` + notifications i18n catalogs.*

### Test hygiene

- **D1 — React `act()` warning in the MaintenanceCard test.** The dashboard upcoming-maintenance tile test performs an async state update that is not wrapped in `act(...)`, producing a non-failing warning. Wrap the relevant update in `act()` / `waitFor`. *Source: `review-notes/M7-report.md` §5 #4.*

## Resolved during the M7 walkthrough

Recorded for traceability (all on `main`):

- PWA stale cache — a normal reload now picks up new builds (`5fc6df3`).
- Shopping list — a checked auto row is reopened when its definition goes low again (`b422c80`).
- Consume (FIFO) — quantity defaults to 1 (`6374dd7`).
- Maintenance notifications — link to the instance detail page instead of a wrong target (`cdbe923`).
- PATCH null guard — explicit null on a non-nullable column returns 422 in the two blind-loop repos (`b6430a5`); the cross-repo consistency pass remains open as **A1**.
- Delete a maintenance schedule — also delete its notifications (`60eb95f`).

## Resolved during the M9.1 walkthrough

Recorded for traceability (on `main`):

- LLM chat URL double-`/v1` — `chat()` appended `/v1/chat/completions` while `list_models()` used `/models`, so a standard version-included base URL (`…/api/v1`) produced `…/api/v1/v1/chat/completions` → a 404 mislabeled as "model unavailable". Fixed so both endpoints append `/<endpoint>` to a base URL that already includes the version segment, with trailing-slash normalization (`e6971bb`).

## Resolved during the 0.1.0 pre-launch hardening

Recorded for traceability (on `main`). A small orchestrated "notification hygiene" round shipped alongside the 0.1.0 launch prep:

- **A2 — Orphaned notifications on subject deletion — FIXED.** `delete_for_subject` is now wired into both deletion paths: `StockInstanceService.delete` purges the lot's own `instance` (best_before / warranty) notifications **and** the `maintenance_schedule` notifications of the schedules that cascade-delete with it (the FK is `ondelete=CASCADE`, which drops the schedule rows but not their notifications); `ItemDefinitionService.delete` purges the definition's `low_stock` notifications (after the existing 409 has-instances guard). This removes the stale-bell-entry symptom and closes the silent-dedup hole (a recreated subject reusing a freed PK + same target date is no longer suppressed). Regression-tested including the cascade-maintenance case (`4f6eb69`).
- **Notification inbox: clear-all + per-row dismiss — NEW.** The inbox previously had no way to empty itself (only mark-read). Added soft-dismiss (`dismissed_at`, migration 0035): a "Clear all" action + a per-row dismiss on both the bell and the full page. Dismiss hides a row from the inbox **only** — it deliberately preserves the row's dedup anchor and low-stock episode state, so a still-active source does not re-spam on the next scan and the low-stock cadence is not reset (`be759c0` backend, `850f701` frontend).

## Design-deferred (by design, not defects)

These are intentionally out of scope and tracked in each milestone's design doc. From `docs/plan/milestones/M7.md` §13: usage-based maintenance, maintenance completion history, per-definition schedules, per-user maintenance lead time, and the TickTick shopping-list sync seam. From `docs/plan/milestones/M9.1.md` §13: the allow-loopback toggle (same-host Ollama), model auto-discovery UI, streaming / function-calling / structured-output, token & cost accounting + budgets, retry / backoff, multiple providers / fallback + per-user config, and secret encryption at rest.
