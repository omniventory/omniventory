/**
 * MaintenancePanel — maintenance schedules section for the InstanceDetail page.
 *
 * Renders the list of maintenance schedules for one stock instance.
 * Each row shows: name, recurrence, next_due_date, status chip, last_completed_date.
 * Status chip is rendered from the server-computed `status` field (overdue/due_soon/ok);
 * the client does NOT recompute status — the server already resolved it against
 * `effective_lead_days`.
 *
 * Actions (EDIT-gated): add, edit, pause/resume, delete, mark-done.
 * Mark-done posts to /complete and triggers a refetch so the advanced next_due_date
 * and updated status chip are visible immediately.
 *
 * M7 Step 7.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Stack,
  Group,
  Text,
  Title,
  Button,
  Badge,
  Modal,
  Alert,
  Table,
  TextInput,
  NumberInput,
  Select,
  Textarea,
  Loader,
  ActionIcon,
} from "@mantine/core";
import { Plus, Edit2, Trash2, AlertCircle, CheckCircle, PauseCircle, PlayCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { notifySuccess } from "./notify";
import { useAuth } from "../auth/AuthContext";
import { formatDate } from "../i18n/format";
import type { components } from "../api/schema";

// ── Types ─────────────────────────────────────────────────────────────────────

type MaintenanceScheduleResponse = components["schemas"]["MaintenanceScheduleResponse"];

// ── Status chip ───────────────────────────────────────────────────────────────

function statusColor(status: string): string {
  if (status === "overdue") return "red";
  if (status === "due_soon") return "yellow";
  return "green";
}

// ── Schedule form state ───────────────────────────────────────────────────────

interface ScheduleFormState {
  name: string;
  interval_count: string;
  interval_unit: string;
  next_due_date: string;
  lead_days: string;
  notes: string;
}

const emptyScheduleForm: ScheduleFormState = {
  name: "",
  interval_count: "1",
  interval_unit: "month",
  next_due_date: "",
  lead_days: "",
  notes: "",
};

function scheduleToForm(s: MaintenanceScheduleResponse): ScheduleFormState {
  return {
    name: s.name,
    interval_count: String(s.interval_count),
    interval_unit: s.interval_unit,
    next_due_date: s.next_due_date,
    lead_days: s.lead_days != null ? String(s.lead_days) : "",
    notes: s.notes ?? "",
  };
}

// ── Mark-done form state ──────────────────────────────────────────────────────

interface MarkDoneFormState {
  completed_on: string;
  note: string;
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface MaintenancePanelProps {
  instanceId: number;
}

// ── MaintenancePanel ──────────────────────────────────────────────────────────

export function MaintenancePanel({ instanceId }: MaintenancePanelProps) {
  const { t } = useTranslation("maintenance");
  const { can } = useAuth();
  const canEdit = can("EDIT");

  // ── Schedule list state ───────────────────────────────────────────────────
  const [schedules, setSchedules] = useState<MaintenanceScheduleResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ── Add modal ─────────────────────────────────────────────────────────────
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState<ScheduleFormState>(emptyScheduleForm);
  const [addBusy, setAddBusy] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // ── Edit modal ────────────────────────────────────────────────────────────
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<ScheduleFormState>(emptyScheduleForm);
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ── Mark-done modal ───────────────────────────────────────────────────────
  const [markDoneOpen, setMarkDoneOpen] = useState(false);
  const [markDoneId, setMarkDoneId] = useState<number | null>(null);
  const [markDoneForm, setMarkDoneForm] = useState<MarkDoneFormState>({ completed_on: "", note: "" });
  const [markDoneBusy, setMarkDoneBusy] = useState(false);
  const [markDoneError, setMarkDoneError] = useState<string | null>(null);

  // ── Delete confirm modal ──────────────────────────────────────────────────
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteName, setDeleteName] = useState("");
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // ── Pause/resume busy ─────────────────────────────────────────────────────
  const [pauseBusyId, setPauseBusyId] = useState<number | null>(null);

  // ── Load schedules ────────────────────────────────────────────────────────

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await client.GET("/api/instances/{instance_id}/maintenance-schedules", {
        params: { path: { instance_id: instanceId } },
      });
      if (res.error || !res.data) {
        setLoadError(t("errors.loadFailed"));
        return;
      }
      setSchedules(res.data);
    } finally {
      setLoading(false);
    }
  }, [instanceId, t]);

  useEffect(() => {
    void loadSchedules();
  }, [loadSchedules]);

  // ── Interval unit options ─────────────────────────────────────────────────

  const intervalUnitOptions = [
    { value: "day", label: t("intervalUnits.day") },
    { value: "week", label: t("intervalUnits.week") },
    { value: "month", label: t("intervalUnits.month") },
    { value: "year", label: t("intervalUnits.year") },
  ];

  // ── Recurrence label ──────────────────────────────────────────────────────

  function recurrenceLabel(schedule: MaintenanceScheduleResponse): string {
    const count = schedule.interval_count;
    const unit = schedule.interval_unit as "day" | "week" | "month" | "year";
    return t(`recurrence.${unit}`, { count });
  }

  // ── Add handler ───────────────────────────────────────────────────────────

  function openAdd() {
    setAddForm(emptyScheduleForm);
    setAddError(null);
    setAddOpen(true);
  }

  async function handleAdd() {
    setAddBusy(true);
    setAddError(null);
    try {
      const { error } = await client.POST("/api/maintenance-schedules", {
        body: {
          instance_id: instanceId,
          name: addForm.name.trim(),
          interval_unit: addForm.interval_unit,
          interval_count: Number(addForm.interval_count) || 1,
          next_due_date: addForm.next_due_date,
          lead_days: addForm.lead_days.trim() ? Number(addForm.lead_days) : null,
          notes: addForm.notes.trim() || null,
        },
      });
      if (error) {
        setAddError(mapApiError(error));
        return;
      }
      setAddOpen(false);
      notifySuccess(t("success.created"));
      await loadSchedules();
    } finally {
      setAddBusy(false);
    }
  }

  // ── Edit handler ──────────────────────────────────────────────────────────

  function openEdit(schedule: MaintenanceScheduleResponse) {
    setEditId(schedule.id);
    setEditForm(scheduleToForm(schedule));
    setEditError(null);
    setEditOpen(true);
  }

  async function handleEdit() {
    if (editId == null) return;
    setEditBusy(true);
    setEditError(null);
    try {
      const { error } = await client.PATCH("/api/maintenance-schedules/{schedule_id}", {
        params: { path: { schedule_id: editId } },
        body: {
          // Send only the editable fields.
          // is_active is intentionally omitted — it is managed by the separate
          // pause/resume action (handleTogglePause) and must NOT be sent here.
          // Sending is_active: null would trigger NOT NULL constraint on the backend.
          name: editForm.name.trim(),
          interval_unit: editForm.interval_unit,
          interval_count: Number(editForm.interval_count) || 1,
          next_due_date: editForm.next_due_date,
          // lead_days and notes are nullable on the backend — null clears them.
          lead_days: editForm.lead_days.trim() ? Number(editForm.lead_days) : null,
          notes: editForm.notes.trim() || null,
        },
      });
      if (error) {
        setEditError(mapApiError(error));
        return;
      }
      setEditOpen(false);
      notifySuccess(t("success.updated"));
      await loadSchedules();
    } finally {
      setEditBusy(false);
    }
  }

  // ── Pause / resume handler ────────────────────────────────────────────────

  async function handleTogglePause(schedule: MaintenanceScheduleResponse) {
    setPauseBusyId(schedule.id);
    try {
      const { error } = await client.PATCH("/api/maintenance-schedules/{schedule_id}", {
        params: { path: { schedule_id: schedule.id } },
        body: { is_active: !schedule.is_active },
      });
      if (error) {
        // Surface error briefly via load error; user will see the list unchanged.
        setLoadError(mapApiError(error));
        return;
      }
      notifySuccess(schedule.is_active ? t("success.paused") : t("success.resumed"));
      await loadSchedules();
    } finally {
      setPauseBusyId(null);
    }
  }

  // ── Delete handler ────────────────────────────────────────────────────────

  function openDelete(schedule: MaintenanceScheduleResponse) {
    setDeleteId(schedule.id);
    setDeleteName(schedule.name);
    setDeleteError(null);
    setDeleteOpen(true);
  }

  async function handleDelete() {
    if (deleteId == null) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      const { error } = await client.DELETE("/api/maintenance-schedules/{schedule_id}", {
        params: { path: { schedule_id: deleteId } },
      });
      if (error) {
        setDeleteError(mapApiError(error));
        return;
      }
      setDeleteOpen(false);
      notifySuccess(t("success.deleted"));
      await loadSchedules();
    } finally {
      setDeleteBusy(false);
    }
  }

  // ── Mark done handler ─────────────────────────────────────────────────────

  function openMarkDone(schedule: MaintenanceScheduleResponse) {
    setMarkDoneId(schedule.id);
    setMarkDoneForm({ completed_on: "", note: "" });
    setMarkDoneError(null);
    setMarkDoneOpen(true);
  }

  async function handleMarkDone() {
    if (markDoneId == null) return;
    setMarkDoneBusy(true);
    setMarkDoneError(null);
    try {
      const { error } = await client.POST("/api/maintenance-schedules/{schedule_id}/complete", {
        params: { path: { schedule_id: markDoneId } },
        body: {
          completed_on: markDoneForm.completed_on.trim() || null,
          note: markDoneForm.note.trim() || null,
        },
      });
      if (error) {
        setMarkDoneError(mapApiError(error));
        return;
      }
      setMarkDoneOpen(false);
      notifySuccess(t("success.markedDone"));
      // Refetch so the advanced next_due_date + updated status chip render immediately.
      await loadSchedules();
    } finally {
      setMarkDoneBusy(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="center">
        <Title order={4}>{t("sectionTitle")}</Title>
        {canEdit && (
          <Button
            size="xs"
            variant="light"
            leftSection={<Plus size={12} />}
            onClick={openAdd}
            data-testid="maintenance-add-btn"
          >
            {t("actions.add")}
          </Button>
        )}
      </Group>

      {loading && <Loader size="xs" />}

      {!loading && loadError && (
        <Alert icon={<AlertCircle size={16} />} color="red" variant="light" data-testid="maintenance-load-error">
          {loadError}
        </Alert>
      )}

      {!loading && !loadError && schedules.length === 0 && (
        <Text size="sm" c="dimmed" data-testid="maintenance-empty">
          {t("empty")}
        </Text>
      )}

      {!loading && !loadError && schedules.length > 0 && (
        <Table.ScrollContainer minWidth={640}>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("col.name")}</Table.Th>
                <Table.Th>{t("col.recurrence")}</Table.Th>
                <Table.Th>{t("col.nextDue")}</Table.Th>
                <Table.Th>{t("col.status")}</Table.Th>
                <Table.Th>{t("col.lastCompleted")}</Table.Th>
                {canEdit && <Table.Th />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {schedules.map((s) => (
                <Table.Tr key={s.id} data-testid={`maintenance-row-${s.id}`}>
                  <Table.Td>
                    <Text size="sm" data-testid={`maintenance-name-${s.id}`}>
                      {s.name}
                    </Text>
                    {!s.is_active && (
                      <Badge size="xs" color="gray" variant="light" ml={4}>
                        paused
                      </Badge>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed" data-testid={`maintenance-recurrence-${s.id}`}>
                      {recurrenceLabel(s)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" data-testid={`maintenance-next-due-${s.id}`}>
                      {formatDate(s.next_due_date)}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      size="sm"
                      variant="light"
                      color={statusColor(s.status)}
                      data-testid={`maintenance-status-${s.id}`}
                    >
                      {t(`status.${s.status}`)}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c="dimmed" data-testid={`maintenance-last-completed-${s.id}`}>
                      {formatDate(s.last_completed_date) || "—"}
                    </Text>
                  </Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="blue"
                          onClick={() => openEdit(s)}
                          data-testid={`maintenance-edit-${s.id}`}
                          title={t("actions.edit")}
                        >
                          <Edit2 size={12} />
                        </ActionIcon>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="green"
                          onClick={() => openMarkDone(s)}
                          data-testid={`maintenance-mark-done-${s.id}`}
                          title={t("actions.markDone")}
                        >
                          <CheckCircle size={12} />
                        </ActionIcon>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color={s.is_active ? "orange" : "teal"}
                          onClick={() => void handleTogglePause(s)}
                          loading={pauseBusyId === s.id}
                          data-testid={`maintenance-pause-${s.id}`}
                          title={s.is_active ? t("actions.pause") : t("actions.resume")}
                        >
                          {s.is_active ? <PauseCircle size={12} /> : <PlayCircle size={12} />}
                        </ActionIcon>
                        <ActionIcon
                          size="sm"
                          variant="subtle"
                          color="red"
                          onClick={() => openDelete(s)}
                          data-testid={`maintenance-delete-${s.id}`}
                          title={t("actions.delete")}
                        >
                          <Trash2 size={12} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {/* Add modal */}
      <Modal
        opened={addOpen}
        onClose={() => { setAddOpen(false); setAddError(null); }}
        title={t("addModal.title")}
        size="sm"
      >
        <Stack gap="sm">
          {addError && (
            <Alert icon={<AlertCircle size={16} />} color="red" variant="light" data-testid="maintenance-add-error">
              {addError}
            </Alert>
          )}
          <TextInput
            label={t("addModal.nameLabel")}
            placeholder={t("addModal.namePlaceholder")}
            value={addForm.name}
            onChange={(e) => { const v = e.currentTarget.value; setAddForm((f) => ({ ...f, name: v })); }}
            required
            data-testid="maintenance-add-name"
          />
          <Group grow gap="xs">
            <NumberInput
              label={t("addModal.intervalCountLabel")}
              value={addForm.interval_count === "" ? "" : Number(addForm.interval_count)}
              onChange={(v) => setAddForm((f) => ({ ...f, interval_count: v === "" ? "" : String(v) }))}
              min={1}
              required
              data-testid="maintenance-add-count"
            />
            <Select
              label={t("addModal.intervalUnitLabel")}
              data={intervalUnitOptions}
              value={addForm.interval_unit}
              onChange={(v) => setAddForm((f) => ({ ...f, interval_unit: v ?? "month" }))}
              required
              data-testid="maintenance-add-unit"
            />
          </Group>
          <TextInput
            label={t("addModal.nextDueDateLabel")}
            type="date"
            value={addForm.next_due_date}
            onChange={(e) => { const v = e.currentTarget.value; setAddForm((f) => ({ ...f, next_due_date: v })); }}
            required
            data-testid="maintenance-add-next-due"
          />
          <NumberInput
            label={t("addModal.leadDaysLabel")}
            description={t("addModal.leadDaysHint")}
            value={addForm.lead_days === "" ? "" : Number(addForm.lead_days)}
            onChange={(v) => setAddForm((f) => ({ ...f, lead_days: v === "" ? "" : String(v) }))}
            min={0}
            data-testid="maintenance-add-lead-days"
          />
          <Textarea
            label={t("addModal.notesLabel")}
            value={addForm.notes}
            onChange={(e) => { const v = e.currentTarget.value; setAddForm((f) => ({ ...f, notes: v })); }}
            data-testid="maintenance-add-notes"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => { setAddOpen(false); setAddError(null); }} disabled={addBusy}>
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button
              onClick={() => void handleAdd()}
              loading={addBusy}
              disabled={!addForm.name.trim() || !addForm.next_due_date}
              data-testid="maintenance-add-submit"
            >
              {t("addModal.submit")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Edit modal */}
      <Modal
        opened={editOpen}
        onClose={() => { setEditOpen(false); setEditError(null); }}
        title={t("editModal.title")}
        size="sm"
      >
        <Stack gap="sm">
          {editError && (
            <Alert icon={<AlertCircle size={16} />} color="red" variant="light" data-testid="maintenance-edit-error">
              {editError}
            </Alert>
          )}
          <TextInput
            label={t("editModal.nameLabel")}
            value={editForm.name}
            onChange={(e) => { const v = e.currentTarget.value; setEditForm((f) => ({ ...f, name: v })); }}
            required
            data-testid="maintenance-edit-name"
          />
          <Group grow gap="xs">
            <NumberInput
              label={t("editModal.intervalCountLabel")}
              value={editForm.interval_count === "" ? "" : Number(editForm.interval_count)}
              onChange={(v) => setEditForm((f) => ({ ...f, interval_count: v === "" ? "" : String(v) }))}
              min={1}
              required
              data-testid="maintenance-edit-count"
            />
            <Select
              label={t("editModal.intervalUnitLabel")}
              data={intervalUnitOptions}
              value={editForm.interval_unit}
              onChange={(v) => setEditForm((f) => ({ ...f, interval_unit: v ?? "month" }))}
              required
              data-testid="maintenance-edit-unit"
            />
          </Group>
          <TextInput
            label={t("editModal.nextDueDateLabel")}
            type="date"
            value={editForm.next_due_date}
            onChange={(e) => { const v = e.currentTarget.value; setEditForm((f) => ({ ...f, next_due_date: v })); }}
            required
            data-testid="maintenance-edit-next-due"
          />
          <NumberInput
            label={t("editModal.leadDaysLabel")}
            description={t("editModal.leadDaysHint")}
            value={editForm.lead_days === "" ? "" : Number(editForm.lead_days)}
            onChange={(v) => setEditForm((f) => ({ ...f, lead_days: v === "" ? "" : String(v) }))}
            min={0}
            data-testid="maintenance-edit-lead-days"
          />
          <Textarea
            label={t("editModal.notesLabel")}
            value={editForm.notes}
            onChange={(e) => { const v = e.currentTarget.value; setEditForm((f) => ({ ...f, notes: v })); }}
            data-testid="maintenance-edit-notes"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => { setEditOpen(false); setEditError(null); }} disabled={editBusy}>
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button
              onClick={() => void handleEdit()}
              loading={editBusy}
              disabled={!editForm.name.trim() || !editForm.next_due_date}
              data-testid="maintenance-edit-submit"
            >
              {t("editModal.submit")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Mark done modal */}
      <Modal
        opened={markDoneOpen}
        onClose={() => { setMarkDoneOpen(false); setMarkDoneError(null); }}
        title={t("markDoneModal.title")}
        size="sm"
      >
        <Stack gap="sm">
          {markDoneError && (
            <Alert icon={<AlertCircle size={16} />} color="red" variant="light" data-testid="maintenance-mark-done-error">
              {markDoneError}
            </Alert>
          )}
          <TextInput
            label={t("markDoneModal.completedOnLabel")}
            description={t("markDoneModal.completedOnHint")}
            type="date"
            value={markDoneForm.completed_on}
            onChange={(e) => { const v = e.currentTarget.value; setMarkDoneForm((f) => ({ ...f, completed_on: v })); }}
            data-testid="maintenance-mark-done-date"
          />
          <Textarea
            label={t("markDoneModal.noteLabel")}
            value={markDoneForm.note}
            onChange={(e) => { const v = e.currentTarget.value; setMarkDoneForm((f) => ({ ...f, note: v })); }}
            data-testid="maintenance-mark-done-note"
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => { setMarkDoneOpen(false); setMarkDoneError(null); }} disabled={markDoneBusy}>
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button
              color="green"
              onClick={() => void handleMarkDone()}
              loading={markDoneBusy}
              data-testid="maintenance-mark-done-submit"
            >
              {t("markDoneModal.submit")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* Delete confirm modal */}
      <Modal
        opened={deleteOpen}
        onClose={() => { setDeleteOpen(false); setDeleteError(null); }}
        title={t("deleteModal.title")}
        size="sm"
      >
        <Stack gap="sm">
          {deleteError && (
            <Alert icon={<AlertCircle size={16} />} color="red" variant="light" data-testid="maintenance-delete-error">
              {deleteError}
            </Alert>
          )}
          {!deleteError && (
            <Text size="sm">
              {t("deleteModal.confirmation", { name: deleteName })}
            </Text>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => { setDeleteOpen(false); setDeleteError(null); }} disabled={deleteBusy}>
              {t("common:actions.cancel", "Cancel")}
            </Button>
            {!deleteError && (
              <Button
                color="red"
                onClick={() => void handleDelete()}
                loading={deleteBusy}
                data-testid="maintenance-delete-submit"
              >
                {t("deleteModal.submit")}
              </Button>
            )}
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
