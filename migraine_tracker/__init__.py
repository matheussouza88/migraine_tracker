import logging
import os
import sys
import time
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from flask import Flask, g, request
from werkzeug.exceptions import HTTPException

from migraine_tracker import database, pages

load_dotenv()


def normalize_db_url(url: str) -> str:
    """Ensure PostgreSQL URLs explicitly use the installed psycopg2 driver.

    In SQLAlchemy 2.1+, generic 'postgresql://' defaults to 'psycopg' (v3).
    Since migraine_tracker relies on 'psycopg2', normalize 'postgresql://' to
    'postgresql+psycopg2://' so SQLAlchemy correctly resolves the DBAPI.
    """
    if url.startswith("postgresql://"):
        return f"postgresql+psycopg2://{url[13:]}"
    return url


def mask_db_url(url: str) -> str:
    """Mask credentials in database URI for safe log output."""
    try:
        parsed = urlsplit(url)
        if parsed.password:
            netloc = f"{parsed.username}:******@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunsplit(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
    except Exception:
        pass
    return url


def configure_logging(app: Flask):
    """Configure structured logging and request access timing."""
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S %z"
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(log_level)

    # Configure app.logger
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(log_level)
    app.logger.propagate = False

    # Configure root migraine_tracker namespace logger
    root_logger = logging.getLogger("migraine_tracker")
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    root_logger.propagate = False

    # Silence default duplicate Werkzeug request logging at INFO level
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    @app.before_request
    def record_request_start_time():
        g.request_start_time = time.perf_counter()

    @app.after_request
    def log_response_info(response):
        start_time = getattr(g, "request_start_time", None)
        if start_time is not None:
            latency_ms = (time.perf_counter() - start_time) * 1000
            duration_str = f"{latency_ms:.2f}ms"
        else:
            duration_str = "unknown"

        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        http_logger = logging.getLogger("migraine_tracker.http")
        http_logger.info(
            '%s - "%s %s %s" %s %s - %s',
            client_ip,
            request.method,
            request.full_path if request.query_string else request.path,
            request.environ.get("SERVER_PROTOCOL", "HTTP/1.1"),
            response.status_code,
            response.content_length or "-",
            duration_str,
        )
        return response

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return e
        root_logger.error(
            "Unhandled exception processing %s %s: %s",
            request.method,
            request.path,
            str(e),
            exc_info=True,
        )
        return {"error": "Internal server error"}, 500


def create_app(test_config=None):
    app = Flask(__name__)

    # Default configuration
    default_db = os.getenv(
        "DATABASE_URL",
        "sqlite:///migraine.sqlite",
    )
    sqlite_path = os.getenv("FLASK_DATABASE")
    if sqlite_path and not os.getenv("DATABASE_URL"):
        default_db = f"sqlite:///{sqlite_path}"
    else:
        default_db = normalize_db_url(default_db)

    app.config.from_mapping(
        SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-secret-key"),
        SQLALCHEMY_DATABASE_URI=default_db,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)

    configure_logging(app)
    logger = logging.getLogger("migraine_tracker")
    logger.info(
        "Initializing Migraine Tracker (Environment: %s)",
        os.getenv("FLASK_ENV", "production"),
    )
    logger.info(
        "Configured Database URI: %s",
        mask_db_url(app.config["SQLALCHEMY_DATABASE_URI"]),
    )

    database.init_app(app)
    logger.info("Database initialized successfully.")

    app.register_blueprint(pages.bp)
    logger.info("Migraine Tracker application ready.")

    return app
