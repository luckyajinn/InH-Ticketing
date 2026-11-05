# Changelog

All notable changes to InH-Ticketing. Versions follow [Semantic Versioning](https://semver.org).

## [0.1.0] (unreleased)

Milestone 1: skeleton and Microsoft 365 sign-in.

### Added
- Django 6.1 project with settings from environment variables (`.env`).
- Sign-in with Microsoft 365 (Entra ID) using MSAL: OpenID Connect
  authorization code flow with PKCE. No passwords are handled.
- A custom User model keyed on the Entra object ID. Name, email and role
  sync from Entra on every sign-in.
- Roles from Entra app roles: Requester (default), Agent and Admin. Admins get
  the Django admin site, which also signs in with Microsoft 365.
- Friendly sign-in error pages for common Entra errors.
- Sign-in, home and error pages styled from the UI mockup, with light and dark mode.
- `/healthz` endpoint, Dockerfile and Docker Compose with PostgreSQL 17.
- Entra setup guide (`docs/entra-setup.md`) and the UI mockup (`mockups/`).
