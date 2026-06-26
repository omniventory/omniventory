/**
 * NotePanel — reusable owner-metadata component for managing free-text notes.
 *
 * Features:
 *  - List: displays all notes for an owner with timestamps.
 *  - Add: Textarea at the bottom, submits via POST /api/notes.
 *  - Edit: inline edit mode per note (click Edit button → textarea → Save/Cancel).
 *  - Delete: per-note with a small confirm modal.
 *  - Empty / loading / error states.
 *
 * M5 Step 9.
 */
import { useState, useEffect, useCallback } from "react";
import {
  Stack,
  Group,
  Text,
  Title,
  Button,
  Textarea,
  Alert,
  Card,
  Modal,
  Loader,
  ActionIcon,
} from "@mantine/core";
import { Edit2, Trash2, AlertCircle } from "react-feather";
import { useTranslation } from "react-i18next";
import { client } from "../api/client";
import { mapApiError } from "../i18n/errors";
import { notifySuccess } from "./notify";
import { formatDate } from "../i18n/format";
import type { components } from "../api/schema";

// ── Types ─────────────────────────────────────────────────────────────────────

type NoteResponse = components["schemas"]["NoteResponse"];

export type NoteOwnerType = "item_definition" | "stock_instance" | "location";

export interface NotePanelProps {
  modelType: NoteOwnerType;
  modelId: number;
}

// ── NotePanel ─────────────────────────────────────────────────────────────────

