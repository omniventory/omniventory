/**
 * AcceptInvite — pre-auth public page for accepting an invite link.
 *
 * Rendered by App.tsx BEFORE the auth gate when pathname === "/invite/accept".
 * Reads `token` from window.location.search via URLSearchParams.
 *
 * Flow:
 *  1. On mount: GET /api/invitations/accept?token=<token> → show email + role.
 *     On 400 auth.invalid_token → show error state with link to Login.
 *  2. User sets password + confirm; on submit:
 *     POST /api/invitations/accept {token, password} → success.
 *  3. On success: show confirmation, redirect to "/" via window.location.assign.
 *     (No auto-login — the user must sign in with their new credentials.)
 */
import { useEffect, useState } from "react";
import {
  Stack,
  PasswordInput,
  TextInput,
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

type InvitationPublic = components["schemas"]["InvitationPublic"];

export function AcceptInvite() {
  const { t } = useTranslation("account");
  const { t: tRoles } = useTranslation("roles");

  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  const [validating, setValidating] = useState(true);
  const [inviteData, setInviteData] = useState<InvitationPublic | null>(null);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    async function validate() {
      if (!token) {
        setTokenError(t("acceptInvite.invalidMessage"));
        setValidating(false);
        return;
      }
      const { data, error } = await client.GET("/api/invitations/accept", {
        params: { query: { token } },
      });
      if (error || !data) {
        setTokenError(mapApiError(error));
      } else {
        setInviteData(data);
      }
      setValidating(false);
    }
    void validate();
  }, [token, t]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setSubmitError(t("acceptInvite.mismatchError"));
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const { error } = await client.POST("/api/invitations/accept", {
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
      <AuthLayout title={t("acceptInvite.title")}>
        <Text c="dimmed" ta="center" data-testid="invite-validating">
          Loading…
        </Text>
      </AuthLayout>
    );
  }

  if (tokenError || !inviteData) {
    return (
      <AuthLayout title={t("acceptInvite.invalidTitle")}>
        <Stack gap="md">
          <Alert
            icon={<AlertCircle size={16} />}
            color="red"
            variant="light"
            data-testid="invite-token-error"
          >
            {tokenError ?? t("acceptInvite.invalidMessage")}
          </Alert>
          <Button
            variant="subtle"
            onClick={() => window.location.assign("/")}
            data-testid="invite-go-login-btn"
          >
            {t("acceptInvite.goToLogin")}
          </Button>
        </Stack>
      </AuthLayout>
    );
  }

  if (done) {
    return (
      <AuthLayout title={t("acceptInvite.title")}>
        <Alert
          icon={<CheckCircle size={16} />}
          color="teal"
          variant="light"
          data-testid="invite-success"
        >
          {t("acceptInvite.success")}
        </Alert>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title={t("acceptInvite.title")} subtitle={t("acceptInvite.subtitle")}>
      <form onSubmit={handleSubmit}>
        <Stack gap="md">
          <TextInput
            label={t("acceptInvite.emailLabel")}
            value={inviteData.email}
            readOnly
            data-testid="invite-email-display"
          />
          <TextInput
            label={t("acceptInvite.roleLabel")}
            value={tRoles(inviteData.role, { defaultValue: inviteData.role })}
            readOnly
            data-testid="invite-role-display"
          />
          <PasswordInput
            label={t("acceptInvite.passwordLabel")}
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            required
            data-testid="invite-password-input"
          />
          <PasswordInput
            label={t("acceptInvite.confirmLabel")}
            value={confirm}
            onChange={(e) => setConfirm(e.currentTarget.value)}
            required
            data-testid="invite-confirm-input"
          />

          {submitError && (
            <Alert
              icon={<AlertCircle size={16} />}
              color="red"
              variant="light"
              data-testid="invite-submit-error"
            >
              {submitError}
            </Alert>
          )}

          <Button type="submit" loading={submitting} data-testid="invite-accept-btn">
            {t("acceptInvite.submit")}
          </Button>
        </Stack>
      </form>
    </AuthLayout>
  );
}
