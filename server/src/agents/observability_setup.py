"""
Agent Framework observability configuration.

Configures OpenTelemetry tracing, logging, and metrics
export to Azure Application Insights when a connection
string is provided via the ``APPLICATIONINSIGHTS_CONNECTION_STRING``
environment variable.  If the variable is absent, telemetry
is silently disabled and the application runs without any
observability overhead.
"""

from __future__ import annotations

import os
from typing import Any, cast

from agent_framework import observability
from azure.monitor.opentelemetry import exporter

from src.utils import logger

log = logger.create_logger("Observability")


def setup() -> None:
    """Configure Agent Framework observability with Azure Application Insights."""
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if not connection_string:
        log.warn("APPLICATIONINSIGHTS_CONNECTION_STRING not set — telemetry disabled")
        return

    exporters = [
        exporter.AzureMonitorTraceExporter(
            connection_string=connection_string,
        ),
        exporter.AzureMonitorLogExporter(
            connection_string=connection_string,
        ),
        exporter.AzureMonitorMetricExporter(
            connection_string=connection_string,
        ),
    ]

    observability.configure_otel_providers(exporters=cast(list[Any], exporters))

    log.success("Agent Framework observability configured with Azure Monitor")
