/**
 * ErrorState — shown when an operation or data load fails.
 */
import { Alert, Text } from "@mantine/core";
import { AlertCircle } from "react-feather";

interface ErrorStateProps {
  message?: string;
}

export function ErrorState({
  message = "Something went wrong.",
}: ErrorStateProps) {
  return (
    <Alert
      icon={<AlertCircle size={16} />}
      title="Error"
      color="red"
      variant="light"
    >
      <Text size="sm">{message}</Text>
    </Alert>
  );
}
