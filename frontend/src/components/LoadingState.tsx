/**
 * LoadingState — centered spinner for async data loads.
 */
import { Center, Loader, Stack, Text } from "@mantine/core";

interface LoadingStateProps {
  message?: string;
}

export function LoadingState({ message = "Loading…" }: LoadingStateProps) {
  return (
    <Center h={200}>
      <Stack align="center" gap="sm">
        <Loader size="md" />
        <Text c="dimmed" size="sm">
          {message}
        </Text>
      </Stack>
    </Center>
  );
}
