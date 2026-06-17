/**
 * Toast notification helpers — thin wrappers around @mantine/notifications.
 *
 * Design:
 *  - Callers pass an already-translated string (from `t(...)`) — this helper
 *    has no knowledge of i18n keys and never calls `t()` itself.  This
 *    preserves the wire/display split: backend codes → i18n → display text →
 *    toast.
 *  - Unified color/icon/autoClose: success = teal + CheckCircle;
 *    error = red + AlertCircle.
 *  - React icons (react-feather) are created with React.createElement so this
 *    module stays a plain .ts file (no JSX pragma needed).
 *  - The `<Notifications>` container is mounted in main.tsx (once, app-wide).
 *    Calling these helpers without the container mounted is safe — Mantine
 *    queues the notification and shows it once the container appears.
 */

import { notifications } from "@mantine/notifications";
import { createElement } from "react";
import { CheckCircle, AlertCircle } from "react-feather";

/** Auto-close delay (ms) for success toasts. */
const SUCCESS_AUTO_CLOSE = 3000;

/** Auto-close delay (ms) for error toasts. */
const ERROR_AUTO_CLOSE = 5000;

/** Icon size (px) shown inside the toast. */
const ICON_SIZE = 16;

/**
 * Show a top-center success toast.
 *
 * @param message  Already-translated display string from the caller.
 */
export function notifySuccess(message: string): void {
  notifications.show({
    message,
    color: "teal",
    icon: createElement(CheckCircle, { size: ICON_SIZE }),
    autoClose: SUCCESS_AUTO_CLOSE,
  });
}

/**
 * Show a top-center error toast.
 *
 * NOTE: The primary error-display mechanism for validation/request failures is
 * the inline `Alert` component (mapApiError → Alert).  This helper is only
 * used when an additional toast is clearly helpful.
 *
 * @param message  Already-translated display string from the caller.
 */
export function notifyError(message: string): void {
  notifications.show({
    message,
    color: "red",
    icon: createElement(AlertCircle, { size: ICON_SIZE }),
    autoClose: ERROR_AUTO_CLOSE,
  });
}
