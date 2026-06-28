/**
 * Audit log page — admin-only (VIEW_AUDIT).
 *
 * Features:
 *  - Paginated table of security/admin events: time, event, actor, target,
 *    detail, IP.
 *  - Filters: event type (NativeSelect over 14 known codes + "all"),
 *    actor ID (number input), date range (from / to date inputs).
 *  - Pagination: limit=50, prev/next buttons driven by the envelope total.
 *  - Read-only — no mutations.
 *
 * Event type labels: localized via the "audit" namespace using the event code
 * as a nested key path (e.g. t("events.auth.login_succeeded")), with the raw
 * code as the defaultValue fallback for any unknown future type.
 *
 * params rendering: rendered as a compact "key=value, …" Code string.
 * The API returns params as a parsed dict (or null); the code also guards
 * defensively against a JSON-string value.
 *
 * Dates use formatDate (M1.5 src/i18n/format). Query params use the exact
 * field names from the OpenAPI schema: event_type, actor_id, from, to,
 * limit, offset.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Code,
  Group,
  NativeSelect,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { AlertCircle, FileText } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { PageShell } from "../components/PageShell";
import { LoadingState } from "../components/LoadingState";
import { formatDate } from "../i18n/format";
import type { components } from "../api/schema";

type AuditLogResponse = components["schemas"]["AuditLogResponse"];
type AuditLogListResponse = components["schemas"]["AuditLogListResponse"];

const DEFAULT_LIMIT = 50;

/**
 * The 14 event type codes defined in M6.md §3.2.
 * Used to populate the event-type filter Select and localize event labels.
 */
const EVENT_TYPES = [
  "auth.login_succeeded",
  "auth.login_failed",
  "auth.logout",
  "user.created",
  "user.role_changed",
  "user.deactivated",
  "user.reactivated",
  "user.deleted",
  "password.changed",
  "password.reset",
  "invitation.issued",
  "invitation.accepted",
  "invitation.revoked",
  "settings.changed",
] as const;

/**
 * Render an AuditLogResponse params dict as a compact "key=value, …" string.
 *
 * The API returns params as a parsed dict (or null) — the _parse_params
 * validator on the backend deserialises the stored JSON string before the
 * response is serialised. We guard defensively for a raw JSON string too.
 */
function renderParams(
  params: Record<string, unknown> | string | null | undefined,
): string {
  if (params === null || params === undefined) return "";

  let dict: Record<string, unknown>;
  if (typeof params === "string") {
    try {
      dict = JSON.parse(params) as Record<string, unknown>;
    } catch {
      // Not valid JSON — return the raw string for transparency.
      return params;
    }
  } else {
    dict = params;
  }

  const entries = Object.entries(dict);
  if (entries.length === 0) return "";
  return entries.map(([k, v]) => `${k}=${String(v)}`).join(", ");
}

