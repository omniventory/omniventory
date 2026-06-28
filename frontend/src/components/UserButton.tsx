/**
 * UserButton — pinned to the bottom of the Navbar.
 *
 * Shows an Avatar (first letter of email), the email address, and a Menu
 * that contains:
 *   - Language switcher (inline EN / 中文 toggle)
 *   - Color-scheme toggle
 *   - Logout
 *
 * The email initial is derived client-side from the email prop.
 * All text via i18n (nav namespace).
 */
import {
  Avatar,
  Group,
  Text,
  Menu,
  UnstyledButton,
  Divider,
  useMantineColorScheme,
  useComputedColorScheme,
} from "@mantine/core";
import { Sun, Moon, LogOut, User } from "react-feather";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { emailToInitial } from "./emailToInitial";
import { useAuth } from "../auth/AuthContext";

interface UserButtonProps {
  email: string;
  onLogout: () => void;
}

export function UserButton({ email, onLogout }: UserButtonProps) {
  const { t } = useTranslation("nav");
  const { t: tRoles } = useTranslation("roles");
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("dark");
  // Role from AuthContext; null when no provider is present (tests — see AUTH_FALLBACK).
  const { role } = useAuth();
  const navigate = useNavigate();

  function toggleColorScheme() {
    setColorScheme(computed === "dark" ? "light" : "dark");
  }

  const initial = emailToInitial(email);

  return (
    <Menu position="top" withArrow offset={4} width={220}>
      <Menu.Target>
        <UnstyledButton
          aria-label={t("userMenu")}
          style={{
            display: "block",
            width: "100%",
            padding: "var(--mantine-spacing-xs)",
            borderRadius: "var(--mantine-radius-md)",
          }}
        >
          <Group wrap="nowrap" gap="xs">
            <Avatar color="teal" radius="xl" size="sm">
              {initial}
            </Avatar>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text size="sm" fw={500} truncate="end">
                {email}
              </Text>
              {role && (
                <Text size="xs" c="dimmed" truncate="end" data-testid="user-role-label">
                  {tRoles(role, { defaultValue: role })}
                </Text>
              )}
            </div>
          </Group>
        </UnstyledButton>
      </Menu.Target>

      <Menu.Dropdown>
        {/* Account — self-service for all roles */}
        <Menu.Item
          leftSection={<User size={14} />}
          onClick={() => navigate("/account")}
          aria-label={t("account")}
          data-testid="account-menu-item"
        >
          {t("account")}
        </Menu.Item>

        <Divider />

        {/* Language switcher row */}
        <Menu.Label>{t("language")}</Menu.Label>
        <Menu.Item
          component="div"
          closeMenuOnClick={false}
          style={{ cursor: "default" }}
        >
          <LanguageSwitcher mode="authed" />
        </Menu.Item>

        <Divider />

        {/* Color-scheme toggle */}
        <Menu.Item
          leftSection={
            computed === "dark" ? <Sun size={14} /> : <Moon size={14} />
          }
          onClick={toggleColorScheme}
          aria-label={t("toggleColorScheme")}
        >
          {t("toggleColorScheme")}
        </Menu.Item>

        <Divider />

        {/* Logout */}
        <Menu.Item
          color="red"
          leftSection={<LogOut size={14} />}
          onClick={onLogout}
          aria-label={t("logout")}
        >
          {t("logout")}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
