
import base64
import hashlib
import logging
import time
import uuid

from decimal import Decimal, InvalidOperation

import requests

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from django.conf import settings


logger = logging.getLogger(__name__)


# ============================================================
# AZAMPAY PRODUCTION ENDPOINTS
# ============================================================

BASE_URL = settings.AZAMPAY_DISBURSEMENT_BASE_URL.rstrip("/")

AUTH_URL = settings.AZAMPAY_DISBURSEMENT_AUTH_URL

BALANCE_CHECK_URL = (
    f"{BASE_URL}/api/v1/azampay/checkbalance/azampesa"
)

BANK_NAMES_URL = (
    f"{BASE_URL}/api/v1/azampay/BankNames"
)

NAME_LOOKUP_URL = (
    f"{BASE_URL}/api/v1/azampay/namelookup"
)

PAYOUT_CREATE_URL = (
    f"{BASE_URL}/api/v1/azampay/disburse"
)

PAYOUT_QUERY_URL = (
    f"{BASE_URL}/api/v1/azampay/transactionstatus"
)

AZAMPAY_PROVIDER_MAP = {
    "mpesa": "Vodacom",
    "tigo_pesa": "Yas",
    "airtel_money": "Airtel",
    "halopesa": "Halotel",
}


def get_azampay_provider(seller_settings):
    """
    Convert Exxabay mobile money provider values
    into AzamPay Disbursement identifiers.
    """

    if seller_settings is None:
        raise ValueError("Seller payout settings are missing.")

    provider = seller_settings.mobile_money_provider

    bank_name = AZAMPAY_PROVIDER_MAP.get(provider)

    if not bank_name:
        raise ValueError(
            f"Unsupported AzamPay payout provider: {provider}"
        )

    return bank_name

# ============================================================
# 1. GENERATE DISBURSEMENT TOKEN
# ============================================================

def generate_disbursement_token():
    """
    Generate an AzamPay production access token.

    AzamPay confirmed that Disbursement uses the
    same production credentials as Collections.
    """

    payload = {
        "appName": settings.AZAMPAY_DISBURSEMENT_APP_NAME,
        "clientId": settings.AZAMPAY_DISBURSEMENT_CLIENT_ID,
        "clientSecret": settings.AZAMPAY_DISBURSEMENT_CLIENT_SECRET,
    }

    try:
        response = requests.post(
            AUTH_URL,
            json=payload,
            timeout=(10, 30),
        )

        response.raise_for_status()

        data = response.json()

        token_data = data.get("data")

        if isinstance(token_data, dict):
            token = token_data.get("accessToken")
        else:
            token = None

        if not token:
            logger.error(
                "AzamPay Disbursement authentication "
                "succeeded but accessToken is missing."
            )
            return None

        logger.info(
            "AzamPay Disbursement token generated successfully."
        )

        return token

    except requests.RequestException:
        logger.exception(
            "AzamPay Disbursement authentication failed."
        )
        return None

    except (ValueError, AttributeError, TypeError):
        logger.exception(
            "Invalid AzamPay authentication response."
        )
        return None


# ============================================================
# 2. REQUEST HEADERS
# ============================================================

def _headers(token, *, accept="application/json"):
    """
    Build authenticated AzamPay API headers.
    """

    if not token:
        raise ValueError(
            "AzamPay access token is required."
        )

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": accept,
    }


# ============================================================
# 3. SHARED HTTP REQUEST HELPER
# ============================================================

def _request(
    method,
    url,
    token,
    *,
    headers_override=None,
    **kwargs,
):
    """
    Make an authenticated AzamPay API request.

    Returns:
        requests.Response on an HTTP response.
        None on a network/request exception.

    Important:
        A timeout during a POST disbursement does
        not prove that the transfer failed.
        Never automatically retry such a transfer.
    """

    headers = _headers(token)

    if headers_override:
        headers.update(headers_override)

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=(10, 60),
            **kwargs,
        )

        logger.info(
            "AzamPay Disbursement API request: "
            "method=%s status=%s",
            method,
            response.status_code,
        )

        return response

    except requests.RequestException:
        logger.exception(
            "AzamPay Disbursement API request failed: "
            "method=%s",
            method,
        )
        return None


