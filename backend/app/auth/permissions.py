"""RBAC permission matrix for Omniventory (M6 Step 1).

Three fixed roles: admin / member / viewer.
Five permissions: VIEW, EDIT, MANAGE_USERS, MANAGE_SETTINGS, VIEW_AUDIT.

The matrix is **code-defined** (no DB-driven permission table — roadmap §2.11).
Role values are plain strings stored in ``users.role``; they are validated
against ``VALID_ROLES`` in the application layer, never via a DB CHECK constraint.

Design decisions (M6 §2 "Permission map"):
    viewer  → {VIEW}
    member  → {VIEW, EDIT}
    admin   → {VIEW, EDIT, MANAGE_USERS, MANAGE_SETTINGS, VIEW_AUDIT}

Self-service routes (e.g. ``/auth/me``, own notification inbox) are **never**
gated by a permission — any authenticated user may access their own data
regardless of role.  Do not add a permission check to those routes.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Valid role set (app-layer validation — no DB CHECK/enum)
# ---------------------------------------------------------------------------

#: All role strings that the app accepts.  Validated in the service layer;
#: unknown strings from a legacy or corrupted row are treated as having **no**
#: permissions (``has_permission`` returns ``False``).
VALID_ROLES: frozenset[str] = frozenset({"admin", "member", "viewer"})


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------


class Role:
    """String constants for the three fixed roles."""

    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# ---------------------------------------------------------------------------
# Permission constants
# ---------------------------------------------------------------------------


class Permission:
    """String constants for the five permissions in the matrix.

    Values are stable identifiers used as dict keys inside ``PERMISSIONS``.
    They are not persisted to the DB; changing them here is a coordinated
    backend-only change.
    """

    VIEW = "view"
    EDIT = "edit"
    MANAGE_USERS = "manage_users"
    MANAGE_SETTINGS = "manage_settings"
    VIEW_AUDIT = "view_audit"


# ---------------------------------------------------------------------------
# Permission matrix
# ---------------------------------------------------------------------------

#: Maps each role to the set of permissions it holds.
#: Unknown roles are not present → ``has_permission`` returns ``False``.
PERMISSIONS: dict[str, set[str]] = {
    Role.VIEWER: {Permission.VIEW},
    Role.MEMBER: {Permission.VIEW, Permission.EDIT},
    Role.ADMIN: {
        Permission.VIEW,
        Permission.EDIT,
        Permission.MANAGE_USERS,
        Permission.MANAGE_SETTINGS,
        Permission.VIEW_AUDIT,
    },
}


# ---------------------------------------------------------------------------
# Permission check helper
# ---------------------------------------------------------------------------


def has_permission(role: str, perm: str) -> bool:
    """Return ``True`` if *role* has *perm*; ``False`` for unknown roles.

    Never raises — an unknown role (not in ``VALID_ROLES``) is treated as
    having no permissions.

    Parameters
    ----------
    role:
        The user's role string (e.g. ``Role.ADMIN``).
    perm:
        A ``Permission.*`` constant string to check.
    """
    return perm in PERMISSIONS.get(role, set())
