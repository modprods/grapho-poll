import logging
import os
from typing import Any, Protocol

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, LogRecordExportResult
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExportResult, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

log = logging.getLogger("mod_telemetry")

_meter: Any = None
_log_provider: LoggerProvider | None = None
_meter_provider: MeterProvider | None = None

_TELEMETRY_ENVS = frozenset({"prod", "production", "staging"})


class Counter(Protocol):
    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None: ...


class Meter(Protocol):
    def create_counter(
        self, name: str, unit: str = "1", description: str = "",
    ) -> Counter: ...


class _NoopCounter:
    def add(self, amount: int, attributes: dict[str, str] | None = None) -> None:
        pass


class _NoopMeter:
    def create_counter(
        self, name: str, unit: str = "1", description: str = "",
    ) -> _NoopCounter:
        return _NoopCounter()


class _LoggingLogExporter:
    def __init__(self, exporter: OTLPLogExporter) -> None:
        self._exporter = exporter

    def export(self, batch: Any) -> LogRecordExportResult:
        result = self._exporter.export(batch)
        if result is not LogRecordExportResult.SUCCESS:
            log.error("OTLP log export failed: %s", result.name)
        return result

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporter.force_flush(timeout_millis)


class _LoggingMetricExporter:
    def __init__(self, exporter: OTLPMetricExporter) -> None:
        self._exporter = exporter

    def __getattr__(self, name: str) -> Any:
        return getattr(self._exporter, name)

    def export(self, metrics_data: Any, timeout_millis: float = 10_000, **kwargs: Any) -> MetricExportResult:
        result = self._exporter.export(metrics_data, timeout_millis=timeout_millis, **kwargs)
        if result is not MetricExportResult.SUCCESS:
            log.error("OTLP metric export failed: %s", result.name)
        return result

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        self._exporter.shutdown(timeout_millis=timeout_millis, **kwargs)

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return self._exporter.force_flush(timeout_millis=timeout_millis)


def telemetry_enabled() -> bool:
    mod_env = os.getenv("MOD_ENV", "").lower()
    if mod_env in _TELEMETRY_ENVS:
        return True
    if mod_env in ("local", "dev", "development"):
        return False
    return os.getenv("OTEL_TELEMETRY_ENABLED", "").lower() == "true"


def sanitize_otlp_endpoint() -> str:
    raw = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if any(ch in raw for ch in "\r\n"):
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT contained newlines; stripping whitespace")
    stripped = raw.strip()
    if raw != stripped:
        log.warning("OTEL_EXPORTER_OTLP_ENDPOINT had leading/trailing whitespace; stripping")
    if stripped:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = stripped
    return stripped


def init(service_name: str, version: str = "0.0.0") -> Meter:
    logging.getLogger("opentelemetry").propagate = False
    global _meter, _log_provider, _meter_provider
    if not telemetry_enabled():
        log.info(
            "Telemetry disabled (noop); set MOD_ENV=prod/staging or OTEL_TELEMETRY_ENABLED=true",
        )
        _meter = _NoopMeter()
        return _meter

    endpoint = sanitize_otlp_endpoint()
    log.info("Telemetry enabled; exporting to %s", endpoint or "(OTEL_EXPORTER_OTLP_ENDPOINT not set)")

    resource = Resource.create({
        "service.name": service_name,
        "service.version": version,
    })

    _log_provider = LoggerProvider(resource=resource)
    _log_provider.add_log_record_processor(
        BatchLogRecordProcessor(_LoggingLogExporter(OTLPLogExporter())),
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=_log_provider)
    logging.getLogger().addHandler(handler)

    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(_LoggingMetricExporter(OTLPMetricExporter()))],
    )
    metrics.set_meter_provider(_meter_provider)
    _meter = metrics.get_meter(service_name)
    return _meter


def shutdown() -> None:
    global _log_provider, _meter_provider
    if _meter_provider is not None:
        _meter_provider.shutdown()
        _meter_provider = None
    if _log_provider is not None:
        _log_provider.shutdown()
        _log_provider = None


def meter() -> Meter:
    if _meter is None:
        return _NoopMeter()
    return _meter
