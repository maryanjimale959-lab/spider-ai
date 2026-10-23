"""Tidy the local database after verification runs.

Verification creates real accounts and uploads real files. This removes the traces of
those probe accounts - their stored uploads and page renders - while leaving every other
account alone, and renames the one account that came with the machine so the word "demo"
is not sitting in the sign-in box.

    .venv/Scripts/python tools/cleanup_probe_runs.py            # report only
    .venv/Scripts/python tools/cleanup_probe_runs.py --apply    # do it
    .venv/Scripts/python tools/cleanup_probe_runs.py --apply --email you@example.com
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import security  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import session_scope  # noqa: E402
from app.models import Document, DocumentVersion, User  # noqa: E402

PROBE = re.compile(r"^(mariam\.\d+|hosted\.\d+|probe\.\d+)@spider\.local$")
KEEP_EMAIL = "mariam@spider.local"
NEW_PASSWORD = "spider-2026"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes (default is a dry run)")
    parser.add_argument("--email", help="also rename the machine account to this address")
    parser.add_argument("--password", help="and give it this password")
    args = parser.parse_args()

    email = args.email or KEEP_EMAIL
    password = args.password or NEW_PASSWORD
    touched = {"users": 0, "documents": 0, "files": 0, "renamed": None}

    with session_scope() as db:
        probes = [u for u in db.scalars(select(User)).all() if PROBE.match(u.email or "")]
        for user in probes:
            for document in db.scalars(select(Document).where(Document.owner_id == user.id)).all():
                for version in document.versions:
                    Path(version.storage_path).unlink(missing_ok=True)
                    shutil.rmtree(settings.rendered_dir / version.id, ignore_errors=True)
                    touched["files"] += 1
                    db.query(DocumentVersion).filter(DocumentVersion.id == version.id).delete()
                db.delete(document)
                touched["documents"] += 1
            user.is_active = False
            user.full_name = "(verification run - removed)"
            touched["users"] += 1

        legacy = db.scalar(select(User).where(User.email == "demo@spider.local"))
        if legacy is not None:
            legacy.email = email
            legacy.password_hash = security.hash_password(password)
            touched["renamed"] = f"demo@spider.local -> {email}"

        print(f"mode: {'apply' if args.apply else 'dry run'}")
        print(f"probe accounts removed: {touched['users']}  documents deleted: {touched['documents']}  files unlinked: {touched['files']}")
        print(f"account rename: {touched['renamed'] or 'nothing to rename'}")

        remaining = db.scalars(select(User).where(User.is_active.is_(True))).all()
        print("active accounts:")
        for user in remaining:
            docs = db.scalars(select(Document).where(Document.owner_id == user.id, Document.deleted_at.is_(None))).all()
            print(f"  {user.email}  ({user.full_name})  documents: {[d.title for d in docs]}")

        if not args.apply:
            db.rollback()
            print("dry run - nothing written. Re-run with --apply.")
            return 0
    print("cleanup written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
