/**
 * CustomFieldsEditor — controlled key/value editor for the `custom_fields` map.
 *
 * Renders an ordered list of rows. Each row has:
 *   - a key TextInput
 *   - a type Select (string / number / boolean / null)
 *   - a value input that adapts to the selected type
 *   - a remove ActionIcon
 *
 * An "Add field" button appends a new empty row.
 *
 * Serialization rules (M5 §7.2):
 *   - Rows with an empty key are skipped.
 *   - If no valid rows remain after filtering, onChange is called with null.
 *   - Number rows: strValue is parsed via Number(); empty strValue → 0.
 *   - Boolean rows: use boolValue (true/false).
 *   - Null rows: always produce null regardless of inputs.
 *   - String rows: strValue as-is.
 *
 * Resync logic: the component keeps internal row state to allow natural
 * key-strokes.  When the `value` prop changes externally (e.g., modal
 * opens with edit data), the component detects the change via a JSON
 * comparison ref and resets its rows.  This avoids an update loop because
 * the ref is advanced *before* calling onChange, so the round-trip value
 * coming back from the parent is recognised as "already applied" and skipped.
 */
import { useState, useEffect, useRef } from "react";
import {
  Stack,
  Group,
  Text,
  Button,
  TextInput,
  NumberInput,
  Select,
  ActionIcon,
  Switch,
} from "@mantine/core";
import { Trash2, Plus } from "react-feather";
import { useTranslation } from "react-i18next";

// ── Types ─────────────────────────────────────────────────────────────────────

type CFValue = string | number | boolean | null;
type CFType = "string" | "number" | "boolean" | "null";

