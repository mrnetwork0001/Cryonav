"""
Real outbound notification for Sentinel escalations.

Until now the Sentinel's `dispatch` verdict returned the string "911 / Municipal Heat
Response" and sent nothing. This module actually delivers a push notification — to a
user-nominated contact, never to emergency services.

WHY NOT 911: there is no public API by which a civilian application can file an emergency
call, and vendors say so explicitly (Twilio, verbatim: "You should not rely on Twilio
Programmable SMS if you require delivery of SMS communications to emergency services such
as 911 or E911"). Anything claiming otherwise in a hackathon build would be dangerous
theatre. Notifying a contact the user nominated is the legitimate, implementable version,
and it is what this does.

TRANSPORT: ntfy (https://ntfy.sh), an open-source pub/sub notifier. A POST to a
topic URL delivers to every subscribed phone. No account, no key, no per-message cost, and
the server is self-hostable — so a municipality could run its own rather than depend on a
third party. The topic name is the secret; treat it like a credential.

CONFIGURATION
    CRYONAV_NTFY_TOPIC   topic to publish to. Unset => notifications disabled, and the API
                         says so rather than pretending a message went out.
    CRYONAV_NTFY_SERVER  defaults to https://ntfy.sh; point at a self-hosted instance.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

DEFAULT_SERVER = "https://ntfy.sh"
TIMEOUT_S = 6.0


def _ascii(text: str) -> str:
    """Header-safe rendering: HTTP header values cannot carry arbitrary UTF-8."""
    return text.encode("ascii", "replace").decode("ascii")


def is_configured() -> bool:
    return bool(os.getenv("CRYONAV_NTFY_TOPIC", "").strip())


def _topic() -> str:
    return os.getenv("CRYONAV_NTFY_TOPIC", "").strip()


def _server() -> str:
    return (os.getenv("CRYONAV_NTFY_SERVER") or DEFAULT_SERVER).rstrip("/")


def send_dispatch(
    *,
    position: tuple,
    reading: Dict[str, Any],
    dwell_minutes: float,
    accuracy_m: Optional[float] = None,
    shelter: Optional[Dict[str, Any]] = None,
    city_id: str = "",
) -> Dict[str, Any]:
    """Publish a heat-emergency alert. Returns a result describing what actually happened.

    Never raises: a failed notification must not take down the safety response that
    triggered it. The returned dict always states plainly whether a message was sent, so
    the UI can say "notified" only when that is true.
    """
    if not is_configured():
        return {
            "sent": False,
            "channel": "ntfy",
            "reason": "CRYONAV_NTFY_TOPIC not configured — no notification was sent",
        }

    lat, lon = position
    where = f"{lat:.5f},{lon:.5f}"
    acc = f" (±{accuracy_m:.0f} m)" if accuracy_m is not None else ""
    refuge = ""
    if shelter:
        refuge = (
            f" Nearest air-conditioned refuge: {shelter.get('name')}"
            f" ({shelter.get('distance_m')} m, ~{shelter.get('walk_minutes')} min walk)."
        )
    body = (
        f"Immobility detected in extreme heat.\n"
        f"Position: {where}{acc}\n"
        f"Stationary for {dwell_minutes:.0f} min of continuous high-risk exposure.\n"
        f"Air {reading.get('air_temp_2m_f')}°F, surface {reading.get('surface_temp_f')}°F, "
        f"risk {str(reading.get('risk_level', '')).upper()}."
        f"{refuge}\n"
        f"Map: https://www.google.com/maps?q={lat:.5f},{lon:.5f}"
    )

    started = time.perf_counter()
    try:
        import httpx  # noqa: PLC0415

        resp = httpx.post(
            f"{_server()}/{_topic()}",
            content=body.encode("utf-8"),
            headers={
                # HTTP header values are latin-1; the body is free to carry UTF-8 but the
                # title is not, so it stays ASCII. (A "·" here silently failed every send.)
                "Title": _ascii(
                    f"Cryonav Sentinel: heat emergency{' - ' + city_id if city_id else ''}"
                ),
                "Priority": "urgent",
                "Tags": "rotating_light",
                "Markdown": "no",
            },
            timeout=TIMEOUT_S,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        if resp.status_code >= 400:
            return {
                "sent": False,
                "channel": "ntfy",
                "reason": f"notification server returned {resp.status_code}",
                "latency_ms": elapsed,
            }
        payload = {}
        try:
            payload = resp.json()
        except ValueError:
            pass
        return {
            "sent": True,
            "channel": "ntfy",
            "server": _server(),
            "message_id": payload.get("id"),
            "latency_ms": elapsed,
            "recipient": "user-nominated contact subscribed to the alert topic",
        }
    except Exception as exc:  # noqa: BLE001 — never break the safety path
        return {
            "sent": False,
            "channel": "ntfy",
            "reason": f"{type(exc).__name__}: {exc}",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
