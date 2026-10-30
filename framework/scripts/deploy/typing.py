"""Type-only contracts for the existing injected scheduler and current-run records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, TypeAlias, TypedDict

from utils.type_contracts import JsonObject, JsonValue


class StackOptions(TypedDict, total=False):
    artifacts: list[dict[str, str]]
    templateBucket: str
    templateKeyPrefix: str


class StackUnit(StackOptions):
    name: str
    template: str
    parameters: str
    deployOrder: str | int


# Stack operation records also supply the minimal unfinished-operation journal.
StackState: TypeAlias = JsonObject
States: TypeAlias = dict[str, StackState]
Target: TypeAlias = dict[str, str]
Manifest: TypeAlias = dict[str, str | None]
AwsValue: TypeAlias = (
    JsonValue | date | datetime | bytes | list["AwsValue"] | dict[str, "AwsValue"]
)
AwsResponse: TypeAlias = dict[str, AwsValue]
Save: TypeAlias = Callable[[], None]
Sleep: TypeAlias = Callable[[float], None]
PathsFor: TypeAlias = Callable[[StackUnit], tuple[Path, Path]]
InputPaths: TypeAlias = Callable[[Iterable[StackUnit]], list[Path]]


class DeployRunContext(TypedDict, total=False):
    deployResult: str
    snapshotValidation: str
    stepwise: bool
    stepUnits: list[StackUnit]
    checkpointPending: JsonObject
    currentFailure: str | None
    repository: str
    taskFile: str
    taskDigest: str
    inputDigest: str
    inputDigests: dict[str, str]
    states: States
    metrics: dict[str, float]
    modelInputs: Manifest
    consumedInputs: Manifest
    inputIdentities: dict[str, list[int]]
    pendingGeneration: dict[str, JsonObject]
    generationError: str
    pendingObserved: JsonObject
    environment: str
    directory: str
    target: Target
    gitPublication: JsonObject


class SchedulerBackend(Protocol):
    def prepare(self, unit: StackUnit, state: StackState) -> str: ...
    def execute(self, unit: StackUnit, state: StackState) -> None: ...
    def poll(self, unit: StackUnit, state: StackState) -> str: ...


CacheKey: TypeAlias = str | int | None | tuple["CacheKey", ...]


class DeliveryBoundary(TypedDict, total=False):
    exports: dict[str, AwsResponse]
    importNames: dict[str, set[str]]
    heads: dict[CacheKey, AwsResponse]
    uploaded: dict[CacheKey, JsonObject]
    kmsSelectors: dict[CacheKey, str]
    bucketDesigns: dict[CacheKey, JsonObject]
    buckets: dict[CacheKey, JsonObject]
