/**
 * First-run setup page.
 *
 * Shown when GET /api/auth/setup-status returns { setup_required: true },
 * meaning no users exist yet.  The user fills in an email + password to
 * create the first (admin) account.  On success, the parent is notified to
 * transition to the Login page — we do NOT auto-login (by design).
 *
 * Auth: unauthenticated endpoint; no session cookie required or set here.
 */
import { useState } from "react";
import {
  Stack,
  TextInput,
  PasswordInput,
  Button,
  Alert,
} from "@mantine/core";
import { AlertCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { AuthLayout } from "../components/AuthLayout";

interface SetupProps {
  /** Called after the first admin is created; parent transitions to Login. */
  onSuccess: () => void;
}

export function Setup({ onSuccess }: SetupProps) {
  const { t } = useTranslation("auth");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const { error: apiError } = await client.POST("/api/auth/setup", {
      body: { email, password },
    });

    setLoading(false);

    if (apiError) {
      setError(mapApiError(apiError));
      return;
    }

    onSuccess();
  }

  return (
    <AuthLayout title={t("setup.title")} subtitle={t("setup.subtitle")}>
      <form onSubmit={handleSubmit}>
        <Stack gap="lg">
          {error && (
            <Alert
              icon={<AlertCircle size={16} />}
              color="red"
              variant="light"
              role="alert"
            >
              {error}
            </Alert>
          )}

          <TextInput
            label={t("setup.emailLabel")}
            placeholder={t("setup.emailPlaceholder")}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            required
            autoComplete="email"
          />

          <PasswordInput
            label={t("setup.passwordLabel")}
            placeholder={t("setup.passwordPlaceholder")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
            autoComplete="new-password"
          />

          <Button type="submit" fullWidth loading={loading}>
            {t("setup.submit")}
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
