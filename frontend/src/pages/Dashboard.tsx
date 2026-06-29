/**
 * Dashboard — welcome overview and module entry-point cards.
 *
 * Layout: SimpleGrid (single column on mobile, three columns on md+).
 *
 * Card 1 (ExpiryCard): LIVE — fetches GET /api/expiring and shows
 *   a count + short list. Empty state when nothing is expiring.
 *   Links to /expiring for the full list.
 * Card 2 (durableCard): static placeholder linking to /items.
 * Card 3 (lowStockCard): LIVE — fetches GET /api/low-stock and shows
 *   a count + short list.  Empty state when nothing is low.
 *   Links to /low-stock for the full list.
 * Card 4 (MaintenanceCard): LIVE — fetches GET /api/maintenance-schedules?active=true,
 *   filters client-side for overdue/due_soon (server-provided status), sorts nearest-first,
 *   shows count + short list linking to instance detail. M7 §7.3.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  SimpleGrid,
  Card,
  Text,
  Title,
  Badge,
  Stack,
  ThemeIcon,
  Group,
  Anchor,
  Loader,
  List,
} from "@mantine/core";
import { Clock, Archive, TrendingDown, Tool } from "react-feather";
import { PageShell } from "../components/PageShell";
import { ExpiryBadge } from "../components/ExpiryBadge";
import { client } from "../api/client";
import { formatDate, formatQuantity } from "../i18n/format";
import type { components } from "../api/schema";

type LowStockItem = components["schemas"]["LowStockItem"];
type ExpiringItem = components["schemas"]["ExpiringItem"];
type MaintenanceScheduleResponse = components["schemas"]["MaintenanceScheduleResponse"];

// ── Static concept card ───────────────────────────────────────────────────────

interface ConceptCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  badgeLabel: string;
  /** Existing route to link to. Omit for purely future features. */
  linkTo?: string;
  linkLabel?: string;
}

function ConceptCard({
  icon,
  title,
  description,
  badgeLabel,
  linkTo,
  linkLabel,
}: ConceptCardProps) {
  return (
    <Card component="article">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <ThemeIcon size={44} radius="md" variant="light">
            {icon}
          </ThemeIcon>
          <Badge variant="light" color="gray" size="sm">
            {badgeLabel}
          </Badge>
        </Group>

        <Stack gap={6}>
          <Title order={3} size="h4">
            {title}
          </Title>
          <Text c="dimmed" size="sm" lh={1.5}>
            {description}
          </Text>
        </Stack>

        {linkTo && linkLabel && (
          <Anchor component={Link} to={linkTo} size="sm" mt="auto">
            {linkLabel}
          </Anchor>
        )}
      </Stack>
    </Card>
  );
}

// ── Live expiry tile ──────────────────────────────────────────────────────────

/**
 * The expiry / best-before card:
 *   - Fetches GET /api/expiring once on mount (default horizon = backend default 30 days).
 *   - Shows a count badge + short list (up to 3 lots; definition name · best_before_date
 *     · ExpiryBadge status cue), a link to the full /expiring view.
 *   - Empty state when nothing is expiring within the window.
 *   - Never re-derives the expiring rule client-side (backend owns the rule).
 */
