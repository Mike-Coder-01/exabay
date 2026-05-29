import logging
from decimal import Decimal

import requests
from django.conf import settings

from orders.services import create_payload_checksum, generate_order_reference, generate_token

logger = logging.getLogger(__name__)


ACCOUNT_BALANCE_URL = "https://api.clickpesa.com/third-parties/account/balance"
PAYOUT_PREVIEW_URL = "https://api.clickpesa.com/third-parties/payouts/preview-mobile-money-payout"
PAYOUT_CREATE_URL = "https://api.clickpesa.com/third-parties/payouts/create-mobile-money-payout"
PAYOUT_QUERY_URL = "https://api.clickpesa.com/third-parties/payouts/{}"


def generate_payout_reference() -> str:
    return f"PO{generate_order_reference()}"[:20]


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _decimal_from_response(value, default="0.00") -> Decimal:
    if value in (None, ""):
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def build_payout_payload(amount, order_reference: str, phone_number: str, currency="TZS") -> dict:
    signable = {
        "amount": str(amount),
        "currency": currency,
        "orderReference": order_reference,
        "phoneNumber": phone_number,
    }
    return {
        **signable,
        "checksum": create_payload_checksum(settings.CLICKPESA_CHECKSUM_KEY, signable),
    }


def retrieve_account_balance(token: str) -> requests.Response | None:
    try:
        response = requests.get(ACCOUNT_BALANCE_URL, headers=_headers(token), timeout=(10, 30))
        logger.info("[PAYOUT BALANCE] status=%s body=%s", response.status_code, response.text)
        return response
    except Exception:
        logger.exception("[PAYOUT BALANCE] request failed")
        return None


def preview_mobile_money_payout(token: str, amount, order_reference: str, phone_number: str) -> requests.Response | None:
    payload = build_payout_payload(amount, order_reference, phone_number)
    try:
        response = requests.post(PAYOUT_PREVIEW_URL, json=payload, headers=_headers(token), timeout=(10, 60))
        logger.info("[PAYOUT PREVIEW] status=%s body=%s", response.status_code, response.text)
        return response
    except Exception:
        logger.exception("[PAYOUT PREVIEW] request failed")
        return None


def create_mobile_money_payout(token: str, amount, order_reference: str, phone_number: str) -> requests.Response | None:
    payload = build_payout_payload(amount, order_reference, phone_number)
    try:
        response = requests.post(PAYOUT_CREATE_URL, json=payload, headers=_headers(token), timeout=(10, 60))
        logger.info("[PAYOUT CREATE] status=%s body=%s", response.status_code, response.text)
        return response
    except Exception:
        logger.exception("[PAYOUT CREATE] request failed")
        return None


def query_payout_status(token: str, order_reference: str) -> requests.Response | None:
    try:
        response = requests.get(PAYOUT_QUERY_URL.format(order_reference), headers=_headers(token), timeout=(10, 30))
        logger.info("[PAYOUT QUERY] status=%s body=%s", response.status_code, response.text)
        return response
    except Exception:
        logger.exception("[PAYOUT QUERY] request failed")
        return None


def extract_payout_fee(payload: dict) -> Decimal:
    return _decimal_from_response(payload.get("fee"))


def extract_total_deducted(payload: dict) -> Decimal:
    return _decimal_from_response(payload.get("amount"))
