"""A small, explicit toolkit for serving and evaluating an 8 GB GPU model.

The package is deliberately split by capability.  HTTP, Prometheus and
Kubernetes are adapters around the serving core; they are not the serving
core itself.
"""

__all__ = ["serving"]

