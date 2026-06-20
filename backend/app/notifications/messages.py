"""Server-side bilingual message catalog for external notification channels (M4 §9 Step 7).

**Scoped exception to the wire/display split (M4 §2)**
------------------------------------------------------
Per the M1.5 wire/display split, the backend emits no human-readable text for
in-app notifications; the SPA localises ``message_code`` + ``params`` in the
frontend.  However, email/MQTT/HTTP payloads leave the system without ever
passing through the SPA.  For these external artifacts the backend **must**
render human text.  This module is that scoped, deliberate exception:

- It covers **only** the four reminder message codes used by the engine.
- It renders in the **recipient's preferred language** (``preferred_language``
  falling back to ``'en'``).
- The rendered text is only used by external channel adapters (``EmailChannel``,
  ``HttpChannel``, ``MqttChannel``); in-app notifications never touch this module.

Public API
----------
``render_line(code, params, lang) -> str``
    Render a single reminder notification as a one-line human-readable string.
    ``lang`` should be ``'zh'`` or ``'en'`` (any other value falls back to EN).

``render_digest(lines, lang) -> tuple[str, str]``
    Wrap a list of already-rendered lines into an email digest.
    Returns ``(subject, body)`` in the given language.

Supported codes
---------------
- ``reminder.best_before``   — a lot is approaching or past its best-before date.
- ``reminder.warranty``      — a lot's warranty is expiring or has expired.
- ``reminder.low_stock``     — a definition's stock has dropped below its threshold
                               (episode opener).
- ``reminder.low_stock_repeat`` — the low-stock condition persists (repeat reminder).
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Per-code renderers: (params, lang) -> str
# ---------------------------------------------------------------------------

# The params dict mirrors what ReminderEngine stores in Notification.params
# (JSON blob), decoded back to a Python dict by the caller.


def _render_best_before(params: dict[str, Any], lang: str) -> str:
    name = params.get("name", "")
    days: int = params.get("days_remaining", 0)

    if lang == "zh":
        if days < 0:
            return f"【临期提醒】{name} 已过期 {abs(days)} 天"
        if days == 0:
            return f"【临期提醒】{name} 今天到期"
        return f"【临期提醒】{name} 还有 {days} 天到期"
    else:
        if days < 0:
            return f"[Expiry] {name} expired {abs(days)} day(s) ago"
        if days == 0:
            return f"[Expiry] {name} expires today"
        return f"[Expiry] {name} expires in {days} day(s)"


def _render_warranty(params: dict[str, Any], lang: str) -> str:
    name = params.get("name", "")
    days: int = params.get("days_remaining", 0)

    if lang == "zh":
        if days < 0:
            return f"【保修提醒】{name} 保修已过期 {abs(days)} 天"
        if days == 0:
            return f"【保修提醒】{name} 保修今天到期"
        return f"【保修提醒】{name} 保修还有 {days} 天到期"
    else:
        if days < 0:
            return f"[Warranty] {name} warranty expired {abs(days)} day(s) ago"
        if days == 0:
            return f"[Warranty] {name} warranty expires today"
        return f"[Warranty] {name} warranty expires in {days} day(s)"


def _render_low_stock(params: dict[str, Any], lang: str) -> str:
    name = params.get("name", "")
    current = params.get("current", "")
    threshold = params.get("threshold", "")

    if lang == "zh":
        return f"【库存不足】{name} 当前库存 {current}，低于阈值 {threshold}"
    else:
        return f"[Low stock] {name} — current: {current}, threshold: {threshold}"


def _render_low_stock_repeat(params: dict[str, Any], lang: str) -> str:
    name = params.get("name", "")
    current = params.get("current", "")
    threshold = params.get("threshold", "")
    offset = params.get("offset", "")

    if lang == "zh":
        return f"【库存不足·持续提醒+{offset}天】{name} 当前库存 {current}，仍低于阈值 {threshold}"
    else:
        return (
            f"[Low stock +{offset}d] {name} — current: {current}, "
            f"threshold: {threshold} (still low)"
        )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_RENDERERS = {
    "reminder.best_before": _render_best_before,
    "reminder.warranty": _render_warranty,
    "reminder.low_stock": _render_low_stock,
    "reminder.low_stock_repeat": _render_low_stock_repeat,
}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def render_line(code: str, params: dict[str, Any], lang: str) -> str:
    """Render a single reminder notification as a human-readable line.

    Parameters
    ----------
    code:
        The ``message_code`` from the ``Notification`` row (e.g.
        ``"reminder.best_before"``).
    params:
        The decoded params dict (from ``json.loads(notification.params)``).
    lang:
        BCP-47 language tag.  ``'zh'`` renders in Chinese; any other value
        (including ``None`` after caller normalisation) renders in English.

    Returns
    -------
    str
        A single human-readable line suitable for inclusion in an email body
        or a channel payload's ``"message"`` field.

    Notes
    -----
    If ``code`` is not recognised, a generic fallback line is returned so that
    unknown future codes do not crash the channel adapter.
    """
    normalised_lang = "zh" if lang == "zh" else "en"
    renderer = _RENDERERS.get(code)
    if renderer is None:
        # Unknown code — generic fallback (graceful degradation).
        return f"[{code}]" if normalised_lang == "en" else f"【{code}】"
    return renderer(params, normalised_lang)


def render_test_email(lang: str) -> tuple[str, str]:
    """Render a test email subject and body for the SMTP test endpoint.

    Parameters
    ----------
    lang:
        BCP-47 language tag.  ``'zh'`` renders in Chinese; any other value
        renders in English.

    Returns
    -------
    (subject, body)
        A simple bilingual test email for diagnostics.
    """
    normalised_lang = "zh" if lang == "zh" else "en"

    if normalised_lang == "zh":
        subject = "Omniventory SMTP 连通性测试"
        body = (
            "您好，\n\n"
            "这是来自 Omniventory 的 SMTP 连通性测试邮件。\n\n"
            "若您收到此邮件，则表示 SMTP 配置已正确生效。\n"
        )
    else:
        subject = "Omniventory SMTP connectivity test"
        body = (
            "Hello,\n\n"
            "This is a test email from Omniventory to verify your SMTP configuration.\n\n"
            "If you received this, your SMTP settings are working correctly.\n"
        )

    return subject, body


def render_digest(lines: list[str], lang: str) -> tuple[str, str]:
    """Wrap rendered reminder lines into an email digest (subject + body).

    Parameters
    ----------
    lines:
        List of human-readable lines, each the output of ``render_line()``.
        Must be non-empty (callers should not call this for zero-line digests).
    lang:
        Language for the subject and wrapper text (``'zh'`` or ``'en'``).

    Returns
    -------
    (subject, body)
        ``subject`` — a short one-line email subject.
        ``body``    — a multi-line plain-text email body.

    Notes
    -----
    The digest is plain text (no HTML) for maximum compatibility with simple
    SMTP setups and mail catchers (Mailpit, etc.).
    """
    normalised_lang = "zh" if lang == "zh" else "en"
    count = len(lines)
    bullet_lines = "\n".join(f"  • {line}" for line in lines)

    if normalised_lang == "zh":
        subject = f"Omniventory 提醒汇总（共 {count} 条）"
        body = (
            f"您好，\n\n"
            f"以下是今日的库存与到期提醒汇总（共 {count} 条）：\n\n"
            f"{bullet_lines}\n\n"
            f"请登录 Omniventory 查看详情。\n"
        )
    else:
        subject = f"Omniventory reminder digest ({count} item{'s' if count != 1 else ''})"
        body = (
            f"Hello,\n\n"
            f"Here is your Omniventory reminder digest for today "
            f"({count} item{'s' if count != 1 else ''}):\n\n"
            f"{bullet_lines}\n\n"
            f"Please log in to Omniventory for details.\n"
        )

    return subject, body