interface CFRow {
  key: string;
  type: CFType;
  /** Used for string and number types. */
  strValue: string;
  /** Used for boolean type. */
  boolValue: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function valueToRows(
  value: Record<string, CFValue> | null | undefined,
): CFRow[] {
  if (!value) return [];
  return Object.entries(value).map(([key, val]) => {
    if (val === null)
      return { key, type: "null" as CFType, strValue: "", boolValue: false };
    if (typeof val === "boolean")
      return {
        key,
        type: "boolean" as CFType,
        strValue: "",
        boolValue: val,
      };
    if (typeof val === "number")
      return {
        key,
        type: "number" as CFType,
        strValue: String(val),
        boolValue: false,
      };
    return {
      key,
      type: "string" as CFType,
      strValue: String(val),
      boolValue: false,
    };
  });
}

function rowsToValue(rows: CFRow[]): Record<string, CFValue> | null {
  const valid = rows.filter((r) => r.key.trim() !== "");
  if (valid.length === 0) return null;
  const result: Record<string, CFValue> = {};
  for (const row of valid) {
    const k = row.key.trim();
    if (row.type === "null") result[k] = null;
    else if (row.type === "boolean") result[k] = row.boolValue;
    else if (row.type === "number")
      result[k] = row.strValue === "" ? 0 : Number(row.strValue);
    else result[k] = row.strValue;
  }
  return Object.keys(result).length === 0 ? null : result;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface CustomFieldsEditorProps {
  value: Record<string, CFValue> | null | undefined;
  onChange: (v: Record<string, CFValue> | null) => void;
  disabled?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function CustomFieldsEditor({
  value,
  onChange,
  disabled,
}: CustomFieldsEditorProps) {
  const { t } = useTranslation("customFields");

  const [rows, setRows] = useState<CFRow[]>(() => valueToRows(value));

  // Track the JSON of the last value we sent to onChange.  When the parent
  // feeds it back through the value prop, we recognise it and skip resync.
  const prevValueJson = useRef(JSON.stringify(value ?? null));

  useEffect(() => {
    const incoming = JSON.stringify(value ?? null);
    if (incoming !== prevValueJson.current) {
      prevValueJson.current = incoming;
      setRows(valueToRows(value));
    }
  }, [value]);

  /** Serialise rows, advance the ref, and call parent onChange. */
  function emit(newRows: CFRow[]) {
    const newValue = rowsToValue(newRows);
    prevValueJson.current = JSON.stringify(newValue);
    onChange(newValue);
  }

  function addRow() {
    const newRows: CFRow[] = [
      ...rows,
      { key: "", type: "string", strValue: "", boolValue: false },
    ];
    setRows(newRows);
    emit(newRows);
  }

  function removeRow(index: number) {
    const newRows = rows.filter((_, i) => i !== index);
    setRows(newRows);
    emit(newRows);
  }

  function updateKey(index: number, key: string) {
    const newRows = rows.map((r, i) => (i === index ? { ...r, key } : r));
    setRows(newRows);
    emit(newRows);
  }

  function updateType(index: number, type: CFType) {
    // Reset value fields when type changes.
    const newRows = rows.map((r, i) =>
      i === index ? { ...r, type, strValue: "", boolValue: false } : r,
    );
    setRows(newRows);
    emit(newRows);
  }

  function updateStrValue(index: number, strValue: string) {
    const newRows = rows.map((r, i) => (i === index ? { ...r, strValue } : r));
    setRows(newRows);
    emit(newRows);
  }

  function updateBoolValue(index: number, boolValue: boolean) {
    const newRows = rows.map((r, i) =>
      i === index ? { ...r, boolValue } : r,
    );
    setRows(newRows);
    emit(newRows);
  }

  const typeOptions = [
    { value: "string", label: t("types.string") },
    { value: "number", label: t("types.number") },
    { value: "boolean", label: t("types.boolean") },
    { value: "null", label: t("types.null") },
  ];

  return (
    <Stack gap="xs" data-testid="custom-fields-editor">
      <Text size="sm" fw={500}>
        {t("sectionTitle")}
      </Text>

      {rows.length === 0 && (
        <Text size="sm" c="dimmed" data-testid="cf-empty-state">
          {t("emptyState")}
        </Text>
      )}

      {rows.map((row, index) => (
        <Group key={index} gap="xs" align="flex-end" data-testid={`cf-row-${index}`}>
          {/* Key input */}
          <TextInput
            label={index === 0 ? t("keyLabel") : undefined}
            value={row.key}
            onChange={(e) => updateKey(index, e.currentTarget.value)}
            disabled={disabled}
            placeholder="key"
            style={{ flex: 1 }}
            data-testid={`cf-key-${index}`}
          />

          {/* Type selector */}
          <Select
            label={index === 0 ? t("typeLabel") : undefined}
            data={typeOptions}
            value={row.type}
            onChange={(v) => updateType(index, (v ?? "string") as CFType)}
            disabled={disabled}
            style={{ width: 110 }}
            allowDeselect={false}
            data-testid={`cf-type-${index}`}
          />

          {/* Value input — adapts to type */}
          {row.type === "string" && (
            <TextInput
              label={index === 0 ? t("valueLabel") : undefined}
              value={row.strValue}
              onChange={(e) => updateStrValue(index, e.currentTarget.value)}
              disabled={disabled}
              style={{ flex: 1 }}
              data-testid={`cf-value-${index}`}
            />
          )}
          {row.type === "number" && (
            <NumberInput
              label={index === 0 ? t("valueLabel") : undefined}
              value={row.strValue === "" ? "" : Number(row.strValue)}
              onChange={(v) =>
                updateStrValue(index, v === "" ? "" : String(v))
              }
              disabled={disabled}
              style={{ flex: 1 }}
              data-testid={`cf-value-${index}`}
            />
          )}
          {row.type === "boolean" && (
            <Stack gap={2} style={{ flex: 1 }}>
              {index === 0 && (
                <Text size="sm" fw={500}>
                  {t("valueLabel")}
                </Text>
              )}
              <Switch
                checked={row.boolValue}
                onChange={(e) =>
                  updateBoolValue(index, e.currentTarget.checked)
                }
                disabled={disabled}
                data-testid={`cf-value-${index}`}
              />
            </Stack>
          )}
          {row.type === "null" && (
            <TextInput
              label={index === 0 ? t("valueLabel") : undefined}
              value=""
              disabled
              placeholder="null"
              style={{ flex: 1 }}
              data-testid={`cf-value-${index}`}
            />
          )}

          {/* Remove button */}
          <ActionIcon
            variant="subtle"
            color="red"
            onClick={() => removeRow(index)}
            disabled={disabled}
            aria-label={t("removeField")}
            data-testid={`cf-remove-${index}`}
          >
            <Trash2 size={14} />
          </ActionIcon>
        </Group>
      ))}

      <Button
        variant="subtle"
        size="xs"
        leftSection={<Plus size={12} />}
        onClick={addRow}
        disabled={disabled}
        data-testid="cf-add-btn"
        style={{ alignSelf: "flex-start" }}
      >
        {t("addField")}
      </Button>
    </Stack>
  );
}
