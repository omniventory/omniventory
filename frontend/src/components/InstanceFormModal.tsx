/**
 * InstanceFormModal — shared modal for creating/editing a stock instance.
 *
 * Enforces the client-side serial ⇒ quantity = 1 rule (M1 §7.3):
 *   - When serial is non-empty, quantity is forced to "1" and disabled.
 *   - The server's 422 is surfaced via the `error` prop.
 *
 * Used by both the Items (definition detail) page and the InstanceDetail page.
 */
import {
  Modal,
  Stack,
  Select,
  TextInput,
  Textarea,
  NumberInput,
  Button,
  Group,
  Alert,
} from "@mantine/core";
import { AlertCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import type { components } from "../api/schema";

// ── Types ─────────────────────────────────────────────────────────────────────

type DefinitionResponse = components["schemas"]["DefinitionResponse"];
type LocationResponse = components["schemas"]["LocationResponse"];

export interface InstanceFormState {
  definition_id: string;
  location_id: string;
  quantity: string;
  serial: string;
  model_number: string;
  manufacturer: string;
  warranty_expires: string;
  warranty_details: string;
  purchase_price: string;
  purchase_date: string;
  purchase_source: string;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface InstanceFormModalProps {
  opened: boolean;
  title: string;
  form: InstanceFormState;
  setForm: React.Dispatch<React.SetStateAction<InstanceFormState>>;
  onSubmit: () => void;
  onClose: () => void;
  busy: boolean;
  error: string | null;
  definitions: DefinitionResponse[];
  locations: LocationResponse[];
  /** When true, definition picker is locked (pre-filled from context). */
  lockDefinition?: boolean;
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InstanceFormModal({
  opened,
  title,
  form,
  setForm,
  onSubmit,
  onClose,
  busy,
  error,
  definitions,
  locations,
  lockDefinition,
}: InstanceFormModalProps) {
  const { t } = useTranslation("instances");

  // Client-side serial ⇒ quantity = 1 rule (§7.3):
  // When serial is non-empty, force quantity to "1" and disable the field.
  const serialPresent = form.serial.trim().length > 0;

  function handleSerialChange(value: string) {
    setForm((f) => ({
      ...f,
      serial: value,
      // auto-set quantity to 1 when a serial is entered
      quantity: value.trim().length > 0 ? "1" : f.quantity,
    }));
  }

  const defOptions = definitions.map((d) => ({
    value: String(d.id),
    label: d.name,
  }));
  const locationOptions = [
    { value: "", label: t("form.noneOption") },
    ...locations.map((l) => {
      const assetSuffix = l.container_asset_label ? ` — ${l.container_asset_label}` : "";
      return { value: String(l.id), label: `${l.name}${assetSuffix}` };
    }),
  ];

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="md">
      <Stack gap="sm">
        {error && (
          <Alert
            icon={<AlertCircle size={16} />}
            color="red"
            variant="light"
            data-testid="instance-error-alert"
          >
            {error}
          </Alert>
        )}
        <Select
          label={t("form.definitionLabel")}
          required
          data={defOptions}
          value={form.definition_id}
          onChange={(v) => setForm((f) => ({ ...f, definition_id: v ?? "" }))}
          disabled={lockDefinition}
          data-testid="inst-definition-select"
        />
        <Select
          label={t("form.locationLabel")}
          data={locationOptions}
          value={form.location_id}
          onChange={(v) => setForm((f) => ({ ...f, location_id: v ?? "" }))}
          clearable
          data-testid="inst-location-select"
        />
        <TextInput
          label={t("form.serialLabel")}
          value={form.serial}
          onChange={(e) => handleSerialChange(e.currentTarget.value)}
          data-testid="inst-serial-input"
        />
        <NumberInput
          label={t("form.quantityLabel")}
          value={form.quantity}
          onChange={(v) => setForm((f) => ({ ...f, quantity: String(v) }))}
          min={0}
          allowDecimal
          disabled={serialPresent}
          description={
            serialPresent ? t("form.quantitySerialHint") : undefined
          }
          data-testid="inst-quantity-input"
        />
        <TextInput
          label={t("form.modelNumberLabel")}
          value={form.model_number}
          onChange={(e) =>
            setForm((f) => ({ ...f, model_number: e.currentTarget.value }))
          }
        />
        <TextInput
          label={t("form.manufacturerLabel")}
          value={form.manufacturer}
          onChange={(e) =>
            setForm((f) => ({ ...f, manufacturer: e.currentTarget.value }))
          }
          data-testid="inst-manufacturer-input"
        />
        <TextInput
          label={t("form.warrantyExpiresLabel")}
          placeholder={t("form.warrantyExpiresPlaceholder")}
          value={form.warranty_expires}
          onChange={(e) =>
            setForm((f) => ({ ...f, warranty_expires: e.currentTarget.value }))
          }
        />
        <Textarea
          label={t("form.warrantyDetailsLabel")}
          value={form.warranty_details}
          onChange={(e) =>
            setForm((f) => ({ ...f, warranty_details: e.currentTarget.value }))
          }
          autosize
          minRows={2}
        />
        <TextInput
          label={t("form.purchasePriceLabel")}
          placeholder={t("form.purchasePricePlaceholder")}
          value={form.purchase_price}
          onChange={(e) =>
            setForm((f) => ({ ...f, purchase_price: e.currentTarget.value }))
          }
        />
        <TextInput
          label={t("form.purchaseDateLabel")}
          placeholder={t("form.purchaseDatePlaceholder")}
          value={form.purchase_date}
          onChange={(e) =>
            setForm((f) => ({ ...f, purchase_date: e.currentTarget.value }))
          }
        />
        <TextInput
          label={t("form.purchaseSourceLabel")}
          value={form.purchase_source}
          onChange={(e) =>
            setForm((f) => ({ ...f, purchase_source: e.currentTarget.value }))
          }
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={busy}>
            {t("common:actions.cancel", "Cancel")}
          </Button>
          <Button
            onClick={onSubmit}
            loading={busy}
            disabled={!form.definition_id}
            data-testid="inst-submit-btn"
          >
            {t("common:actions.save", "Save")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
