/**
 * Account — self-service page available to all authenticated roles (viewer / member / admin).
 * Reachable via the user menu ("My Account" item).
 *
 * Sections (all self-service, no permission gate required):
 *  1. Change password — current + new + confirm → POST /api/auth/change-password.
 *     Surfaces auth.password_incorrect via mapApiError.
 *     On success: clear form, show success message (other sessions are revoked).
 *  2. Your reminders (per-user) — MOVED from Configuration (which is admin-only).
 *     reminder_best_before_lead_days + reminder_warranty_lead_days loaded from
 *     GET /api/auth/me; saved via PATCH /api/auth/me.
 *     Empty string = null (inherit global default); value = integer override.
 *
 * Step 12 will later add notification preference toggles (in-app / email digest)
 * to this page.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Button,
  Divider,
  Group,
  NumberInput,
  Paper,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { AlertCircle, CheckCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { notifySuccess } from "../components/notify";
import { PageShell } from "../components/PageShell";
import { LoadingState } from "../components/LoadingState";
import { ErrorState } from "../components/ErrorState";
import type { components } from "../api/schema";

type UserResponse = components["schemas"]["UserResponse"];
type SettingsResponse = components["schemas"]["SettingsResponse"];

export function Account() {
  const { t } = useTranslation("account");

  // ── Loading state ──
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [me, setMe] = useState<UserResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);

  // ── Change-password form ──
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState(false);

  // ── Per-user reminders form (moved from Configuration) ──
  const [userBbLeadDays, setUserBbLeadDays] = useState<string>("");
  const [userWLeadDays, setUserWLeadDays] = useState<string>("");
  const [userRemindersBusy, setUserRemindersBusy] = useState(false);
  const [userRemindersError, setUserRemindersError] = useState<string | null>(null);

  // ── Load data ─────────────────────────────────────────────────────────────

  const loadAll = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // Load both in parallel; settings failure is non-fatal (only affects
      // the description's globalValue placeholder).
      const [meRes, settingsRes] = await Promise.all([
        client.GET("/api/auth/me"),
        client.GET("/api/settings"),
      ]);

      if (meRes.error || !meRes.data) {
        setLoadError(t("loadError"));
        return;
      }

      const u = meRes.data.user;
      setMe(u);
      setUserBbLeadDays(
        u.reminder_best_before_lead_days != null
          ? String(u.reminder_best_before_lead_days)
          : "",
      );
      setUserWLeadDays(
        u.reminder_warranty_lead_days != null
          ? String(u.reminder_warranty_lead_days)
          : "",
      );

      if (!settingsRes.error && settingsRes.data) {
        setSettings(settingsRes.data);
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // ── Save handlers ─────────────────────────────────────────────────────────

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setPwError(t("changePassword.mismatchError"));
      return;
    }
    setPwBusy(true);
    setPwError(null);
    setPwSuccess(false);
    try {
      const { error } = await client.POST("/api/auth/change-password", {
        body: { current_password: currentPassword, new_password: newPassword },
      });
      if (error) {
        setPwError(mapApiError(error));
        return;
      }
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPwSuccess(true);
    } finally {
      setPwBusy(false);
    }
  }

  async function handleSaveUserReminders() {
    setUserRemindersBusy(true);
    setUserRemindersError(null);
    try {
      // Empty string = send null (inherit global); value = integer override
      const bbVal = userBbLeadDays.trim() === "" ? null : Number(userBbLeadDays);
      const wVal = userWLeadDays.trim() === "" ? null : Number(userWLeadDays);

      const { error } = await client.PATCH("/api/auth/me", {
        body: {
          reminder_best_before_lead_days: bbVal,
          reminder_warranty_lead_days: wVal,
        },
      });
      if (error) {
        setUserRemindersError(mapApiError(error));
        return;
      }
      notifySuccess(t("yourReminders.saved"));
      await loadAll();
    } finally {
      setUserRemindersBusy(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) return <LoadingState />;
  if (loadError || !me) return <ErrorState message={loadError ?? t("loadError")} />;

  return (
    <PageShell title={t("page.title")} subtitle={t("page.subtitle")}>
      <Stack gap="xl">

        {/* ── Change password ───────────────────────────────────────────── */}
        <Paper withBorder p="md">
          <Stack gap="sm">
            <Title order={4}>{t("section.changePassword")}</Title>
            <Divider />
            <Text size="sm" c="dimmed">
              {t("changePassword.otherSessionsNote")}
            </Text>

            {pwSuccess && (
              <Alert
                icon={<CheckCircle size={16} />}
                color="teal"
                variant="light"
                data-testid="pw-success"
              >
                {t("changePassword.success")}
              </Alert>
            )}

            {pwError && (
              <Alert
                icon={<AlertCircle size={16} />}
                color="red"
                variant="light"
                data-testid="pw-error"
              >
                {pwError}
              </Alert>
            )}

            <form onSubmit={handleChangePassword}>
              <Stack gap="sm">
                <PasswordInput
                  label={t("changePassword.currentLabel")}
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.currentTarget.value)}
                  required
                  data-testid="current-password-input"
                />
                <PasswordInput
                  label={t("changePassword.newLabel")}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.currentTarget.value)}
                  required
                  data-testid="new-password-input"
                />
                <PasswordInput
                  label={t("changePassword.confirmLabel")}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.currentTarget.value)}
                  required
                  data-testid="confirm-password-input"
                />
                <Group justify="flex-end">
                  <Button
                    type="submit"
                    loading={pwBusy}
                    data-testid="change-pw-btn"
                  >
                    {t("changePassword.submit")}
                  </Button>
                </Group>
              </Stack>
            </form>
          </Stack>
        </Paper>

        {/* ── Your reminders (per-user) — moved from Configuration ─────── */}
        <Paper withBorder p="md">
          <Stack gap="sm">
            <Title order={4}>{t("section.yourReminders")}</Title>
            <Divider />
            <Text size="sm" c="dimmed">
              {t("yourReminders.description")}
            </Text>

            {userRemindersError && (
              <Alert
                icon={<AlertCircle size={16} />}
                color="red"
                variant="light"
                data-testid="user-reminders-error"
              >
                {userRemindersError}
              </Alert>
            )}

            <NumberInput
              label={t("yourReminders.bestBeforeLeadDaysLabel")}
              description={t("yourReminders.bestBeforeLeadDaysDescription", {
                globalValue: settings?.reminders.best_before_lead_days ?? "—",
              })}
              value={userBbLeadDays === "" ? "" : Number(userBbLeadDays)}
              onChange={(v) =>
                setUserBbLeadDays(v === "" ? "" : String(Math.round(Number(v))))
              }
              min={0}
              allowDecimal={false}
              suffix=" days"
              data-testid="user-bb-lead-input"
            />
            <NumberInput
              label={t("yourReminders.warrantyLeadDaysLabel")}
              description={t("yourReminders.warrantyLeadDaysDescription", {
                globalValue: settings?.reminders.warranty_lead_days ?? "—",
              })}
              value={userWLeadDays === "" ? "" : Number(userWLeadDays)}
              onChange={(v) =>
                setUserWLeadDays(v === "" ? "" : String(Math.round(Number(v))))
              }
              min={0}
              allowDecimal={false}
              suffix=" days"
              data-testid="user-warranty-lead-input"
            />

            <Group justify="flex-end">
              <Button
                onClick={() => void handleSaveUserReminders()}
                loading={userRemindersBusy}
                data-testid="save-user-reminders-btn"
              >
                {t("yourReminders.save")}
              </Button>
            </Group>
          </Stack>
        </Paper>

      </Stack>
    </PageShell>
  );
}
