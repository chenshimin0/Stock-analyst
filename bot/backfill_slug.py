"""One-shot backfill: re-slug all reports to use stock_code.

Old slug (e.g. 'HLGF') was pinyin initials and collided between stocks
whose names start with the same letters (e.g. 汉缆股份 / 海亮股份).
New slug is the stock_code lowercased ('002498') — unique by definition.

Idempotent: skips rows whose slug already equals stock_code.lower().
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "bot"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import Report  # noqa: E402


def main():
    db = SessionLocal()
    try:
        reports = db.query(Report).all()
        updated = 0
        skipped = 0
        for r in reports:
            new_slug = r.stock_code.lower() if r.stock_code else None
            if not new_slug:
                skipped += 1
                continue
            if r.slug == new_slug:
                skipped += 1
                continue
            old = r.slug
            r.slug = new_slug
            updated += 1
            print(f"  id={r.id:>3} {r.stock_code} {r.stock_name[:10]:>10}  {old} -> {new_slug}")
        db.commit()
        print(f"\nDone. updated={updated} skipped={skipped} total={len(reports)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
