/**
 * ErrorState — shown when an operation or data load fails.
 * Renders as an ARIA-role alert so screen readers announce it immediately.
 */
import { Alert } from "@mantine/core";
import { AlertCircle } from "react-feather";
import { useTranslation } from "react-i18next";

interface ErrorStateProps {
  message?: string;
}

export function ErrorState({ message }: ErrorStateProps) {
  const { t } = useTranslation();
  const displayMessage = message ?? t("status.somethingWentWrong");
  return (
    <Alert
      icon={<AlertCircle size={16} />}
      title={t("status.error")}
      color="red"
      variant="light"
      radius="md"
      role="alert"
    >
      {displayMessage}
    </Alert>
  );
}
