"""Canonical combined archive with exact original policy, terms and inventory."""
import json
from dataclasses import asdict
from decimal import Decimal

from .authorization_archive import AuthorizedRightsAccount
from .authorization_archive_audit import validate_authorization_archive
from .codec import canonical
from .inventory_codec import decode_inventory, encode_inventory
from .payment_authorization import PaymentAuthorization
from .session_policy import PaymentInterval, RightsSessionPolicy, SubscriptionElection
from .types import PaymentRequest, PaymentTerms


def encode_authorized_account(account: AuthorizedRightsAccount) -> str:
    AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
    return canonical({"schema_version": 1, "inventory": encode_inventory(account.inventory),
        "policy": asdict(account.policy), "authorizations": [asdict(row) for row in account.authorizations]})


def decode_authorized_account(payload: str) -> AuthorizedRightsAccount:
    """Reject duplicate/extra fields and independently bind the complete archive."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate authorized-account JSON key")
            result[key] = value
        return result

    values = json.loads(payload, object_pairs_hook=unique)
    if (not isinstance(values, dict) or set(values) != {"schema_version", "inventory", "policy", "authorizations"}
            or type(values["schema_version"]) is not int or values["schema_version"] != 1):
        raise ValueError("unsupported authorized-account archive schema")
    inventory = decode_inventory(values["inventory"])
    validate_authorization_archive(values["policy"], values["authorizations"], inventory.book.receipts)

    def request(row):
        terms = dict(row["terms"])
        terms["unit_price"] = Decimal(terms["unit_price"])
        terms["evidence_sha256"] = tuple(terms["evidence_sha256"])
        return PaymentRequest(PaymentTerms(**terms), row["units"], Decimal(row["fee"]))

    policy_values = dict(values["policy"])
    policy_values["elections"] = tuple(SubscriptionElection(row["action_id"], tuple(map(request, row["requests"])))
                                       for row in policy_values["elections"])
    policy = RightsSessionPolicy(**policy_values)
    authorizations = tuple(PaymentAuthorization(policy, row["action_id"], tuple(map(request, row["requests"])),
        tuple(PaymentInterval(**{**interval, "evidence_sha256": tuple(interval["evidence_sha256"])})
              for interval in row["intervals"]), row["as_of"]) for row in values["authorizations"])
    account = AuthorizedRightsAccount(inventory, policy, authorizations)
    if encode_authorized_account(account) != payload:
        raise ValueError("authorized-account archive is not canonical")
    return account
