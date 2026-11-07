"""Create or promote the bootstrap admin user (idempotent).

Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, then run:

    uv run python -m scripts.seed_admin

This is intentionally a CLI task rather than app-startup side effect: it keeps
credentials out of logs and lets operators rotate the admin password explicitly.
"""

from __future__ import annotations

import sys

from app.core.config import settings
from app.core.auth import hash_password
from app.database.session import SessionLocal
from app.models.enums import UserRole
from app.services.auth import AuthService
from app.services.tenant import ensure_default_tenant


def main() -> int:
    email = (settings.BOOTSTRAP_ADMIN_EMAIL or "").strip()
    password = settings.BOOTSTRAP_ADMIN_PASSWORD or ""
    if not email or not password:
        print(
            "Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD "
            "before running this command.",
            file=sys.stderr,
        )
        return 1

    db = SessionLocal()
    try:
        tenant = ensure_default_tenant(db)
        service = AuthService(db)
        user = service.get_user_by_email(email)
        if user is None:
            service.create_user(
                email=email,
                password=password,
                tenant_id=tenant.id,
                role=UserRole.ADMIN,
                is_active=True,
                is_superadmin=True,
            )
            print(f"Created admin user {email.lower()}.")
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.ADMIN
            user.is_active = True
            user.is_superadmin = True
            db.commit()
            print(f"Updated admin user {user.email}.")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
