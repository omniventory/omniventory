/**
 * Locations page — tree browse and management for the location hierarchy.
 *
 * Delegates all rendering and CRUD logic to the shared TreeBrowser component,
 * parameterised with resource="locations".
 */
import { useTranslation } from "react-i18next";
import { PageShell } from "../components/PageShell";
import { TreeBrowser } from "../components/TreeBrowser";

export function Locations() {
  const { t } = useTranslation("nav");
  return (
    <PageShell title={t("locations")}>
      <TreeBrowser resource="locations" />
    </PageShell>
  );
}