function ExpiryCard() {
  const { t } = useTranslation("dashboard");

  const [items, setItems] = useState<ExpiringItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const result = await client.GET("/api/expiring");
      if (cancelled) return;
      const data = result?.data;
      if (Array.isArray(data)) {
        setItems(data);
      } else {
        setFetchError(true);
      }
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const previewItems = items?.slice(0, 3) ?? [];
  const count = items?.length ?? 0;

  return (
    <Card component="article" data-testid="expiry-tile">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <ThemeIcon size={44} radius="md" variant="light" color="red">
            <Clock size={22} strokeWidth={1.5} />
          </ThemeIcon>
          {!loading && !fetchError && count > 0 && (
            <Badge
              variant="filled"
              color="red"
              size="sm"
              data-testid="expiry-count-badge"
            >
              {t("expiryCard.countLabel", { count })}
            </Badge>
          )}
        </Group>

        <Stack gap={6}>
          <Title order={3} size="h4">
            {t("expiryCard.title")}
          </Title>

          {loading && <Loader size="xs" />}

          {!loading && fetchError && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="expiry-load-error"
            >
              {t("expiryCard.loadError")}
            </Text>
          )}

          {!loading && !fetchError && count === 0 && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="expiry-empty-state"
            >
              {t("expiryCard.emptyState")}
            </Text>
          )}

          {!loading && !fetchError && count > 0 && (
            <List
              size="sm"
              spacing={4}
              data-testid="expiry-list"
            >
              {previewItems.map((item) => (
                <List.Item key={item.instance_id} data-testid={`expiry-item-${item.instance_id}`}>
                  <Text size="sm" span fw={500}>
                    {item.name}
                  </Text>
                  <Text size="sm" span c="dimmed">
                    {" "}{formatDate(item.best_before_date)}
                  </Text>
                  {" "}
                  <ExpiryBadge bestBeforeDate={item.best_before_date} />
                </List.Item>
              ))}
            </List>
          )}
        </Stack>

        {!loading && !fetchError && count > 0 && (
          <Anchor
            component={Link}
            to="/expiring"
            size="sm"
            mt="auto"
            data-testid="expiry-view-link"
          >
            {t("expiryCard.viewAll")}
          </Anchor>
        )}
      </Stack>
    </Card>
  );
}

// ── Live low-stock tile ───────────────────────────────────────────────────────

/**
 * The consumable / low-stock card:
 *   - Fetches GET /api/low-stock once on mount.
 *   - Shows a count + short list (up to 3 items inline; link to full view).
 *   - Empty state when nothing is low.
 *   - Never re-derives the low-stock rule client-side (backend owns the rule).
 */
function LowStockCard() {
  const { t } = useTranslation("dashboard");
  const { t: tStock } = useTranslation("stock");

  const [items, setItems] = useState<LowStockItem[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const result = await client.GET("/api/low-stock");
      if (cancelled) return;
      const data = result?.data;
      if (Array.isArray(data)) {
        setItems(data);
      } else {
        setFetchError(true);
      }
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const previewItems = items?.slice(0, 3) ?? [];
  const count = items?.length ?? 0;

  return (
    <Card component="article" data-testid="low-stock-tile">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <ThemeIcon size={44} radius="md" variant="light" color="orange">
            <TrendingDown size={22} strokeWidth={1.5} />
          </ThemeIcon>
          {!loading && !fetchError && count > 0 && (
            <Badge
              variant="filled"
              color="orange"
              size="sm"
              data-testid="low-stock-count-badge"
            >
              {t("lowStockCard.countLabel", { count })}
            </Badge>
          )}
        </Group>

        <Stack gap={6}>
          <Title order={3} size="h4">
            {t("lowStockCard.title")}
          </Title>

          {loading && <Loader size="xs" />}

          {!loading && fetchError && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="low-stock-load-error"
            >
              {t("lowStockCard.loadError")}
            </Text>
          )}

          {!loading && !fetchError && count === 0 && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="low-stock-empty-state"
            >
              {t("lowStockCard.emptyState")}
            </Text>
          )}

          {!loading && !fetchError && count > 0 && (
            <List
              size="sm"
              spacing={4}
              data-testid="low-stock-list"
            >
              {previewItems.map((item) => (
                <List.Item key={item.definition_id} data-testid={`low-stock-item-${item.definition_id}`}>
                  <Text size="sm" span fw={500}>
                    {item.name}
                  </Text>
                  {item.mode === "exact" ? (
                    <Text size="sm" span c="dimmed">
                      {" "}
                      {formatQuantity(item.current)}
                      {" / "}
                      {formatQuantity(item.threshold)}
                    </Text>
                  ) : (
                    <Text size="sm" span c="orange">
                      {" "}
                      ({tStock("stockLevel.low")})
                    </Text>
                  )}
                </List.Item>
              ))}
            </List>
          )}
        </Stack>

        {!loading && !fetchError && count > 0 && (
          <Anchor
            component={Link}
            to="/low-stock"
            size="sm"
            mt="auto"
            data-testid="low-stock-view-link"
          >
            {t("lowStockCard.viewAll")}
          </Anchor>
        )}
      </Stack>
    </Card>
  );
}

