"""Create demo accounts, load the sample documents, and run a real investigation on each.

    ./.venv/Scripts/python.exe tools/seed_demo.py

Every finding written by this script comes from the analysis engine reading the sample
text. Nothing is hardcoded.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import services  # noqa: E402
from app.core.database import Base, engine, session_scope  # noqa: E402
from app.models import DocumentVersion, Investigation, User  # noqa: E402
from app.security import hash_password  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

# One person, one workspace: a single demo account owns every sample document.
ACCOUNTS = [
    ("demo@spider.local", "Demo Workspace", "user", "spider-demo-2026"),
    ("admin@spider.local", "SPIDER Administrator", "admin", "spider-admin-2026"),
]
OWNER = "demo@spider.local"

DOCUMENTS = [
    ("english_report.pdf", "pdf"),
    ("english_report.docx", "docx"),
    ("english_report.md", "markdown"),
    ("english_report.txt", "txt"),
    ("english_report.html", "html"),
    ("reading_log.csv", "csv"),
    ("arabic_report.md", "markdown"),
    ("somali_report.md", "markdown"),
]

def ensure_users() -> dict[str, User]:
    users: dict[str, User] = {}
    with session_scope() as db:
        for email, name, role, password in ACCOUNTS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, full_name=name, role=role, password_hash=hash_password(password))
                db.add(user)
                db.flush()
                print(f"  created {role:8s} {email}")
            users[email] = user
    return users


def ensure_documents(users: dict[str, User]) -> None:
    with session_scope() as db:
        for filename, fmt in DOCUMENTS:
            owner = users[OWNER]
            path = SAMPLES / filename
            if not path.exists():
                print(f"  missing sample {filename} - run tools/make_samples.py first")
                continue
            data = path.read_bytes()
            # Duplicate detection is by content hash and owner, not by title: several
            # formats of the same report are deliberately kept side by side.
            duplicate = db.scalars(
                select(DocumentVersion).where(DocumentVersion.sha256 == hashlib.sha256(data).hexdigest())
            ).all()
            if any(db.get(services.Document, version.document_id).owner_id == owner.id for version in duplicate):
                continue
            document, version = services.store_upload(db, owner, filename, data)
            services.extract_version(db, version)
            document.title = f"{path.stem} ({fmt.upper()})"
            db.flush()
            print(f"  loaded {filename:24s} passages={len(version.passages)} words={version.word_count} lang={version.language}")


def run_investigations(users: dict[str, User]) -> None:
    with session_scope() as db:
        for version in db.scalars(select(DocumentVersion)).all():
            already = db.scalar(
                select(Investigation).where(Investigation.version_id == version.id,
                                            Investigation.status == "completed")
            )
            if already is not None:
                continue
            document = db.get(services.Document, version.document_id)
            owner = db.get(User, document.owner_id)
            investigation = services.create_investigation(db, version, owner, None)
            services.execute_investigation(db, investigation)
            metrics = investigation.metrics or {}
            print(
                f"  investigated {version.filename:24s} -> {metrics.get('validated_findings')} findings "
                f"({metrics.get('rejected_findings')} rejected), {metrics.get('keywords')} keywords, "
                f"{metrics.get('graph_counts', {}).get('nodes')} nodes, {metrics.get('elapsed_seconds')}s"
            )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Accounts:")
    users = ensure_users()
    print("Documents:")
    ensure_documents(users)
    print("Investigations:")
    run_investigations(users)
    print("\nSign in with:  demo@spider.local / spider-demo-2026")


if __name__ == "__main__":
    main()
