# config.py (add fields + parsing)
from dataclasses import dataclass
import os
from pathlib import Path

# Lazy dotenv load only for non-production convenience
if os.getenv("ENVIRONMENT", "development") != "production":
    try:
        if Path('.env').exists():
            from dotenv import load_dotenv  # type: ignore
            load_dotenv()
    except Exception:  # pragma: no cover
        pass

@dataclass(frozen=True)
class Config:
    # Core bot / external API
    telegram_token: str
    tls_login_url: str

    # Monitoring cadence
    check_interval: int
    min_check_interval: int
    max_check_interval: int
    jitter_ratio: float

    # Content classification patterns
    negative_patterns: tuple[str, ...]
    captcha_markers: tuple[str, ...]
    block_markers: tuple[str, ...]

    # Selenium / navigation
    headless: bool
    login_wait_seconds: int
    window_size: str
    user_data_dir: str
    stealth_mode: bool
    remote_debug_port: int | None
    start_monitor_after_login: bool
    custom_user_agent: str | None

    # Persistence & subscribers
    subscribers_file: str
    subscriber_backend: str  # file | memory (extensible for redis/postgres)

    # Resilience
    error_backoff_base: int
    error_backoff_max: int
    cooldown_on_captcha: int
    failure_threshold: int

    # Security / access control
    whitelist_usernames: tuple[str, ...]

    # Observability
    log_level: str
    log_format: str  # text | json
    metrics_port: int | None

    # Feature toggles
    enable_status_command: bool
    enable_metrics: bool

    @staticmethod
    def load() -> "Config":
        def _bool(val: str | None, default: bool = False) -> bool:
            if val is None:
                return default
            return val.strip().lower() in ("1", "true", "yes", "on")

        def _tuple(env_name: str, default: str, sep: str = ";") -> tuple[str, ...]:
            raw = os.getenv(env_name, default)
            # allow both ; and , as separators
            parts: list[str] = []
            for token in raw.replace(",", sep).split(sep):
                token = token.strip()
                if token:
                    parts.append(token.lower())
            return tuple(parts)

        metrics_port_env = os.getenv("METRICS_PORT", "")
        metrics_port = int(metrics_port_env) if metrics_port_env.strip().isdigit() else None

        return Config(
            telegram_token=os.environ["TELEGRAM_TOKEN"],
            tls_login_url=os.getenv("TLS_LOGIN_URL", "https://visas-de.tlscontact.com/en/ir/THR/login"),
            check_interval=int(os.getenv("CHECK_INTERVAL", "300")),
            min_check_interval=int(os.getenv("MIN_CHECK_INTERVAL", "180")),
            max_check_interval=int(os.getenv("MAX_CHECK_INTERVAL", "420")),
            jitter_ratio=float(os.getenv("JITTER_RATIO", "0.20")),
            negative_patterns=_tuple(
                "NEGATIVE_PATTERNS",
                "no appointment;not available;no slots;no appointments available",
            ),
            captcha_markers=_tuple(
                "CAPTCHA_MARKERS",
                "verify;captcha;are you human;robot check",
            ),
            block_markers=_tuple(
                "BLOCK_MARKERS",
                "too many requests;429;temporarily blocked;suspicious activity",
            ),
            headless=_bool(os.getenv("HEADLESS", "false")),
            login_wait_seconds=int(os.getenv("LOGIN_WAIT_SECONDS", "90")),
            window_size=os.getenv("WINDOW_SIZE", "1280,900"),
            user_data_dir=os.getenv("USER_DATA_DIR", "chrome_profile"),
            stealth_mode=_bool(os.getenv("STEALTH_MODE", "true"), True),
            remote_debug_port=(int(p) if (p:=os.getenv("REMOTE_DEBUG_PORT","")) and p.isdigit() else None),
            start_monitor_after_login=_bool(os.getenv("START_MONITOR_AFTER_LOGIN", "true"), True),
            custom_user_agent=os.getenv("CUSTOM_USER_AGENT") or None,
            subscribers_file=os.getenv("SUBSCRIBERS_FILE", "subscribers.json"),
            subscriber_backend=os.getenv("SUBSCRIBER_BACKEND", "file"),
            error_backoff_base=int(os.getenv("ERROR_BACKOFF_BASE", "30")),
            error_backoff_max=int(os.getenv("ERROR_BACKOFF_MAX", "600")),
            cooldown_on_captcha=int(os.getenv("COOLDOWN_ON_CAPTCHA", "1800")),
            failure_threshold=int(os.getenv("FAILURE_THRESHOLD", "5")),
            whitelist_usernames=_tuple("WHITELIST_USERNAMES", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_format=os.getenv("LOG_FORMAT", "text").lower(),
            metrics_port=metrics_port,
            enable_status_command=_bool(os.getenv("ENABLE_STATUS_COMMAND", "true"), True),
            enable_metrics=_bool(os.getenv("ENABLE_METRICS", "false"), False),
        )
