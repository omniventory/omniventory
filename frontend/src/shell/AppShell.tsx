/**
 * Responsive application shell.
 *
 * Desktop: persistent sidebar (navbar) + header.
 * Mobile: header with burger icon → opens a Drawer for navigation.
 *
 * This is the ONE shell definition for the whole app.  Every later page
 * mounts inside <AppShell> via the {children} slot.
 *
 * Color-scheme toggle and logout action live in the header.
 */
import {
  AppShell as MantineAppShell,
  Burger,
  Drawer,
  Group,
  ActionIcon,
  Text,
  Stack,
  NavLink,
  useMantineColorScheme,
  useComputedColorScheme,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Sun, Moon, LogOut, Package } from "react-feather";
import { client } from "../api/client";

interface AppShellProps {
  children: React.ReactNode;
  onLogout: () => void;
}

/** Sidebar / nav content (placeholder nav item for M0). */
function NavContent() {
  return (
    <Stack gap={4} p="xs">
      <NavLink
        label="Inventory"
        leftSection={<Package size={16} />}
        active
        variant="filled"
      />
    </Stack>
  );
}

/** Header content: app name, dark-mode toggle, logout. */
function HeaderContent({
  burgerOpened,
  onBurgerToggle,
  onLogout,
}: {
  burgerOpened: boolean;
  onBurgerToggle: () => void;
  onLogout: () => void;
}) {
  const { setColorScheme } = useMantineColorScheme();
  const computed = useComputedColorScheme("dark");

  function toggleColorScheme() {
    setColorScheme(computed === "dark" ? "light" : "dark");
  }

  return (
    <Group h="100%" px="md" justify="space-between">
      {/* Left: burger (mobile only) + app name */}
      <Group>
        <Burger
          opened={burgerOpened}
          onClick={onBurgerToggle}
          hiddenFrom="sm"
          size="sm"
          aria-label="Toggle navigation"
        />
        <Text fw={700} size="lg">
          Omniventory
        </Text>
      </Group>

      {/* Right: color-scheme toggle + logout */}
      <Group gap="xs">
        <ActionIcon
          variant="default"
          size="lg"
          onClick={toggleColorScheme}
          aria-label="Toggle color scheme"
        >
          {computed === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </ActionIcon>
        <ActionIcon
          variant="default"
          size="lg"
          onClick={onLogout}
          aria-label="Logout"
        >
          <LogOut size={16} />
        </ActionIcon>
      </Group>
    </Group>
  );
}

export function AppShell({ children, onLogout }: AppShellProps) {
  const [drawerOpened, { toggle: toggleDrawer, close: closeDrawer }] =
    useDisclosure(false);

  async function handleLogout() {
    await client.POST("/api/auth/logout");
    onLogout();
  }

  return (
    <>
      {/* Mobile drawer (visible on sm and below) */}
      <Drawer
        opened={drawerOpened}
        onClose={closeDrawer}
        size="xs"
        padding="md"
        title="Navigation"
        hiddenFrom="sm"
        zIndex={1000}
      >
        <NavContent />
      </Drawer>

      {/* Mantine AppShell: navbar hidden on mobile (handled by Drawer instead) */}
      <MantineAppShell
        header={{ height: 56 }}
        navbar={{
          width: 220,
          breakpoint: "sm",
          collapsed: { mobile: true },
        }}
        padding="md"
      >
        <MantineAppShell.Header>
          <HeaderContent
            burgerOpened={drawerOpened}
            onBurgerToggle={toggleDrawer}
            onLogout={handleLogout}
          />
        </MantineAppShell.Header>

        <MantineAppShell.Navbar>
          <NavContent />
        </MantineAppShell.Navbar>

        <MantineAppShell.Main>{children}</MantineAppShell.Main>
      </MantineAppShell>
    </>
  );
}
