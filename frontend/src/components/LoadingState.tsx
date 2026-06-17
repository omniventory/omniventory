/**
 * LoadingState — centered spinner for async data loads.
 */
import { Center, Loader, Stack, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message }: LoadingStateProps) {
  const { t } = useTranslation();
  const displayMessage = message ?? t("status.loading");
  return (
    <Center h={200}>
      <Stack align="center" gap="sm">
        <Loader size="md" />
        <Text c="dimmed" size="sm">
          {displayMessage}
        </Text>
      </Stack>
    </Center>
  );
}
