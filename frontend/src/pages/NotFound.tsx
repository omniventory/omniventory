/**
 * NotFound — 404 page shown when the user navigates to an unknown authed route.
 * Follows the Mantine "Error pages" pattern: large status code, title, message,
 * and a "back to home" button.
 */
import { Center, Stack, Title, Text, Button } from "@mantine/core";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

export function NotFound() {
  const { t } = useTranslation();
  return (
    <Center h="calc(100vh - 120px)">
      <Stack align="center" gap="lg" maw={400}>
        <Title
          order={1}
          style={{
            fontSize: "6rem",
            fontWeight: 900,
            lineHeight: 1,
            color: "var(--mantine-color-teal-6)",
          }}
          aria-label={t("notFound.code")}
        >
          {t("notFound.code")}
        </Title>
        <Title order={2} ta="center">
          {t("notFound.title")}
        </Title>
        <Text c="dimmed" size="md" ta="center">
          {t("notFound.message")}
        </Text>
        <Button component={Link} to="/" size="md" variant="light" color="teal">
          {t("notFound.backHome")}
        </Button>
      </Stack>
    </Center>
  );
}
