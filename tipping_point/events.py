"""Commitment events: what a reader (stub or LLM) extracts from chat. Pure data, no money."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Kind(str, Enum):
    SET = "SET"                  # participant wants exactly qty (of variant)
    ADD = "ADD"                  # participant adds qty
    REMOVE = "REMOVE"            # participant removes qty
    CANCEL = "CANCEL"            # participant drops out (of variant, or entirely)
    SET_VARIANT = "SET_VARIANT"  # participant switches their existing line to variant
    COPY = "COPY"                # "same as X"
    MAYBE = "MAYBE"              # soft interest, not counted
    QUESTION = "QUESTION"        # needs an answer, not counted


class CommitmentEvent(BaseModel):
    kind: Kind
    participant: str = Field(description="Who the order is for (the payer). Usually the sender.")
    source_id: int = Field(description="Message id the event came from")
    qty: int | None = None
    variant: str | None = None
    copy_from: str | None = None
    added_by: str | None = Field(default=None, description="Set when someone orders on another person's behalf")
    note: str | None = None
