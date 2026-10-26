"""Metadata contracts around third-party quantization implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    source: Path
    dtype: str = "bf16"


@dataclass(frozen=True, slots=True)
class CalibrationManifest:
    name: str
    source: Path
    samples: int
    sha256: str
    split: str


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    name: str
    source_model: str
    algorithm: str
    algorithm_version: str
    files: tuple[tuple[str, int, str], ...]
    total_bytes: int

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        name: str,
        source_model: str,
        algorithm: str,
        algorithm_version: str,
    ) -> "ArtifactManifest":
        files: list[tuple[str, int, str]] = []
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append((path.relative_to(directory).as_posix(), path.stat().st_size, digest))
        return cls(
            name=name,
            source_model=source_model,
            algorithm=algorithm,
            algorithm_version=algorithm_version,
            files=tuple(files),
            total_bytes=sum(size for _, size, _ in files),
        )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