# ============================================================
# 4. CHECK DISBURSEMENT WALLET BALANCE
# ============================================================

def retrieve_account_balance(token):
    """
    Retrieve the AzamPay disbursement wallet balance.

    This is a read-only operation.

    Production endpoint confirmed by AzamPay:
    GET /api/v1/azampay/checkbalance/azampesa
    """

    return _request(
        "GET",
        BALANCE_CHECK_URL,
        token,
        headers_override={
            "Accept": "text/plain",
        },
    )


# ============================================================
# 5. RETRIEVE SUPPORTED BANK NAMES
# ============================================================

def retrieve_bank_names(token):
    """
    Retrieve supported bank/operator names.

    Production endpoint:
    GET /api/v1/azampay/BankNames

    The provider's example did not specify whether
    bearer authentication is required. This function
    sends it for consistency.
    """

    return _request(
        "GET",
        BANK_NAMES_URL,
        token,
    )


# ============================================================
# 6. GENERATE DISBURSEMENT CHECKSUM
# ============================================================

def generate_disbursement_checksum(
    source_account,
    destination_account,
    currency,
    amount,
    epoch_date,
    external_reference_id,
    public_key_pem,
):
    """
    Generate the checksum using the existing
    Exxabay implementation.

    Process:
        1. Concatenate transaction fields.
        2. Generate SHA-512 digest.
        3. Encrypt digest with RSA PKCS1v15.
        4. Encode encrypted bytes using Base64.

    IMPORTANT:
        This algorithm must match AzamPay's
        official Disbursement checksum specification
        before real transfers are enabled.
    """

    if not public_key_pem:
        raise ValueError(
            "AzamPay Disbursement public key is missing."
        )

    input_string = (
        str(source_account)
        + str(destination_account)
        + str(currency)
        + str(amount)
        + str(epoch_date)
        + str(external_reference_id)
    )

    sha512_hash = hashlib.sha512(
        input_string.encode("utf-8")
    ).digest()

    public_key = serialization.load_pem_public_key(
        public_key_pem.encode("utf-8")
    )

    encrypted_data = public_key.encrypt(
        sha512_hash,
        padding.PKCS1v15(),
    )

    return base64.b64encode(
        encrypted_data
    ).decode("utf-8")


# ============================================================
# 7. LOOK UP SELLER ACCOUNT NAME
# ============================================================

def lookup_seller_name(
    token,
    bank_name,
    account_number,
    checksum,
):
    """
    Look up the registered name of a seller account.

    The endpoint is retained from your existing
    integration; its production contract still
    needs confirmation from AzamPay.
    """

    payload = {
        "bankName": bank_name,
        "accountNumber": account_number,
        "checksum": checksum,
    }

    return _request(
        "POST",
        NAME_LOOKUP_URL,
        token,
        json=payload,
    )


# ============================================================
# 8. VALIDATE TRANSFER AMOUNT
# ============================================================

def _validate_transfer_amount(amount):
    """
    Validate a positive TZS transfer amount.

    Returns Decimal without converting to float.
    """

    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "Invalid disbursement amount."
        )

    if not value.is_finite() or value <= 0:
        raise ValueError(
            "Disbursement amount must be positive."
        )

    if value != value.to_integral_value():
        raise ValueError(
            "TZS disbursement amount must be a whole number."
        )

    return value


# ============================================================
# 9. CREATE MOBILE MONEY PAYOUT
# ============================================================