export function Audit() {
  const { t } = useTranslation("audit");

  // ── Filter state ─────────────────────────────────────────────────────────────
  const [eventType, setEventType] = useState<string>("");
  const [actorId, setActorId] = useState<string>("");
  const [from, setFrom] = useState<string>("");
  const [to, setTo] = useState<string>("");

  // ── Pagination state ─────────────────────────────────────────────────────────
  const [offset, setOffset] = useState(0);

  // ── Data state ───────────────────────────────────────────────────────────────
  const [data, setData] = useState<AuditLogListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Fetch ─────────────────────────────────────────────────────────────────────

  const fetchAuditLog = useCallback(
    async (
      currentOffset: number,
      currentEventType: string,
      currentActorId: string,
      currentFrom: string,
      currentTo: string,
    ) => {
      setLoading(true);
      setError(null);

      const { data: result, error: err } = await client.GET("/api/audit", {
        params: {
          query: {
            limit: DEFAULT_LIMIT,
            offset: currentOffset,
            event_type: currentEventType || undefined,
            actor_id: currentActorId
              ? parseInt(currentActorId, 10)
              : undefined,
            from: currentFrom || undefined,
            to: currentTo || undefined,
          },
        },
      });

      if (err || !result) {
        setError(mapApiError(err));
      } else {
        setData(result);
      }
      setLoading(false);
    },
    [],
  );

  // Re-fetch whenever any filter or pagination changes.
  // React 18 auto-batches the four setters in applyFilter into one update,
  // so this effect fires exactly once per filter change.
  useEffect(() => {
    void fetchAuditLog(offset, eventType, actorId, from, to);
  }, [offset, eventType, actorId, from, to, fetchAuditLog]);

  // ── Filter helpers ────────────────────────────────────────────────────────────

  /**
   * Apply new filter values and reset the offset to 0 so the user sees the
   * first page of results immediately.
   */
  function applyFilter(
    newEventType: string,
    newActorId: string,
    newFrom: string,
    newTo: string,
  ) {
    setEventType(newEventType);
    setActorId(newActorId);
    setFrom(newFrom);
    setTo(newTo);
    setOffset(0);
  }

  // ── Pagination helpers ────────────────────────────────────────────────────────

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const limit = data?.limit ?? DEFAULT_LIMIT;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + limit, total);
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  // ── NativeSelect data ─────────────────────────────────────────────────────────

  const eventTypeData = [
    { value: "", label: t("filters.all") },
    ...EVENT_TYPES.map((et) => ({
      value: et,
      // Localize via nested key path e.g. "events.auth.login_succeeded".
      // Falls back to the raw event type code for any unknown future type.
      label: t(`events.${et}`, { defaultValue: et }),
    })),
  ];

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <PageShell title={t("page.title")} subtitle={t("page.subtitle")}>
      {/* Filters */}
      <Paper shadow="xs" radius="md" p="md">
        <Group gap="sm" align="flex-end" wrap="wrap">
          <NativeSelect
            label={t("filters.eventType")}
            value={eventType}
            onChange={(e) => {
              applyFilter(e.currentTarget.value, actorId, from, to);
            }}
            data={eventTypeData}
            data-testid="filter-event-type"
          />

          <TextInput
            label={t("filters.actorId")}
            type="number"
            value={actorId}
            placeholder={t("filters.actorIdPlaceholder")}
            onChange={(e) => applyFilter(eventType, e.currentTarget.value, from, to)}
            data-testid="filter-actor-id"
            style={{ width: 130 }}
          />

          <TextInput
            label={t("filters.from")}
            type="date"
            value={from}
            onChange={(e) =>
              applyFilter(eventType, actorId, e.currentTarget.value, to)
            }
            data-testid="filter-from"
          />

          <TextInput
            label={t("filters.to")}
            type="date"
            value={to}
            onChange={(e) =>
              applyFilter(eventType, actorId, from, e.currentTarget.value)
            }
            data-testid="filter-to"
          />
        </Group>
      </Paper>

      {/* Loading */}
      {loading && <LoadingState />}

      {/* Error */}
      {!loading && error && (
        <Alert
          icon={<AlertCircle size={16} />}
          color="red"
          variant="light"
          radius="md"
        >
          {error}
        </Alert>
      )}

      {/* Table + pagination */}
      {!loading && !error && (
        <Stack gap="sm">
          <Paper shadow="xs" radius="md" withBorder>
            <Table horizontalSpacing="sm" verticalSpacing="xs" striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("columns.time")}</Table.Th>
                  <Table.Th>{t("columns.event")}</Table.Th>
                  <Table.Th>{t("columns.actor")}</Table.Th>
                  <Table.Th>{t("columns.target")}</Table.Th>
                  <Table.Th>{t("columns.detail")}</Table.Th>
                  <Table.Th>{t("columns.ip")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={6} ta="center" c="dimmed">
                      {t("empty")}
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  items.map((row: AuditLogResponse) => {
                    const paramsStr = renderParams(
                      row.params as Record<string, unknown> | null,
                    );
                    const targetCell =
                      row.target_type
                        ? `${row.target_type}${row.target_id != null ? ` #${row.target_id}` : ""}`
                        : "—";

                    return (
                      <Table.Tr key={row.id} data-testid={`audit-row-${row.id}`}>
                        <Table.Td style={{ whiteSpace: "nowrap" }}>
                          {formatDate(row.created_at)}
                        </Table.Td>
                        <Table.Td>
                          {/* Localize via nested key e.g. "events.auth.login_succeeded";
                              fall back to the raw code for any unknown future type. */}
                          {t(`events.${row.event_type}`, {
                            defaultValue: row.event_type,
                          })}
                        </Table.Td>
                        <Table.Td>
                          {row.actor_email ?? t("nullActor")}
                        </Table.Td>
                        <Table.Td>{targetCell}</Table.Td>
                        <Table.Td>
                          {paramsStr ? (
                            <Code fz="xs">{paramsStr}</Code>
                          ) : (
                            "—"
                          )}
                        </Table.Td>
                        <Table.Td>{row.ip_address ?? "—"}</Table.Td>
                      </Table.Tr>
                    );
                  })
                )}
              </Table.Tbody>
            </Table>
          </Paper>

          {/* Pagination controls */}
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              {total > 0
                ? t("pagination.showing", {
                    from: showingFrom,
                    to: showingTo,
                    total,
                  })
                : ""}
            </Text>
            <Group gap="xs">
              <Button
                variant="default"
                size="xs"
                disabled={!hasPrev}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                data-testid="prev-btn"
                leftSection={<FileText size={12} />}
              >
                {t("pagination.prev")}
              </Button>
              <Button
                variant="default"
                size="xs"
                disabled={!hasNext}
                onClick={() => setOffset(offset + limit)}
                data-testid="next-btn"
              >
                {t("pagination.next")}
              </Button>
            </Group>
          </Group>
        </Stack>
      )}
    </PageShell>
  );
}
