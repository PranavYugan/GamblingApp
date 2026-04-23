from __future__ import annotations

from config import initialize_database_and_schemas


def main() -> None:
    connection = initialize_database_and_schemas()
    connection.close()


if __name__ == "__main__":
    main()

