"""Convert rations, ammunition and animal feed saved as plain gear into tracked supplies.

Characters and animals made before rations were counted in days and ammunition one at a time keep entries
like "Week's iron rations" or "Quiver with 20 arrows". This turns them into "Iron rations" (7 days) and
"Arrows" (20), the way new characters get them. Run it once with the bot stopped:

    python tools/convert_supplies.py            # show what would change
    python tools/convert_supplies.py --apply    # change it (a backup copy of the database is made first)

Unclear rations ("Rations", "Iron Rations") count as a week each. Running it again changes nothing.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from acks import supplies  # noqa: E402
from acks.storage import Storage  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="save the changes (default: only list them)")
    ap.add_argument("--db", default=os.getenv("DATABASE_PATH", str(ROOT / "data" / "acks.db")))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"No database at {db}")
    if args.apply:
        backup = db.with_name(f"{db.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(db, backup)
        print(f"Backup: {backup}")
    store = Storage(db)
    total = 0
    with store._lock:
        guilds = [r[0] for r in store._conn.execute("SELECT DISTINCT guild_id FROM characters "
                                                    "UNION SELECT DISTINCT guild_id FROM animals")]
    for gid in guilds:
        for holder, save in [*((c, store.save) for c in store.list_for_guild(gid)),
                             *((a, store.save_animal) for a in store.animals_for_guild(gid))]:
            changes = supplies.convert_legacy(holder)
            if not changes:
                continue
            total += len(changes)
            print(f"{holder.name} (#{holder.id}{', animal' if save == store.save_animal else ''}):")
            for line in changes:
                print(f"  {line}")
            if args.apply:
                save(holder)
    store.close()
    if not total:
        print("Nothing to convert.")
    elif not args.apply:
        print(f"\n{total} item(s) would change. Run again with --apply to save.")
    else:
        print(f"\n{total} item(s) converted.")


if __name__ == "__main__":
    main()
