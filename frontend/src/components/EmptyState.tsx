/**
 * EmptyState — shown when a list/page has no items yet.
 */
import { Center, Stack, Text, ThemeIcon } from "@mantine/core";
import { Inbox } from "react-feather";
import { useTranslation } from "react-i18next";

interface EmptyStateProps {
  message?: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  const { t } = useTranslation();
  const displayMessage = message ?? t("status.nothingHere");
  return (
    <Center py="xl" h={220}>
      <Stack align="center" gap="md">
        <ThemeIcon size={56} radius="xl" variant="light" color="gray">
          <Inbox size={28} strokeWidth={1.5} />
        </ThemeIcon>
        <Text c="dimmed" size="sm" ta="center" maw={280}>
          {displayMessage}
        </Text>
      </Stack>
    </Center>
  );
}
