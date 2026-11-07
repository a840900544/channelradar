"""Package the built workbench and consistent SQLite snapshots for Windows."""

import argparse
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "requirements.txt", "alembic.ini", "providers.py", "scan_latest.py",
    "universities.csv", "start-windows.ps1", "WINDOWS_DEPLOY.md",
)
DIRECTORIES = ("radar", "migrations", "frontend/dist")
DATABASES = ("channelradar.sqlite3", "data/workbench.sqlite3")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not (ROOT / "frontend/dist/index.html").is_file():
        parser.error("请先构建前端")
    with tempfile.TemporaryDirectory() as temporary:
        snapshots = Path(temporary)
        for name in DATABASES:
            original = ROOT / name
            target = snapshots / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(original.as_uri() + "?mode=ro", uri=True)) as source:
                with closing(sqlite3.connect(target)) as destination:
                    source.backup(destination)
                    if name == "data/workbench.sqlite3":
                        destination.execute("DELETE FROM admin_sessions")
                        destination.commit()
                    if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise RuntimeError(f"数据库完整性校验失败 {name}")
        with args.output.open("xb") as output, ZipFile(output, "w", ZIP_DEFLATED) as archive:
            for name in FILES:
                archive.write(ROOT / name, name)
            for name in DIRECTORIES:
                for path in (ROOT / name).rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts:
                        archive.write(path, path.relative_to(ROOT))
            for path in (ROOT / "evidence").glob("*review*.json"):
                archive.write(path, path.relative_to(ROOT))
            for name in DATABASES:
                archive.write(snapshots / name, name)


if __name__ == "__main__":
    main()
