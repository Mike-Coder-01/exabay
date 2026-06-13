import hmac
import hashlib
import json
import logging
import random
import string

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ── ClickPesa endpoints ────────────────────────────────────────────────────────
TOKEN_URL    = "https://api.clickpesa.com/third-parties/generate-token"
PREVIEW_URL  = "https://api.clickpesa.com/third-parties/payments/preview-ussd-push-request"
PUSH_URL     = "https://api.clickpesa.com/third-parties/payments/initiate-ussd-push-request"


# ══════════════════════════════════════════════════════════════════════════════
# ORDER REFERENCE
# ══════════════════════════════════════════════════════════════════════════════

def generate_order_reference() -> str:
    """
    Alphanumeric, max 20 chars — matches ClickPesa's requirement.
    """
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


# ══════════════════════════════════════════════════════════════════════════════
# CHECKSUM
# ══════════════════════════════════════════════════════════════════════════════

def _canonicalize(obj):
    """Recursively sort dict keys so the JSON serialisation is deterministic."""
    if isinstance(obj, dict):
        return {k: _canonicalize(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canonicalize(i) for i in obj]
    return obj


def create_payload_checksum(key: str, payload: dict) -> str:
    """
    HMAC-SHA256 over the canonicalised JSON of *payload*.

    IMPORTANT: only pass the fields that ClickPesa will sign — do NOT include
    'checksum' or 'checksumMethod' in the payload dict before calling this.
    """
    canonical     = _canonicalize(payload)
    payload_str   = json.dumps(canonical, separators=(",", ":"), sort_keys=False)
    digest        = hmac.new(
        key.encode("utf-8"),
        payload_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    logger.debug("[CHECKSUM] payload_str=%s  digest=%s", payload_str, digest)
    return digest


def validate_checksum(key: str, payload: dict, received: str) -> bool:
    if not received:
        return False
    return hmac.compare_digest(create_payload_checksum(key, payload), received)


# ══════════════════════════════════════════════════════════════════════════════
# AUTH TOKEN  (cached for the lifetime of a single checkout attempt)
# ══════════════════════════════════════════════════════════════════════════════

def generate_token() -> str | None:
    """
    Returns the raw bearer token string (without the 'Bearer ' prefix),
    or None on failure.
    """
    headers = {
        "api-key":   settings.CLICKPESA_API_KEY,
        "client-id": settings.CLICKPESA_CLIENT_ID,
    }

    try:
        r = requests.post(TOKEN_URL, headers=headers, timeout=(10, 30))
        logger.info("[TOKEN] status=%s body=%s", r.status_code, r.text)
        r.raise_for_status()

        token = r.json().get("token", "")

        # API returns "Bearer <token>" — strip the prefix so callers can
        # re-add it cleanly in the Authorization header.
        if token.startswith("Bearer "):
            token = token[len("Bearer "):]

        return token or None

    except Exception:
        logger.exception("[TOKEN] request failed")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PREVIEW
# ══════════════════════════════════════════════════════════════════════════════

def preview_payment(
    token: str,
    amount,          # Decimal or str
    order_reference: str,
    phone_number: str,
) -> requests.Response | None:
    """
    Validates the phone number and checks which mobile-money channels are live.
    Returns the raw Response so the caller can inspect status_code / json().
    """
    # Only the fields ClickPesa documents — nothing extra.
    signable = {
    "amount":             str(amount),
    "currency":           "TZS",        
    "orderReference":     order_reference,
    "phoneNumber":        phone_number,
    "fetchSenderDetails": False,
  }

    payload = {
        **signable,
        "checksum": create_payload_checksum(settings.CLICKPESA_CHECKSUM_KEY, signable),
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    try:
        r = requests.post(PREVIEW_URL, json=payload, headers=headers, timeout=(10, 60))
        logger.info("[PREVIEW] status=%s body=%s", r.status_code, r.text)
        return r
    except Exception:
        logger.exception("[PREVIEW] request failed")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# USSD PUSH
# ══════════════════════════════════════════════════════════════════════════════

def initiate_ussd_push(
    token: str,
    amount,
    order_reference: str,
    phone_number: str,
) -> requests.Response | None:
    """
    Sends the USSD push to the customer's handset.
    Returns the raw Response so the caller can inspect status_code / json().
    """
    signable = {
    "amount":         str(amount),
    "currency":       "TZS",            
    "orderReference": order_reference,
    "phoneNumber":    phone_number,
  }

    payload = {
        **signable,
        "checksum": create_payload_checksum(settings.CLICKPESA_CHECKSUM_KEY, signable),
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    try:
        r = requests.post(PUSH_URL, json=payload, headers=headers, timeout=(10, 60))
        # logger.info("[PUSH] status=%s body=%s", r.status_code, r.text)
        return r
    except Exception:
        logger.exception("[PUSH] request failed")
        return None
    
QUERY_URL = "https://api.clickpesa.com/third-parties/payments/{}"

def query_payment_status(token: str, order_reference: str) -> dict | None:
    """
    Polls ClickPesa directly for payment status.
    Returns the first payment record dict, or None on failure.
    """
    url = QUERY_URL.format(order_reference)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=(10, 30))
        # logger.info("[QUERY] status=%s body=%s", r.status_code, r.text)
        if r.status_code == 200:
            data = r.json()
            # Returns a list — get the first record
            return data[0] if isinstance(data, list) and data else None
        return None
    except Exception:
        logger.exception("[QUERY] request failed")
        return None