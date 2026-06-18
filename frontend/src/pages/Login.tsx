/**
 * Login page.
 *
 * Posts credentials via the typed client → on success notifies the parent to
 * transition into the authenticated shell.  Session is cookie-based (HttpOnly);
 * nothing is stored in localStorage/sessionStorage.
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
import type { components } from "../api/schema";

type UserResponse = components["schemas"]["UserResponse"];

interface LoginProps {
  onSuccess: (user: UserResponse) => void;
}

export function Login({ onSuccess }: LoginProps) {
  const { t } = useTranslation("auth");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const { data, error: apiError } = await client.POST("/api/auth/login", {
      body: { email, password },
    });

    setLoading(false);

    if (apiError) {
      setError(mapApiError(apiError));
      return;
    }

    if (data) {
      onSuccess(data);
    }
  }

  return (
    <AuthLayout title={t("login.title")} subtitle={t("login.subtitle")}>
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
            label={t("login.emailLabel")}
            placeholder={t("login.emailPlaceholder")}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            required
            autoComplete="email"
          />

          <PasswordInput
            label={t("login.passwordLabel")}
            placeholder={t("login.passwordPlaceholder")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
            autoComplete="current-password"
          />

          <Button type="submit" fullWidth loading={loading}>
            {t("login.submit")}
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
