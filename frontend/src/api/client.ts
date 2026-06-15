/**
 * Typed API client.
 *
 * Wraps ``openapi-fetch`` with the generated ``paths`` type from
 * ``./schema.d.ts`` (GENERATED — do not edit that file directly; run
 * ``make codegen`` to regenerate after backend API changes).
 *
 * All API calls through this client are automatically typed for
 * path, parameters, request body, and response body.
 */
import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * The application API client.
 *
 * Orchestrator reconciliation note (binding decision):
 * The committed ``schema.d.ts`` contract has paths that include the ``/api``
 * prefix (e.g. ``paths['/api/auth/login']``), because the FastAPI app mounts
 * all routers under ``settings.api_prefix`` (default ``/api``).  Using
 * ``baseUrl: '/api'`` with these full paths would double-prefix the URL to
 * ``/api/api/auth/login``.  Therefore ``baseUrl`` is set to ``''`` (same-origin,
 * no prefix) so callers use the full typed keys that exist in ``schema.d.ts``:
 *   ``client.POST('/api/auth/login', …)``
 *   ``client.GET('/api/auth/me')``
 *   ``client.POST('/api/auth/logout')``
 * This composes to the correct single ``/api/...`` URL.
 *
 * - ``credentials: 'include'`` — ensures the session cookie is sent with
 *   every request (required for the ``HttpOnly`` session-cookie auth).
 */
export const client = createClient<paths>({
  baseUrl: "",
  credentials: "include",
});
