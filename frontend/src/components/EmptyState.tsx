/**
 * EmptyState — shown when a list/page has no items yet.
 */
import { Center, Stack, Text } from "@mantine/core";
import { Inbox } from "react-feather";
import { useTranslation } from "react-i18next";

interface EmptyStateProps {
  message?: string;
}

export function EmptyState({ message }: EmptyStateProps) {
  const { t } = useTranslation();
  const displayMessage = message ?? t("status.nothingHere");
  return (
    <Center h={200}>
      <Stack align="center" gap="sm">
        <Inbox size={40} strokeWidth={1.5} />
        <Text c="dimmed" size="sm">
          {displayMessage}
        </Text>
      </Stack>
    </Center>
  );
}
