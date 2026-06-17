/**
 * Dashboard — placeholder page for the root route ("/").
 *
 * Content will expand in later milestones.
 */
import { useTranslation } from "react-i18next";
import { PageShell } from "../components/PageShell";
import { EmptyState } from "../components/EmptyState";

export function Dashboard() {
  const { t } = useTranslation("nav");
  return (
    <PageShell title={t("dashboard")}>
      <EmptyState message={t("dashboardPlaceholder")} />
    </PageShell>
  );
}
