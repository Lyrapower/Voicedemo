import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO") -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(log_dir / "grid_router.log")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level))
    if not root.handlers:
        root.addHandler(console)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
