/**
 * RequirePermission — route guard that redirects to "/" when the current user
 * lacks the given permission.
 *
 * Usage (in Routes):
 *   <Route path="/configuration" element={
 *     <RequirePermission permission="MANAGE_SETTINGS">
 *       <Configuration />
 *     </RequirePermission>
 *   } />
 *
 * With the permissive fallback (no AuthProvider — tests only), can() always
 * returns true, so there is no redirect in isolated component tests.
 */
import { Navigate } from "react-router-dom";
import { useAuth, type Permission } from "./AuthContext";

interface RequirePermissionProps {
  permission: Permission;
  children: React.ReactNode;
}

export function RequirePermission({ permission, children }: RequirePermissionProps) {
  const { can } = useAuth();
  if (!can(permission)) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
