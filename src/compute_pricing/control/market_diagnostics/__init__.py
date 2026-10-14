"""Pure conditional quote diagnostics, excluded from compute-price admission."""
from .ladder import DiagnosticError, evaluate_threshold_ladder

__all__ = ["DiagnosticError", "evaluate_threshold_ladder"]
