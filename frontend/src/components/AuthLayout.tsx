/**
 * AuthLayout — shared centered frame for Login and Setup pages.
 *
 * Renders:
 *   - Full-viewport centered container with theme-aware page background.
 *   - Brand lockup at the top (Package icon in ThemeIcon + app name), consistent
 *     with the AppShell navbar brand (NavBrand in shell/AppShell.tsx).
 *   - Page title + optional subtitle.
 *   - A Paper card housing the form content (children).
 *   - LanguageSwitcher in "pre-login" mode, top-right of the card.
 *
 * This is purely presentational — no state, no API calls.  All form logic
 * stays inside Login / Setup.
 */
import {
  Center,
  Paper,
  Stack,
  Title,
  Text,
  Group,
  ThemeIcon,
  Box,
} from "@mantine/core";
import { Package } from "react-feather";
import { useTranslation } from "react-i18next";
import { LanguageSwitcher } from "./LanguageSwitcher";

interface AuthLayoutProps {
  /** Page-level title (e.g. "Sign in"). */
  title: string;
  /** Optional dimmed subtitle below the title. */
  subtitle?: string;
  /** The form content rendered inside the Paper card. */
  children: React.ReactNode;
}

export function AuthLayout({ title, subtitle, children }: AuthLayoutProps) {
  const { t } = useTranslation("nav");

  return (
    <Center
      h="100dvh"
      p="md"
      style={{
        background:
          "light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-8))",
      }}
    >
      <Stack w="100%" maw={420} gap="lg">
        {/* Brand lockup — mirrors NavBrand in AppShell */}
        <Group justify="center" gap="xs">
          <ThemeIcon variant="light" color="teal" size="lg" radius="md">
            <Package size={20} />
          </ThemeIcon>
          <Text fw={700} size="xl">
            {t("appName")}
          </Text>
        </Group>

        {/* Page title + subtitle */}
        <Box ta="center">
          <Title order={2} mb={4}>
            {title}
          </Title>
          {subtitle && (
            <Text c="dimmed" size="sm">
              {subtitle}
            </Text>
          )}
        </Box>

        {/* Form card */}
        <Paper p="xl" withBorder shadow="sm">
          <Stack gap="md">
            {/* Language switcher — top of card, right-aligned */}
            <Group justify="flex-end">
              <LanguageSwitcher mode="pre-login" />
            </Group>

            {/* Form content */}
            {children}
          </Stack>
        </Paper>
      </Stack>
    </Center>
  );
}
