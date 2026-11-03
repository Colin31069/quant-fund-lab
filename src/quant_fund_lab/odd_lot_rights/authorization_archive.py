"""One immutable value for inventory, full frozen policy and original authorizations."""
import json
from dataclasses import asdict, dataclass

from .authorization_archive_audit import validate_authorization_archive
from .codec import canonical
from .inventory import RightsInventory, post_rights_transition
from .payment_authorization import PaymentAuthorization, apply_authorized_subscription
from .payment_policy import RightsParticipationPolicy
from .policy_election import elect_subscription
from .session_policy import RightsSessionPolicy


@dataclass(frozen=True)
class AuthorizedRightsAccount:
    """Keep full original instructions beside their audited financial inventory.

    book.cash remains the only spendable balance. The combined value is a pure
    state boundary; SQL atomicity and source/registration authentication must
    still be provided by the durable workflow.
    """

    inventory: RightsInventory
    policy: RightsSessionPolicy
    authorizations: tuple[PaymentAuthorization, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.inventory, RightsInventory) or not isinstance(self.policy, RightsSessionPolicy):
            raise TypeError("authorized account requires typed inventory and frozen policy")
        if (type(self.authorizations) is not tuple
                or any(not isinstance(row, PaymentAuthorization) for row in self.authorizations)):
            raise TypeError("authorized account requires immutable original authorizations")
        account = self.inventory
        RightsInventory(account.initial_cash, account.initial_lots, account.book, account.lots, account.postings)
        validate_authorization_archive(json.loads(canonical(asdict(self.policy))),
            json.loads(canonical([asdict(row) for row in self.authorizations])), account.book.receipts)


def apply_account_authorization(account: AuthorizedRightsAccount,
                                authorization: PaymentAuthorization) -> AuthorizedRightsAccount:
    """Publish the inventory and original authorization together, or neither.

    Replay uses the archived authorization rather than a caller-labelled copy.
    Changed policy or command fails without modifying the caller's state.
    """
    AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
    if not isinstance(authorization, PaymentAuthorization) or authorization.policy != account.policy:
        raise ValueError("account authorization differs from its complete frozen policy")
    recorded = next((row for row in account.authorizations if row.action_id == authorization.action_id), None)
    transition = apply_authorized_subscription(account.inventory.book, authorization, recorded=recorded)
    inventory = post_rights_transition(account.inventory, transition)
    if not transition.applied:
        return account
    return AuthorizedRightsAccount(inventory, account.policy, (*account.authorizations, authorization))


def record_account_decline(account: AuthorizedRightsAccount, action_id: str,
                           right_keys: tuple[str, ...], *, as_of: str) -> AuthorizedRightsAccount:
    """Record an unlisted nonparticipation choice without changing any claims.

    This is not an irreversible legal waiver. A frozen selected payment cannot
    be silently overridden by a decline under the same account policy.
    """
    AuthorizedRightsAccount(account.inventory, account.policy, account.authorizations)
    if any(row.action_id == action_id for row in account.policy.elections):
        raise ValueError("account decline cannot override a frozen selected payment")
    policy = RightsParticipationPolicy("authorization:"+account.policy.policy_sha256,
        account.policy.frozen_at, "explicit_election", "reject_batch", "retain_until_evidenced",
        "explicit_current_marks", "already_usable", "inclusive")
    result = elect_subscription(account.inventory.book, action_id, policy,
                                right_keys, (), (), as_of=as_of, decision="decline")
    inventory = post_rights_transition(account.inventory, result)
    return (account if not result.applied else
            AuthorizedRightsAccount(inventory, account.policy, account.authorizations))
