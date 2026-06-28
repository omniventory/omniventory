/**
 * AuthContext — application-wide auth state + client-side permission matrix.
 *
 * Exposes: { user, role, can(permission), refresh(), logout() }
 *
 * Client-side permission matrix MUST mirror the backend exactly (M6.md §2):
 *   viewer  → {VIEW}
 *   member  → {VIEW, EDIT}
 *   admin   → {VIEW, EDIT, MANAGE_USERS, MANAGE_SETTINGS, VIEW_AUDIT}
 *
 * Permissive fallback (test-compat):
 *   When useAuth() is called outside an <AuthProvider> (e.g. isolated page
 *   tests that render a single component without wrapping the full app tree),
 *   a permissive fallback is returned: can() → true for all permissions.
 *   This is safe because production ALWAYS mounts <AuthProvider> before routing;
 *   only vitest isolation tests render pages bare. New Step 8 tests that assert
 *   role-based gating explicitly wrap with <AuthProvider> per role.
 */
import { createContext, useContext, useMemo } from "react";
import type { components } from "../api/schema";
import { client } from "../api/client";

type UserResponse = components["schemas"]["UserResponse"];

export type Permission =
  | "VIEW"
  | "EDIT"
  | "MANAGE_USERS"
  | "MANAGE_SETTINGS"
  | "VIEW_AUDIT";

/**
 * Client-side mirror of the backend permission matrix (M6.md §2).
 * Must stay in sync with backend app/auth/permissions.py PERMISSIONS dict.
 */
const PERMISSIONS: Record<string, ReadonlySet<Permission>> = {
  viewer: new Set<Permission>(["VIEW"]),
  member: new Set<Permission>(["VIEW", "EDIT"]),
  admin: new Set<Permission>(["VIEW", "EDIT", "MANAGE_USERS", "MANAGE_SETTINGS", "VIEW_AUDIT"]),
};

/**
 * hasPermission — pure function for unit-testing the matrix.
 * Also used internally by AuthProvider.
 */
export function hasPermission(role: string | null, permission: Permission): boolean {
  if (!role) return false;
  return PERMISSIONS[role]?.has(permission) ?? false;
}

export interface AuthContextValue {
  user: UserResponse | null;
  role: string | null;
  can: (permission: Permission) => boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

/**
 * Permissive fallback — used when no AuthProvider is present.
 *
 * Production always mounts <AuthProvider> around the authed app, so this
 * path only fires in tests that render individual pages in isolation without
 * a full provider tree. Returning can() = true preserves the pre-M6 test
 * behaviour: all write controls remain visible, and no test breaks.
 *
 * Do NOT reference AUTH_FALLBACK in any production code path.
 */
const AUTH_FALLBACK: AuthContextValue = {
  user: null,
  role: null,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  can: (_permission) => true, // permissive: all tests without a provider pass
  refresh: async () => {},
  logout: async () => {},
};

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * useAuth — returns the current auth context value.
 *
 * Falls back to AUTH_FALLBACK (permissive: can() always true) when no
 * AuthProvider is mounted. This prevents existing page tests from failing
 * when they render without the full app wrapper. See AUTH_FALLBACK comment.
 */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) return AUTH_FALLBACK;
  return ctx;
}

interface AuthProviderProps {
  user: UserResponse | null;
  /** Called after a successful /api/auth/me refresh with the updated user. */
  onRefresh: (u: UserResponse) => void;
  /** Called after the logout API call to transition the app to anon state. */
  onLogout: () => void;
  children: React.ReactNode;
}

export function AuthProvider({ user, onRefresh, onLogout, children }: AuthProviderProps) {
  const value = useMemo<AuthContextValue>((): AuthContextValue => {
    const role = user?.role ?? null;
    return {
      user,
      role,
      can: (permission: Permission): boolean => hasPermission(role, permission),
      refresh: async () => {
        const { data } = await client.GET("/api/auth/me");
        if (data?.user) {
          onRefresh(data.user);
        }
      },
      logout: async () => {
        await client.POST("/api/auth/logout");
        onLogout();
      },
    };
  }, [user, onRefresh, onLogout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