export function NotePanel({ modelType, modelId }: NotePanelProps) {
  const { t } = useTranslation("notes");

  // ── Notes list state ──────────────────────────────────────────────────────
  const [notes, setNotes] = useState<NoteResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // ── Add note state ────────────────────────────────────────────────────────
  const [addBody, setAddBody] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // ── Edit note state ───────────────────────────────────────────────────────
  const [editNote, setEditNote] = useState<{ id: number; body: string } | null>(
    null,
  );
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // ── Delete state ──────────────────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<NoteResponse | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // ── Data loading ──────────────────────────────────────────────────────────

  const loadNotes = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const { data, error } = await client.GET("/api/notes", {
        params: { query: { model_type: modelType, model_id: modelId } },
      });
      if (error) {
        setLoadError(mapApiError(error));
        return;
      }
      setNotes(data ?? []);
    } finally {
      setLoading(false);
    }
  }, [modelType, modelId]);

  useEffect(() => {
    void loadNotes();
  }, [loadNotes]);

  // ── Add note ──────────────────────────────────────────────────────────────

  async function handleAdd() {
    const body = addBody.trim();
    if (!body) return;
    setAdding(true);
    setAddError(null);
    try {
      const { error } = await client.POST("/api/notes", {
        body: { model_type: modelType, model_id: modelId, body },
      });
      if (error) {
        setAddError(mapApiError(error));
        return;
      }
      setAddBody("");
      notifySuccess(t("success.created"));
      await loadNotes();
    } finally {
      setAdding(false);
    }
  }

  // ── Edit note ─────────────────────────────────────────────────────────────

  async function handleSaveEdit() {
    if (!editNote) return;
    const body = editNote.body.trim();
    if (!body) return;
    setSaving(true);
    setEditError(null);
    try {
      const { error } = await client.PATCH("/api/notes/{note_id}", {
        params: { path: { note_id: editNote.id } },
        body: { body },
      });
      if (error) {
        setEditError(mapApiError(error));
        return;
      }
      notifySuccess(t("success.updated"));
      setEditNote(null);
      await loadNotes();
    } finally {
      setSaving(false);
    }
  }

  // ── Delete note ───────────────────────────────────────────────────────────

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const { error } = await client.DELETE("/api/notes/{note_id}", {
        params: { path: { note_id: deleteTarget.id } },
      });
      if (error) {
        setDeleteError(mapApiError(error));
        return;
      }
      setDeleteTarget(null);
      notifySuccess(t("success.deleted"));
      await loadNotes();
    } finally {
      setDeleting(false);
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Stack gap="sm" data-testid="note-panel">
      <Title order={5}>{t("sectionTitle")}</Title>

      {/* Loading / error / list */}
      {loading ? (
        <Loader size="sm" data-testid="note-loading" />
      ) : loadError ? (
        <Alert
          icon={<AlertCircle size={16} />}
          color="red"
          variant="light"
          data-testid="note-load-error"
        >
          {loadError}
        </Alert>
      ) : notes.length === 0 ? (
        <Text size="sm" c="dimmed" data-testid="note-empty">
          {t("emptyState")}
        </Text>
      ) : (
        <Stack gap="xs">
          {notes.map((note) => {
            const isEditing = editNote?.id === note.id;

            return (
              <Card
                key={note.id}
                padding="xs"
                withBorder
                data-testid={`note-card-${note.id}`}
              >
                <Stack gap={4}>
                  {isEditing ? (
                    <>
                      <Textarea
                        value={editNote.body}
                        onChange={(e) =>
                          setEditNote((prev) =>
                            prev
                              ? { ...prev, body: e.currentTarget.value }
                              : null,
                          )
                        }
                        autosize
                        minRows={2}
                        size="xs"
                        data-testid={`note-edit-textarea-${note.id}`}
                      />
                      {editError && (
                        <Alert
                          icon={<AlertCircle size={16} />}
                          color="red"
                          variant="light"
                          data-testid={`note-edit-error-${note.id}`}
                        >
                          {editError}
                        </Alert>
                      )}
                      <Group gap="xs">
                        <Button
                          size="xs"
                          variant="light"
                          loading={saving}
                          onClick={handleSaveEdit}
                          data-testid={`note-save-btn-${note.id}`}
                        >
                          {t("saveBtn")}
                        </Button>
                        <Button
                          size="xs"
                          variant="default"
                          disabled={saving}
                          onClick={() => { setEditNote(null); setEditError(null); }}
                          data-testid={`note-cancel-btn-${note.id}`}
                        >
                          {t("cancelBtn")}
                        </Button>
                      </Group>
                    </>
                  ) : (
                    <>
                      <Text
                        size="sm"
                        style={{ whiteSpace: "pre-wrap" }}
                        data-testid={`note-body-${note.id}`}
                      >
                        {note.body}
                      </Text>
                      <Group justify="space-between" align="center">
                        <Text size="xs" c="dimmed">
                          {formatDate(note.updated_at)}
                        </Text>
                        <Group gap={4}>
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            onClick={() => {
                              setEditError(null);
                              setEditNote({ id: note.id, body: note.body });
                            }}
                            data-testid={`note-edit-btn-${note.id}`}
                            aria-label={t("editBtn")}
                          >
                            <Edit2 size={12} />
                          </ActionIcon>
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="red"
                            onClick={() => {
                              setDeleteError(null);
                              setDeleteTarget(note);
                            }}
                            data-testid={`note-delete-btn-${note.id}`}
                            aria-label={t("deleteBtn")}
                          >
                            <Trash2 size={12} />
                          </ActionIcon>
                        </Group>
                      </Group>
                    </>
                  )}
                </Stack>
              </Card>
            );
          })}
        </Stack>
      )}

      {/* Add note area */}
      <Stack gap="xs">
        {addError && (
          <Alert
            icon={<AlertCircle size={16} />}
            color="red"
            variant="light"
            data-testid="note-add-error"
          >
            {addError}
          </Alert>
        )}
        <Textarea
          placeholder={t("bodyPlaceholder")}
          value={addBody}
          onChange={(e) => setAddBody(e.currentTarget.value)}
          autosize
          minRows={2}
          size="xs"
          data-testid="note-add-textarea"
        />
        <Group justify="flex-end">
          <Button
            size="xs"
            variant="light"
            loading={adding}
            disabled={!addBody.trim()}
            onClick={handleAdd}
            data-testid="note-add-btn"
          >
            {t("addBtn")}
          </Button>
        </Group>
      </Stack>

      {/* Delete confirmation modal */}
      <Modal
        opened={deleteTarget !== null}
        onClose={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        title={t("deleteConfirm.title")}
        size="sm"
      >
        <Stack gap="sm">
          {deleteError && (
            <Alert
              icon={<AlertCircle size={16} />}
              color="red"
              variant="light"
              data-testid="note-delete-error"
            >
              {deleteError}
            </Alert>
          )}
          {!deleteError && (
            <Text size="sm">{t("deleteConfirm.text")}</Text>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => {
                setDeleteTarget(null);
                setDeleteError(null);
              }}
              disabled={deleting}
            >
              {t("common:actions.cancel", "Cancel")}
            </Button>
            {!deleteError && (
              <Button
                color="red"
                onClick={handleDelete}
                loading={deleting}
                data-testid="confirm-delete-note-btn"
              >
                {t("deleteConfirm.confirmBtn")}
              </Button>
            )}
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
