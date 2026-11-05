"""Shared test fixtures: fake Entra settings and ID-token claims."""

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "99999999-9999-9999-9999-999999999999"
OID = "22222222-2222-2222-2222-222222222222"

ENTRA_SETTINGS = {
    "ENTRA_TENANT_ID": TENANT_ID,
    "ENTRA_CLIENT_ID": "test-client-id",
    "ENTRA_CLIENT_SECRET": "test-client-secret",
    "ENTRA_REDIRECT_URI": "http://testserver/auth/callback",
    "ENTRA_ROLE_AGENT": "Agent",
    "ENTRA_ROLE_ADMIN": "Admin",
}

NO_ENTRA_SETTINGS = {
    "ENTRA_TENANT_ID": "",
    "ENTRA_CLIENT_ID": "",
    "ENTRA_CLIENT_SECRET": "",
}


def claims(**overrides) -> dict:
    """ID-token claims shaped like the ones Entra returns."""
    base = {
        "oid": OID,
        "tid": TENANT_ID,
        "name": "Dana Whitfield",
        "preferred_username": "dana.whitfield@example.com",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}
