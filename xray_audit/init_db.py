from pathlib import Path
import sys

from .config import Settings
from .storage import apply_schema


def main() -> None:
    settings = Settings.from_env()
    if settings.storage_backend.strip().lower() == "d1":
        print("D1 schema is provisioned with Wrangler migrations; no Python initialization is required.")
        return
    installed_schema = Path(sys.prefix) / "sql" / "schema.sql"
    source_schema = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    schema_path = installed_schema if installed_schema.exists() else source_schema
    apply_schema(settings, str(schema_path))
    print("schema applied:", schema_path)


if __name__ == "__main__":
    main()
