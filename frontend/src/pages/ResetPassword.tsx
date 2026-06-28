/**
 * ResetPassword — pre-auth public page for accepting a password-reset link.
 *
 * Rendered by App.tsx BEFORE the auth gate when pathname === "/password-reset/accept".
 * Reads `token` from window.location.search via URLSearchParams.
 *
 * Flow:
 *  1. On mount: GET /api/password-reset/accept?token=<token> → show masked email.
 *     On 400 auth.invalid_token → show error state with link to Login.
 *  2. User sets new password + confirm; on submit:
 *     POST /api/password-reset/accept {token, password} → success.
 *  3. On success: show confirmation, redirect to "/" via window.location.assign.
 *     (No auto-login — the user must sign in with their new credentials.)
 */
import { useEffect, useState } from "react";
import {
  Stack,
  PasswordInput,
  Button,
  Alert,
  Text,
} from "@mantine/core";
import { AlertCircle, CheckCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { AuthLayout } from "../components/AuthLayout";
import type { components } from "../api/schema";

type PasswordResetPublic = components["schemas"]["PasswordResetPublic"];

export function ResetPassword() {
  const { t } = useTranslation("account");

  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  const [validating, setValidating] = useState(true);
  const [resetData, setResetData] = useState<PasswordResetPublic | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    async function validate() {
      if (!token) {
        setTokenError(t("resetPassword.invalidMessage"));
        setValidating(false);
        return;
      }
      const { data, error } = await client.GET("/api/password-reset/accept", {
        params: { query: { token } },
      });
      if (error || !data) {
        setTokenError(mapApiError(error));
      } else {
        setResetData(data);
      }
      setValidating(false);
    }
    void validate();
  }, [token, t]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setSubmitError(t("resetPassword.mismatchError"));
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const { error } = await client.POST("/api/password-reset/accept", {
        body: { token, password },
      });
      if (error) {
        setSubmitError(mapApiError(error));
        return;
      }
      setDone(true);
      // Redirect to login after a brief moment so the success message is visible.
      setTimeout(() => {
        window.location.assign("/");
      }, 1500);
    } finally {
      setSubmitting(false);
    }
  }

  if (validating) {
    return (
      <AuthLayout title={t("resetPassword.title")}>
        <Text c="dimmed" ta="center" data-testid="reset-validating">
          Loading…
        </Text>
      </AuthLayout>
    );
  }

  if (tokenError || !resetData) {
    return (
      <AuthLayout title={t("resetPassword.invalidTitle")}>
        <Stack gap="md">
          <Alert
            icon={<AlertCircle size={16} />}
            color="red"
            variant="light"
            data-testid="reset-token-error"
          >
            {tokenError ?? t("resetPassword.invalidMessage")}
          </Alert>
          <Button
            variant="subtle"
            onClick={() => window.location.assign("/")}
            data-testid="reset-go-login-btn"
          >
            {t("resetPassword.goToLogin")}
          </Button>
        </Stack>
      </AuthLayout>
    );
  }

  if (done) {
    return (
      <AuthLayout title={t("resetPassword.title")}>
        <Alert
          icon={<CheckCircle size={16} />}
          color="teal"
          variant="light"
          data-testid="reset-success"
        >
          {t("resetPassword.success")}
        </Alert>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("resetPassword.title")} subtitle={t("resetPassword.subtitle")}>
      <form onSubmit={handleSubmit}>
        <Stack gap="md">
          <Text size="sm" c="dimmed" data-testid="reset-for-email">
            {t("resetPassword.forEmail", { email_masked: resetData.email_masked })}
          </Text>
          <PasswordInput
            label={t("resetPassword.passwordLabel")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
            data-testid="reset-password-input"
          />
          <PasswordInput
            label={t("resetPassword.confirmLabel")}
            value={confirm}
            onChange={(e) => setConfirm(e.currentTarget.value)}
            required
            data-testid="reset-confirm-input"
          />

          {submitError && (
            <Alert
              icon={<AlertCircle size={16} />}
              color="red"
              variant="light"
              data-testid="reset-submit-error"
            >
              {submitError}
            </Alert>
          )}

          <Button type="submit" loading={submitting} data-testid="reset-accept-btn">
            {t("resetPassword.submit")}
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
