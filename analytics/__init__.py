#!/usr/bin/env python3
"""
Kickoff Pulse — analytics engine.

Metrics are declared in the registry and evaluated by the query engine, so a new
metric is a definition rather than a function scattered across the app.

Importing this package populates the registry, so `analytics.get("shots")` works
without the caller needing to know which module declared it.
"""

from .query import EventQuery, select  # noqa: F401
from .registry import (Metric, MetricResult, catalogue, compute,  # noqa: F401
                       get, by_category, per90, register)
from . import core_metrics  # noqa: F401  (registers the core definitions)
from .core_metrics import stat_block  # noqa: F401

__all__ = ["EventQuery", "select", "Metric", "MetricResult", "compute", "get",
           "by_category", "catalogue", "per90", "register", "stat_block"]
