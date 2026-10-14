"""Pure declared-requirement coverage; no monetary or execution activation."""
from .catalog import underwriting_template
from .engine import assess_underwriting

__all__ = ["assess_underwriting", "underwriting_template"]
