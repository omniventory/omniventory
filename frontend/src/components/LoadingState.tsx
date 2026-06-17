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
    <Center py="xl" h={220}>
      <Stack align="center" gap="md">
        <Loader size="lg" color="teal" />
        <Text c="dimmed" size="sm" ta="center">
          {displayMessage}
        </Text>
      </Stack>
    </Center>
  );
}
