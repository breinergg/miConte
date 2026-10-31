"""Policy document version registry for miConte.

Bump a version string here when a document changes substantively.
Users who have accepted a previous version will be prompted to re-accept
the new one on their next login.
"""

PRIVACY_POLICY_VERSION = "1.0"
TERMS_OF_USE_VERSION = "1.0"

# Canonical map from document_type to its current required version.
# Keys are stored in policy_acceptances.document_type.
REQUIRED_ACCEPTANCES: dict[str, str] = {
    "privacy_policy": PRIVACY_POLICY_VERSION,
    "terms_of_use": TERMS_OF_USE_VERSION,
}
