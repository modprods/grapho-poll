import logging
import os
from typing import Any, Protocol

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_meter: Any = None

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


def telemetry_enabled() -> bool:
    mod_env = os.getenv("MOD_ENV", "").lower()
    if mod_env in _TELEMETRY_ENVS:
        return True
    if mod_env in ("local", "dev", "development"):
        return False
    return os.getenv("OTEL_TELEMETRY_ENABLED", "").lower() == "true"


def init(service_name: str, version: str = "0.0.0") -> Meter:
    global _meter
    if not telemetry_enabled():
        log = logging.getLogger("mod_telemetry")
        log.debug("Telemetry disabled (MOD_ENV=%r); using noop meter", os.getenv("MOD_ENV"))
        _meter = _NoopMeter()
        return _meter

    resource = Resource.create({
        "service.name": service_name,
        "service.version": version,
    })

    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter()),
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
    logging.getLogger().addHandler(handler)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(service_name)
    return _meter


def meter() -> Meter:
    if _meter is None:
        return _NoopMeter()
    return _meter