// ── Live upcoming-maintenance tile ────────────────────────────────────────────

/**
 * Upcoming-maintenance tile (M7 §7.3):
 *   - Fetches GET /api/maintenance-schedules?active=true once on mount.
 *   - Filters CLIENT-SIDE: keeps rows whose server-provided `status` is
 *     'overdue' or 'due_soon'. Does NOT add any query param for this — the
 *     design doc explicitly requires client-side filtering on the server field.
 *   - Sorts by next_due_date ascending (nearest-first).
 *   - Shows a count badge + short list (up to 3; instance name · task name · due date),
 *     each linking to the instance detail route (/instances/{instance_id}).
 *   - Empty state when nothing is due soon.
 */
function MaintenanceCard() {
  const { t } = useTranslation("dashboard");

  const [allSchedules, setAllSchedules] = useState<MaintenanceScheduleResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const result = await client.GET("/api/maintenance-schedules", {
        params: { query: { active: true } },
      });
      if (cancelled) return;
      const data = result?.data;
      if (Array.isArray(data)) {
        setAllSchedules(data);
      } else {
        setFetchError(true);
      }
      setLoading(false);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Filter client-side: keep overdue + due_soon; sort nearest-first.
  const dueSchedules = (allSchedules ?? [])
    .filter((s) => s.status === "overdue" || s.status === "due_soon")
    .sort((a, b) => a.next_due_date.localeCompare(b.next_due_date));

  const count = dueSchedules.length;
  const previewItems = dueSchedules.slice(0, 3);

  return (
    <Card component="article" data-testid="maintenance-tile">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <ThemeIcon size={44} radius="md" variant="light" color="blue">
            <Tool size={22} strokeWidth={1.5} />
          </ThemeIcon>
          {!loading && !fetchError && count > 0 && (
            <Badge
              variant="filled"
              color="blue"
              size="sm"
              data-testid="maintenance-count-badge"
            >
              {t("maintenanceCard.countLabel", { count })}
            </Badge>
          )}
        </Group>

        <Stack gap={6}>
          <Title order={3} size="h4">
            {t("maintenanceCard.title")}
          </Title>

          {loading && <Loader size="xs" />}

          {!loading && fetchError && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="maintenance-load-error"
            >
              {t("maintenanceCard.loadError")}
            </Text>
          )}

          {!loading && !fetchError && count === 0 && (
            <Text
              c="dimmed"
              size="sm"
              lh={1.5}
              data-testid="maintenance-empty-state"
            >
              {t("maintenanceCard.emptyState")}
            </Text>
          )}

          {!loading && !fetchError && count > 0 && (
            <List
              size="sm"
              spacing={4}
              data-testid="maintenance-list"
            >
              {previewItems.map((s) => (
                <List.Item key={s.id} data-testid={`maintenance-item-${s.id}`}>
                  <Anchor
                    component={Link}
                    to={`/instances/${s.instance_id}`}
                    size="sm"
                    fw={500}
                  >
                    {s.instance_name}
                  </Anchor>
                  <Text size="sm" span c="dimmed">
                    {" — "}{s.name}
                  </Text>
                  <Text size="sm" span c={s.status === "overdue" ? "red" : "orange"}>
                    {" "}{formatDate(s.next_due_date)}
                  </Text>
                </List.Item>
              ))}
            </List>
          )}
        </Stack>
      </Stack>
    </Card>
  );
}

// ── Dashboard page ────────────────────────────────────────────────────────────

export function Dashboard() {
  const { t: tNav } = useTranslation("nav");
  const { t } = useTranslation("dashboard");

  return (
    <PageShell title={tNav("dashboard")} subtitle={t("subtitle")}>
      <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
        <ExpiryCard />

        <ConceptCard
          icon={<Archive size={22} strokeWidth={1.5} />}
          title={t("durableCard.title")}
          description={t("durableCard.description")}
          badgeLabel={t("durableCard.badge")}
          linkTo="/items"
          linkLabel={tNav("items")}
        />

        <LowStockCard />

        <MaintenanceCard />
      </SimpleGrid>
    </PageShell>
  );
}
