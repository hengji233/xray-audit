from pathlib import Path

from .config import Settings
from .storage import apply_schema


def main() -> None:
    settings = Settings.from_env()
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
    apply_schema(settings, str(schema_path))
    print("schema applied:", schema_path)


if __name__ == "__main__":
    main()
