/**
 * Categories page — tree browse and management for the category hierarchy.
 *
 * Delegates all rendering and CRUD logic to the shared TreeBrowser component,
 * parameterised with resource="categories".
 */
import { useTranslation } from "react-i18next";
import { PageShell } from "../components/PageShell";
import { TreeBrowser } from "../components/TreeBrowser";

export function Categories() {
  const { t } = useTranslation("nav");
  return (
    <PageShell title={t("categories")}>
      <TreeBrowser resource="categories" />
    </PageShell>
  );
}
