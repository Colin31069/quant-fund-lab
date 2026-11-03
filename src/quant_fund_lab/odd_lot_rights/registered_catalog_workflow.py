"""Source-authenticated historical catalog admission; no forward activation."""
from .catalog_workflow import commit_catalog_day, verify_catalog_ledger
from .registered_source import RegisteredRightsSource, authenticate_registered_catalog


def commit_registered_catalog_day(ledger, catalog, requests_directory,
                                   binding: RegisteredRightsSource, *, _fault=None):
    """Recheck real registry/study/code before and inside the SQL transaction.

    Requires a locally pinned catalog in addition to original registered source
    authentication. New issuer rights commands remain fail-closed until an
    authenticated supplement/adapter is implemented. Historical replay is never
    a valid forward-observation result.
    """
    assessment = authenticate_registered_catalog(binding, catalog, requests_directory)

    def guard(phase):
        if _fault is not None:
            _fault(phase)
        if authenticate_registered_catalog(binding, catalog, requests_directory) != assessment:
            raise ValueError("registered rights binding changed during SQL admission")

    result = commit_catalog_day(ledger, catalog, requests_directory, _fault=guard)
    authenticate_registered_catalog(binding, catalog, requests_directory)
    return result


def verify_registered_catalog(ledger, catalog, requests_directory,
                               binding: RegisteredRightsSource):
    assessment = authenticate_registered_catalog(binding, catalog, requests_directory)
    state = verify_catalog_ledger(ledger, catalog, requests_directory)
    if authenticate_registered_catalog(binding, catalog, requests_directory) != assessment:
        raise ValueError("registered rights binding changed during readonly verification")
    return assessment, state
