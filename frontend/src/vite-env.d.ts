/// <reference types="vite/client" />

/** Allow importing CSS files (e.g. Mantine's "@mantine/core/styles.css"). */
declare module "*.css" {
  const content: Record<string, string>;
  export default content;
}
