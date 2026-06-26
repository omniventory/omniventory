/**
 * TagPanel — reusable owner-metadata component for managing tags.
 *
 * Features:
 *  - Display: colour Badge chips for each attached tag.
 *  - Picker: Combobox autocomplete that searches existing tags via GET /api/tags.
 *  - Create-on-the-fly: when typed name has no exact match, offer a "Create X" option
 *    that POSTs /api/tags and then attaches the new tag.
 *  - Detach: × button on each chip calls PUT /api/tags/links with the updated set.
 *  - Replace-set semantics: PUT /api/tags/links replaces the complete tag set for the owner.
 *
 * M5 Step 9.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Stack,
  Group,
  Text,
  Title,
  Badge,
  TextInput,
  Alert,
  Loader,
  Combobox,
  useCombobox,
} from "@mantine/core";
import { AlertCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { notifySuccess } from "./notify";
import type { components } from "../api/schema";

// ── Types ─────────────────────────────────────────────────────────────────────

type TagResponse = components["schemas"]["TagResponse"];
type TagLinkResponse = components["schemas"]["TagLinkResponse"];

export type TagOwnerType = "item_definition" | "stock_instance" | "location";

export interface TagPanelProps {
  modelType: TagOwnerType;
  modelId: number;
}

// ── TagPanel ──────────────────────────────────────────────────────────────────

export function TagPanel({ modelType, modelId }: TagPanelProps) {
  const { t } = useTranslation("tags");

  // ── Tag-link list state ───────────────────────────────────────────────────
  const [tagLinks, setTagLinks] = useState<TagLinkResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ── Picker / search state ─────────────────────────────────────────────────
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<TagResponse[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);

  // ── Action busy state ─────────────────────────────────────────────────────
  const [actionError, setActionError] = useState<string | null>(null);

  // ── Combobox store ────────────────────────────────────────────────────────
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });

  // ── Data loading ──────────────────────────────────────────────────────────

  const loadTagLinks = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const { data, error } = await client.GET("/api/tags/links", {
        params: { query: { model_type: modelType, model_id: modelId } },
      });
      if (error) {
        setLoadError(mapApiError(error));
        return;
      }
      setTagLinks(data ?? []);
    } finally {
      setLoading(false);
    }
  }, [modelType, modelId]);

  useEffect(() => {
    void loadTagLinks();
  }, [loadTagLinks]);

  // ── Search effect ─────────────────────────────────────────────────────────

  useEffect(() => {
    if (!search.trim()) {
      setOptions([]);
      return;
    }

    let cancelled = false;
    setSearchBusy(true);

    void client
      .GET("/api/tags", { params: { query: { q: search.trim() } } })
      .then(({ data }) => {
        if (!cancelled) setOptions(data ?? []);
      })
      .finally(() => {
        if (!cancelled) setSearchBusy(false);
      });

    return () => {
      cancelled = true;
    };
  }, [search]);

  // ── Derived display options (exclude already-attached) ────────────────────

  // Only keep links that carry a fully-populated .tag (guards against stale or
  // mis-routed test mocks returning non-TagLinkResponse data).
  const validTagLinks = tagLinks.filter((l) => l.tag != null);
  const currentTagIds = new Set(validTagLinks.map((l) => l.tag_id));
  const filteredOptions = options.filter((o) => !currentTagIds.has(o.id));
  const alreadyAttachedName = validTagLinks.some(
    (l) => l.tag.name.toLowerCase() === search.trim().toLowerCase(),
  );
  const exactMatchInOptions = filteredOptions.find(
    (o) => o.name.toLowerCase() === search.trim().toLowerCase(),
  );
  const showCreate =
    search.trim().length > 0 && !exactMatchInOptions && !alreadyAttachedName;

  // ── Attach / detach helpers ───────────────────────────────────────────────

  async function applyTagSet(newTagIds: number[]) {
    setActionError(null);
    const { error } = await client.PUT("/api/tags/links", {
      body: { model_type: modelType, model_id: modelId, tag_ids: newTagIds },
    });
    if (error) {
      setActionError(mapApiError(error));
      return false;
    }
    return true;
  }

  async function attachTag(tagId: number, successKey: "attached" | "created") {
    const newIds = [...Array.from(currentTagIds), tagId];
    const ok = await applyTagSet(newIds);
    if (ok) {
      notifySuccess(t(`success.${successKey}`));
      await loadTagLinks();
    }
  }

  async function detachTag(tagId: number) {
    const newIds = Array.from(currentTagIds).filter((id) => id !== tagId);
    const ok = await applyTagSet(newIds);
    if (ok) {
      notifySuccess(t("success.detached"));
      await loadTagLinks();
    }
  }

  // ── Create-on-the-fly ─────────────────────────────────────────────────────

  async function createAndAttach(name: string) {
    setActionError(null);
    const { data: newTag, error } = await client.POST("/api/tags", {
      body: { name },
    });
    if (error || !newTag) {
      setActionError(mapApiError(error ?? {}));
      return;
    }
    await attachTag(newTag.id, "created");
  }

  // ── Option submit handler ─────────────────────────────────────────────────

  function handleOptionSubmit(val: string) {
    combobox.closeDropdown();
    setSearch("");
    setOptions([]);

    if (val === "__create__") {
      void createAndAttach(search.trim());
    } else {
      void attachTag(Number(val), "attached");
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Stack gap="sm" data-testid="tag-panel">
      <Title order={5}>{t("sectionTitle")}</Title>

      {/* Action error */}
      {actionError && (
        <Alert
          icon={<AlertCircle size={16} />}
          color="red"
          variant="light"
          data-testid="tag-action-error"
        >
          {actionError}
        </Alert>
      )}

      {/* Loading / error / chip list */}
      {loading ? (
        <Loader size="sm" data-testid="tag-loading" />
      ) : loadError ? (
        <Alert
          icon={<AlertCircle size={16} />}
          color="red"
          variant="light"
          data-testid="tag-load-error"
        >
          {loadError}
        </Alert>
      ) : (
        <Group gap="xs" wrap="wrap" data-testid="tag-chip-group">
          {validTagLinks.length === 0 && (
            <Text size="sm" c="dimmed" data-testid="tag-empty">
              {t("emptyState")}
            </Text>
          )}
          {validTagLinks.map((link) => (
            <Badge
              key={link.tag_id}
              color={link.tag.color ?? "blue"}
              variant="light"
              size="sm"
              rightSection={
                <span
                  style={{ cursor: "pointer", lineHeight: 1 }}
                  onClick={() => void detachTag(link.tag_id)}
                  data-testid={`tag-detach-${link.tag_id}`}
                  aria-label={t("removeAria", { name: link.tag.name })}
                >
                  ×
                </span>
              }
              data-testid={`tag-chip-${link.tag_id}`}
            >
              {link.tag.name}
            </Badge>
          ))}
        </Group>
      )}

      {/* Picker / creator */}
      <Combobox store={combobox} onOptionSubmit={handleOptionSubmit}>
        <Combobox.Target>
          <TextInput
            placeholder={t("addTagPlaceholder")}
            value={search}
            onChange={(e) => {
              const v = e.currentTarget.value;
              setSearch(v);
              if (v.trim()) {
                combobox.openDropdown();
              } else {
                combobox.closeDropdown();
                setOptions([]);
              }
            }}
            onFocus={() => {
              if (search.trim()) combobox.openDropdown();
            }}
            size="xs"
            rightSection={searchBusy ? <Loader size={12} /> : undefined}
            data-testid="tag-search-input"
          />
        </Combobox.Target>

        <Combobox.Dropdown>
          <Combobox.Options>
            {filteredOptions.map((tag) => (
              <Combobox.Option
                key={tag.id}
                value={String(tag.id)}
                data-testid={`tag-option-${tag.id}`}
              >
                <Badge
                  color={tag.color ?? "blue"}
                  variant="light"
                  size="sm"
                >
                  {tag.name}
                </Badge>
              </Combobox.Option>
            ))}
            {showCreate && (
              <Combobox.Option
                value="__create__"
                data-testid="tag-create-option"
              >
                {t("createTagLabel", { name: search.trim() })}
              </Combobox.Option>
            )}
          </Combobox.Options>
        </Combobox.Dropdown>
      </Combobox>
    </Stack>
  );
}
