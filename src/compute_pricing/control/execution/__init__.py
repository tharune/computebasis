"""Paper simulation controls only; no external execution rail."""

from .paper import Actor, Approval, DecisionSnapshot, PaperIntent, PaperJournal, PaperLeg, approve_snapshot, validate_approvals

__all__ = ["Actor", "Approval", "DecisionSnapshot", "PaperIntent", "PaperJournal", "PaperLeg", "approve_snapshot", "validate_approvals"]
