/**
 * EmptyState — shown when a list/page has no items yet.
 */
import { Center, Stack, Text } from "@mantine/core";
import { Inbox } from "react-feather";

interface EmptyStateProps {
  message?: string;
}

export function EmptyState({ message = "Nothing here yet." }: EmptyStateProps) {
  return (
    <Center h={200}>
      <Stack align="center" gap="sm">
        <Inbox size={40} strokeWidth={1.5} />
        <Text c="dimmed" size="sm">
          {message}
        </Text>
      </Stack>
    </Center>
  );
}
