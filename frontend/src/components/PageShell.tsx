/**
 * PageShell — thin wrapper giving each page a consistent title + content area.
 * Keeps pages from each reinventing their own container.
 */
import { Stack, Title } from "@mantine/core";

interface PageShellProps {
  title: string;
  children?: React.ReactNode;
}

export function PageShell({ title, children }: PageShellProps) {
  return (
    <Stack gap="lg">
      <Title order={2}>{title}</Title>
      {children}
    </Stack>
  );
}
