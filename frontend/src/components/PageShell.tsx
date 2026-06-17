/**
 * PageShell — thin wrapper giving each page a consistent title + content area.
 * Keeps pages from each reinventing their own container.
 *
 * Props:
 *   title    — page heading (rendered as Title order={2})
 *   subtitle — optional dimmed sub-line rendered below the title
 *   actions  — optional node rendered to the right of the title (e.g. a "New" button)
 *   children — page body
 */
import { Group, Stack, Text, Title } from "@mantine/core";

interface PageShellProps {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}

export function PageShell({ title, subtitle, actions, children }: PageShellProps) {
  return (
    <Stack gap="lg">
      <Stack gap={4}>
        <Group justify="space-between" align="center" wrap="nowrap">
          <Title order={2}>{title}</Title>
          {actions}
        </Group>
        {subtitle && (
          <Text c="dimmed" size="sm">
            {subtitle}
          </Text>
        )}
      </Stack>
      {children}
    </Stack>
  );
}
