"""OpenTelemetry setup: traces, metrics and logs to any OTLP endpoint (Dash0 at the hackathon).

Everything is driven by the standard environment variables, so the same container works unconfigured
(spans stay in-process and are dropped) or pointed at Dash0:

  OTEL_EXPORTER_OTLP_ENDPOINT   e.g. https://ingress.us-west-2.aws.dash0.com
  OTEL_EXPORTER_OTLP_HEADERS    e.g. Authorization=Bearer <auth token>,Dash0-Dataset=default
  OTEL_SERVICE_NAME             defaults to the name passed in
  OTEL_RESOURCE_ATTRIBUTES      e.g. deployment.environment=hackathon

When no endpoint is set, a console exporter is NOT used either: the app simply does not export, so a
laptop run stays quiet.
"""

from __future__ import annotations

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

_configured = False


def setup_telemetry(service_name: str) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    resource = Resource.create({SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", service_name)})
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider

    tracer_provider = TracerProvider(resource=resource)
    meter_readers = []
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        meter_readers.append(
            PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15000)
        )
        _setup_logs(resource)
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=meter_readers))

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning("httpx instrumentation not active: %s", exc)
    try:
        from opentelemetry.instrumentation.elasticsearch import ElasticsearchInstrumentor

        ElasticsearchInstrumentor().instrument()
    except Exception:
        pass  # optional package; the search span in api.py still covers the call
    logging.getLogger(__name__).info("telemetry ready, exporting=%s", bool(endpoint))


def _setup_logs(resource: Resource) -> None:
    """Ship Python logging records as OTLP logs, correlated with the active span."""
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

        provider = LoggerProvider(resource=resource)
        provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(provider)
        logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=provider))
        logging.getLogger().setLevel(logging.INFO)
    except Exception as exc:  # pragma: no cover
        logging.getLogger(__name__).warning("log export not active: %s", exc)


def get_tracer(name: str):
    return trace.get_tracer(name)


def get_meter(name: str):
    return metrics.get_meter(name)