def create_mobile_money_payout(
    token,
    amount,
    order_reference,
    phone_number,
    *,
    source,
    destination_name,
    bank_name,
    transfer_type,
    checksum,
    date_in_epoch,
):
    """
    Submit a seller payout to AzamPay.

    WARNING:
        This function can transfer real money
        when called with production credentials.

    It does not automatically retry failed or
    timed-out requests.

    Caller must handle:
        - Payout eligibility
        - Duplicate prevention
        - Reservation locking
        - Unknown outcomes
        - Provider reconciliation
    """

    validated_amount = _validate_transfer_amount(
        amount
    )

    if not order_reference:
        raise ValueError(
            "Payout order reference is required."
        )

    if not phone_number:
        raise ValueError(
            "Seller phone number is required."
        )

    if not checksum:
        raise ValueError(
            "AzamPay payout checksum is required."
        )

    if not isinstance(source, dict):
        raise ValueError(
            "Source account must be a dictionary."
        )

    destination = {
        "countryCode": "TZ",
        "fullName": destination_name,
        "bankName": bank_name,
        "accountNumber": phone_number,
        "currency": "TZS",
    }

    payload = {
        "source": source,
        "destination": destination,
        "transferDetails": {
            "type": transfer_type,
            "amount": int(validated_amount),
            "dateInEpoch": date_in_epoch,
        },
        "externalReferenceId": order_reference,
        "checksum": checksum,
        "remarks": "Exxabay seller payout",
    }

    logger.info(
        "Submitting AzamPay seller payout: "
        "reference=%s amount=%s",
        order_reference,
        validated_amount,
    )

    return _request(
        "POST",
        PAYOUT_CREATE_URL,
        token,
        json=payload,
    )


# ============================================================
# 10. QUERY PAYOUT TRANSACTION STATUS
# ============================================================

def query_payout_status(
    token,
    pg_reference_id,
    bank_name,
):
    """
    Query AzamPay for a payout's current status.

    Production endpoint confirmed by AzamPay:
    GET /api/v1/azampay/transactionstatus

    Query parameters:
        pgReferenceId
        bankName

    This function never initiates a transfer.
    """

    if not pg_reference_id:
        raise ValueError(
            "pgReferenceId is required."
        )

    if not bank_name:
        raise ValueError(
            "bankName is required."
        )

    return _request(
        "GET",
        PAYOUT_QUERY_URL,
        token,
        params={
            "pgReferenceId": pg_reference_id,
            "bankName": bank_name,
        },
    )


# ============================================================
# 11. EXTRACT PAYOUT FEE
# ============================================================

def extract_payout_fee(payload):
    """
    AzamPay's supplied Disbursement response
    documentation does not confirm a fee field.

    Do not invent a fee value.
    """

    return Decimal("0.00")


# ============================================================
# 12. EXTRACT TOTAL DEDUCTED
# ============================================================

def extract_total_deducted(payload):
    """
    Actual wallet deduction cannot be established
    from the transfer amount alone.

    The zero here is a compatibility placeholder,
    not a confirmed actual deduction.
    """

    return Decimal("0.00")


# ============================================================
# 13. CONTROLLED TEST PAYOUT
# ============================================================

def test_azampay_disbursement(
    token,
    *,
    source_account,
    source_name,
    destination_account,
    destination_name,
    amount,
    bank_name="Azampesa",
    confirm_live_transfer=False,
):
    """
    Explicitly controlled live transfer helper.

    This function sends real money when enabled.

    Requires:
        confirm_live_transfer=True

    Do not use arbitrary hardcoded test accounts
    in the production environment.
    """

    if confirm_live_transfer is not True:
        raise ValueError(
            "Live transfer not confirmed. "
            "Set confirm_live_transfer=True explicitly."
        )

    validated_amount = _validate_transfer_amount(
        amount
    )

    epoch_date = int(time.time())

    external_reference_id = (
        f"EXX-{uuid.uuid4().hex[:16].upper()}"
    )

    checksum = generate_disbursement_checksum(
        source_account=source_account,
        destination_account=destination_account,
        currency="TZS",
        amount=str(int(validated_amount)),
        epoch_date=epoch_date,
        external_reference_id=external_reference_id,
        public_key_pem=(
            settings.AZAMPAY_DISBURSEMENT_PUBLIC_KEY
        ),
    )

    source = {
        "countryCode": "TZ",
        "fullName": source_name,
        "bankName": "Azampesa",
        "accountNumber": source_account,
        "currency": "TZS",
    }

    return create_mobile_money_payout(
        token=token,
        amount=validated_amount,
        order_reference=external_reference_id,
        phone_number=destination_account,
        source=source,
        destination_name=destination_name,
        bank_name=bank_name,
        transfer_type="MobileMoney",
        checksum=checksum,
        date_in_epoch=epoch_date,
    )
