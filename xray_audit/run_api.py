import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run("xray_audit.api:app", host=settings.api_host, port=settings.api_port, reload=False)


if __name__ == "__main__":
    main()
