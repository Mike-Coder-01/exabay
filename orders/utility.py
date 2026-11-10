import base64

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.conf import settings
from django.core.cache import cache

from .services import generate_token


url = "https://api.clickpesa.com/third-parties/billpay/create-order-control-number"
TOKEN_URL = "https://authenticator.azampay.co.tz/AppRegistration/GenerateToken"

AZAMPAY_PUBLIC_KEY_CACHE = "azampay_public_key"
AZAMPAY_PUBLIC_KEY_CACHE_TTL = 60 * 60 * 24


# AzamPay payment utilities

def token_generation():
    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/json"},
        json={
            "appName": "Exxabay",
            "clientId": settings.AZAM_CLIENT_ID,
            "clientSecret": settings.AZAM_CLIENT_SECRET,
        },
        timeout=(3, 5),
    )
    response.raise_for_status()
    return response.json()["data"]["accessToken"]


def fetch_azampay_public_key(url, headers=None):
    try:
        response = requests.get(
            url,
            headers=headers or {},
            timeout=10,
        )
        response.raise_for_status()
        response_data = response.json()
    except (requests.RequestException, ValueError):
        return None

    if isinstance(response_data, dict) and response_data.get("success"):
        return response_data.get("publicKey") or None

    return None


def get_azampay_public_key(url, headers=None, force_refresh=False):
    """Return the cached AzamPay public key unless a refresh is requested."""
    if not force_refresh:
        cached_key = cache.get(AZAMPAY_PUBLIC_KEY_CACHE)
        if cached_key:
            return cached_key

    public_key = fetch_azampay_public_key(url, headers)
    if public_key:
        cache.set(
            AZAMPAY_PUBLIC_KEY_CACHE,
            public_key,
            AZAMPAY_PUBLIC_KEY_CACHE_TTL,
        )

    return public_key


def verify_callback_signature(
    utility_ref: str,
    external_reference: str,
    transaction_status: str,
    operator_name: str,
    signature_b64: str,
    public_key_pem: str,
) -> bool:
    data_to_verify = (
        f"{utility_ref}{external_reference}{transaction_status}{operator_name}"
    ).encode("utf-8")

    try:
        signature_bytes = base64.b64decode(signature_b64)
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8")
        )
        public_key.verify(
            signature_bytes,
            data_to_verify,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception:
        return False

    return True


class Payments:
    def __init__(self, webhook, headers, body):
        self.webhook = webhook
        self.headers = headers
        self.body = body

    def make_azam_pesa_post_request(self):
        response = requests.post(
            self.webhook,
            headers=self.headers,
            json=self.body,
            timeout=(3, 10),
        )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            return {
                "success": False,
                "message": "AzamPay request failed",
                "status_code": response.status_code,
            }

        try:
            data = response.json()
        except requests.exceptions.JSONDecodeError:
            data = None

        if not isinstance(data, dict):
            return {
                "success": False,
                "message": "AzamPay returned an unexpected response",
                "status_code": response.status_code,
            }

        return data


# Legacy ClickPesa payment utilities

def get_click_pesa_fee(amount):
    if 500 <= amount <= 999:
        return 54
    if 1000 <= amount <= 1999:
        return 96
    if 2000 <= amount <= 2999:
        return 124
    if 3000 <= amount <= 3999:
        return 230
    if 4000 <= amount <= 4999:
        return 380
    if 5000 <= amount <= 9999:
        return 580
    if 10000 <= amount <= 19999:
        return 920
    if 20000 <= amount <= 39999:
        return 1150
    if 40000 <= amount <= 49999:
        return 1572
    if 50000 <= amount <= 99999:
        return 2136
    if 100000 <= amount <= 199999:
        return 3240
    if 200000 <= amount <= 299999:
        return 3660
    if 300000 <= amount <= 399999:
        return 4080
    if 400000 <= amount <= 499999:
        return 4340
    if 500000 <= amount <= 599999:
        return 4820
    if 600000 <= amount <= 799999:
        return 5230
    if 800000 <= amount <= 999999:
        return 6146
    if 1000000 <= amount <= 1999999:
        return 7210
    if 2000000 <= amount <= 3000000:
        return 7960

    return 0


def generate_paybill_number(descriptions, price, bill_reference):
    headers = {
        "Authorization": "Bearer " + generate_token(),
        "Content-Type": "application/json",
    }

    body = {
        "billDescription": descriptions,
        "billPaymentMode": "EXACT",
        "billAmount": price + get_click_pesa_fee(price),
        "billReference": bill_reference,
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
    )

    try:
        data = response.json()
    except ValueError:
        data = {}

    return {
        "success": response.ok,
        "status_code": response.status_code,
        "data": data.get("billPayNumber"),
    }