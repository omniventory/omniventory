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
  const { t: tNav } = useTranslation("nav");
  const { t: tCat } = useTranslation("categories");
  return (
    <PageShell title={tNav("categories")} subtitle={tCat("page.subtitle")}>
      <TreeBrowser resource="categories" />
    </PageShell>
  );
}
