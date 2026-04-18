"""Generated output descriptors used by the writer and preview commands."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeneratedFile(BaseModel):
    """A file we plan to (or already did) write to the target repo."""

    path: str = Field(description="POSIX path relative to repo root.")
    content: str
    target: str = Field(description="Logical target, e.g. 'agents', 'cursor'.")
    description: str = ""

    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


class GenerationPlan(BaseModel):
    """A bundle of files produced by a single generator invocation."""

    target: str
    files: list[GeneratedFile] = Field(default_factory=list)

    def add(self, file: GeneratedFile) -> None:
        self.files.append(file)
