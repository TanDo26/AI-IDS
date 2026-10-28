"""
Create the first admin account, or promote an existing user to admin.

The password is prompted for (never put it on the command line); for automation, set
IDS_ADMIN_PASSWORD instead. The account's email address counts as confirmed: whoever runs this
script vouches for it (IDS_EMAIL_VERIFICATION).
"""
import os
import sys
import getpass
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from src.api.auth.schemas import normalize_email
from src.api.auth.security import hash_password, validate_password
from src.api.db.models import AuditLog, User
from src.api.db.session import get_sessionmaker


def read_password() -> str:
    password = os.environ.get("IDS_ADMIN_PASSWORD")
    if password is None:
        password = getpass.getpass("Admin password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("  Passwords do not match")
    try:
        validate_password(password)
    except ValueError as e:
        sys.exit(f"  {e}")
    return password


def main(email, username, promote):
    email = normalize_email(email)
    with get_sessionmaker()() as db:
        user = db.scalar(select(User).where(User.email == email))
        if promote:
            if user is None:
                sys.exit(f"  No user with email {email}")
            user.role, user.is_active = "admin", True
            user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
            action = "user.promote"
        else:
            if user is not None:
                sys.exit(f"  {email} already exists; use --promote to make it an admin")
            if not username:
                sys.exit("  --username is required when creating an account")
            if db.scalar(select(User).where(User.username == username)) is not None:
                sys.exit(f"  Username {username} is taken")
            user = User(email=email, username=username, password_hash=hash_password(read_password()),
                        role="admin", email_verified_at=datetime.now(timezone.utc))
            db.add(user)
            action = "user.create_admin"
        db.flush()
        db.add(AuditLog(actor_id=None, action=action, target_type="user", target_id=str(user.id),
                        details={"email": email, "via": "scripts/create_admin.py"}))
        db.commit()
        print(f"  Admin ready: {user.email} ({user.username}), id {user.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an admin account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--username", help="Required when creating a new account")
    parser.add_argument("--promote", action="store_true", help="Make an existing user an admin")
    args = parser.parse_args()
    main(args.email, args.username, args.promote)
