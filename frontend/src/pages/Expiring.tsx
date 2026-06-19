/**
 * Expiring page — full list of all currently expiring/expired lots.
 *
 * Fetches from GET /api/expiring?within_days=N and renders a table with:
 *   - Each row: definition name (links to /instances/:instance_id) + best_before_date
 *     + ExpiryBadge status cue.
 *
 * The server returns lots ordered soonest-first (expired lots lead because their
 * date is earliest). This component preserves that order: no client-side sorting.
 *
 * A horizon control (7 / 30 / 90 days) re-queries GET /api/expiring?within_days=N.
 *
 * Empty state shown when nothing is expiring within the window.
 * No pagination needed for M3 (list bounded by lot count in household dataset).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Anchor,
  Table,
  Text,
  Stack,
  Group,
  Loader,
  SegmentedControl,
} from "@mantine/core";
import { PageShell } from "../components/PageShell";
import { ErrorState } from "../components/ErrorState";
import { ExpiryBadge } from "../components/ExpiryBadge";
import { client } from "../api/client";
import { formatDate } from "../i18n/format";
import type { components } from "../api/schema";

type ExpiringItem = components["schemas"]["ExpiringItem"];

/** The available horizon values for the within_days control. */
const HORIZON_OPTIONS = [7, 30, 90] as const;
type HorizonDays = (typeof HORIZON_OPTIONS)[number];

export function Expiring() {
  const { t } = useTranslation("expiry");

  const [items, setItems] = useState<ExpiringItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<HorizonDays>(30);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      const { data, error: apiError } = await client.GET("/api/expiring", {
        params: { query: { within_days: horizon } },
      });
      if (cancelled) return;
      if (apiError || !Array.isArray(data)) {
        setError(t("loadError"));
        setLoading(false);
        return;
      }
      setItems(data);
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [horizon, t]);

  return (
    <PageShell title={t("pageTitle")}>
      {/* Horizon control */}
      <Group mb="md" data-testid="horizon-control">
        <Text size="sm" fw={500}>
          {t("horizon")}:
        </Text>
        <SegmentedControl
          data-testid="horizon-segmented"
          value={String(horizon)}
          onChange={(val) => {
            const n = Number(val) as HorizonDays;
            setHorizon(n);
          }}
          data={HORIZON_OPTIONS.map((d) => ({
            label: t("horizonDays", { count: d }),
            value: String(d),
          }))}
          size="xs"
        />
      </Group>

      {loading && (
        <Group justify="center" py="xl">
          <Loader size="sm" />
        </Group>
      )}

      {!loading && error && (
        <ErrorState message={error} />
      )}

      {!loading && !error && items !== null && items.length === 0 && (
        <Text
          c="dimmed"
          size="sm"
          ta="center"
          py="xl"
          data-testid="expiring-empty"
        >
          {t("emptyState")}
        </Text>
      )}

      {!loading && !error && items !== null && items.length > 0 && (
        <Stack gap="md">
          <Text c="dimmed" size="sm" data-testid="expiring-count">
            {t("countLabel", { count: items.length })}
          </Text>

          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("nameLabel")}</Table.Th>
                <Table.Th>{t("bestBeforeColumn")}</Table.Th>
                <Table.Th>{t("statusLabel")}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr
                  key={item.instance_id}
                  data-testid={`expiring-row-${item.instance_id}`}
                >
                  <Table.Td>
                    <Anchor
                      component={Link}
                      to={`/instances/${item.instance_id}`}
                      size="sm"
                      fw={500}
                    >
                      {item.name}
                    </Anchor>
                  </Table.Td>
                  <Table.Td data-testid={`expiring-date-${item.instance_id}`}>
                    <Text size="sm">{formatDate(item.best_before_date)}</Text>
                  </Table.Td>
                  <Table.Td data-testid={`expiring-status-${item.instance_id}`}>
                    <ExpiryBadge bestBeforeDate={item.best_before_date} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      )}
    </PageShell>
  );
}
