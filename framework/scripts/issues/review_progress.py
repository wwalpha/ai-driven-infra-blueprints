"""Bounded, resumable LLM Review of one immutable Scan; no source or report reads."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from model.sources import publication_lock
from model.validations.naming import NamingRuleIndex
from utils.file_operations import atomic_replace_file
from utils.json_format import exact, fingerprint, strict_json

from .artifact import validate_artifact
from .records import identifier
from .review import (
    assigned_diagnostics,
    diagnostic_index,
    required_text,
    review_additions,
    review_snapshot,
    reviewed_ids,
    validate_confirmations,
    validate_diagnostic_decisions,
    validate_review,
    validate_review_unverified,
)

SECTIONS = (
    "naming_context",
    "human_confirmations",
    "naming",
    "judgments",
    "diagnostics",
    "additions",
)
DEFAULT_MAX_BYTES = 32768
Json = dict[str, Any]


def external_path(root: Path, path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(root.resolve()):
        raise ValueError("Review artifacts/checkpoints must be outside the repository")
    return path


def encoded(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n"


def index_items(items: list[Json], section: str) -> dict[str, Json]:
    ids = [required_text(item, "id") for item in items]
    reviewed_ids(ids, ids, section)
    return dict(zip(ids, items, strict=True))


def accepted_results(state: Json, section: str) -> dict[str, Json]:
    return {k: r for k, r in state["results"][section].items() if r["reviewed"] is True}


class ReviewController:
    """Each operation locks, reloads, validates and atomically replaces one checkpoint."""

    def __init__(self, root: Path, artifact_path: Path, state_path: Path) -> None:
        self.root = root.resolve()
        self.path = external_path(self.root, state_path)
        self.artifact_path = external_path(self.root, artifact_path)
        if self.path == self.artifact_path:
            raise ValueError("checkpoint must differ from Scan artifact")
        raw = self.artifact_path.read_bytes()
        self._artifact_bytes = raw
        self._artifact = strict_json(raw)
        if not isinstance(self._artifact, dict):
            raise ValueError("Scan artifact must be an object")
        self._rule_index = NamingRuleIndex(self._artifact["naming_context"])
        pending_names = validate_artifact(self._artifact, rule_index=self._rule_index)
        self._verified_bytes = None
        a = self._artifact
        if a.get("root") != str(self.root):
            raise ValueError("invalid scan artifact/root")
        validate_confirmations(a["human_confirmations"], a["environment"], a["target"])
        self._identity = dict(
            scan_id=a["scan_id"],
            artifact_digest=hashlib.sha256(raw).hexdigest(),
            naming_context_id=a["naming_context_id"],
            scope={key: a[key] for key in ("environment", "target", "services")},
        )
        context = a["naming_context"]
        contexts = [
            dict(
                id=a["naming_context_id"],
                context={k: v for k, v in context.items() if k != "rules"},
            )
        ]
        for kind, rules in context.get("rules", {}).items():
            contexts.extend(
                dict(
                    id=identifier([a["naming_context_id"], kind, i]),
                    namespace=kind,
                    rule=rule,
                )
                for i, rule in enumerate(rules)
            )
        self._base = {
            "naming_context": index_items(contexts, "naming context"),
            "human_confirmations": index_items(
                a["human_confirmations"]["confirmations"], "Human confirmation"
            ),
            "naming": index_items(pending_names, "naming"),
            "judgments": index_items(a["judgments"], "judgment"),
            "additions": {
                "final": dict(
                    id="final",
                    instruction="Confirm additional Issues / Unverified are finalized; include any remaining current findings.",
                )
            },
        }
        diagnostic_index(a["ordinary"], a["services"])

    @property
    def identity(self) -> Json:
        return deepcopy(self._identity)

    @property
    def artifact(self) -> Json:
        return deepcopy(self._artifact)

    def _sections(self, state: Json) -> dict[str, dict[str, Json]]:
        results = state["results"]["judgments"]
        assignments = {
            key: result["assignment"]
            for key, result in results.items()
            if "assignment" in result
        }
        known = [item for item in self._artifact["judgments"] if item["id"] in results]
        ordinary, _ = assigned_diagnostics(
            dict(self._artifact, judgments=known), assignments
        )
        return {
            **self._base,
            "diagnostics": diagnostic_index(ordinary, self._artifact["services"]),
        }

    def _next_section(self, state: Json, sections=None) -> str | None:
        if sections is None:
            sections = self._sections(state)
        return next(
            (
                s
                for s in SECTIONS
                if set(sections[s]) - accepted_results(state, s).keys()
            ),
            None,
        )

    def _review(self, state: Json) -> Json:
        results = state["results"]
        return dict(
            scan_id=self._identity["scan_id"],
            reviewed_naming_context_id=self._identity["naming_context_id"],
            reviewed_names=list(results["naming"]),
            reviewed_judgments=list(results["judgments"]),
            reviewed_confirmations=list(results["human_confirmations"]),
            diagnostic_assignments={
                key: r["assignment"]
                for key, r in results["judgments"].items()
                if "assignment" in r
            },
            diagnostic_decisions=[
                r["decision"] for r in results["diagnostics"].values()
            ],
            issues=[
                item
                for s in SECTIONS
                for r in results[s].values()
                for item in r["issues"]
            ],
            unverified=[
                item
                for s in SECTIONS
                for r in results[s].values()
                for item in r["unverified"]
            ],
        )

    def _validate_result(self, section: str, item: Json, result: Json) -> None:
        fields = {"id", "reviewed", "reason", "evidence", "issues", "unverified"}
        if section == "judgments" and "message" in item:
            fields.add("assignment")
        if section == "diagnostics":
            fields.add("decision")
        exact(result, fields, "Review result " + item["id"])
        if result["id"] != item["id"] or result["reviewed"] is not True:
            raise ValueError("explicit reviewed=true required for " + item["id"])
        required_text(result, "reason")
        required_text(result, "evidence")
        if "assignment" in fields:
            assigned_diagnostics(
                dict(self._artifact, ordinary=[], judgments=[item]),
                {item["id"]: result["assignment"]},
            )
        if "decision" in fields:
            confirmations = self._base["human_confirmations"]
            validate_diagnostic_decisions(
                [item], [result["decision"]], confirmations, self._artifact["services"]
            )
        review_additions(self._artifact, result["issues"], self._rule_index)
        validate_review_unverified(self._artifact, result["unverified"])

    def _batch_id(self, section: str, ids: list[str]) -> str:
        return fingerprint([self._identity, section, sorted(ids)])

    def _load(self) -> Json:
        if self.artifact_path.read_bytes() != self._artifact_bytes:
            raise ValueError("Scan artifact changed during Review")
        raw = self.path.read_bytes()
        envelope = strict_json(raw)
        exact(envelope, {"schema", "state", "digest"}, "Review checkpoint")
        state = envelope["state"]
        if (
            type(envelope["schema"]) is not int
            or envelope["schema"] != 1
            or envelope["digest"] != fingerprint(state)
        ):
            raise ValueError("corrupt/unsupported Review checkpoint")
        exact(state, {"identity", "results", "pending", "complete"}, "Review state")
        if state["identity"] != self._identity:
            raise ValueError("Review checkpoint Scan/context/digest/scope mismatch")
        exact(state["results"], SECTIONS, "Review result sections")
        if any(not isinstance(r, dict) for r in state["results"].values()):
            raise ValueError("corrupt Review result index")
        if raw == self._verified_bytes:
            return state
        sections = self._sections(state)
        incomplete = False
        for section in SECTIONS:
            results = state["results"][section]
            if set(results) - sections[section].keys():
                raise ValueError("unknown Review IDs in " + section)
            for key, result in results.items():
                try:
                    # Keep final findings as a draft when dependencies need re-review.
                    draft = section == "additions" and result.get("reviewed") is False
                    self._validate_result(
                        section,
                        sections[section][key],
                        dict(result, reviewed=True) if draft else result,
                    )
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(
                        f"invalid checkpoint {section}/{key}: {error}"
                    ) from error
            if (
                incomplete
                and results
                and (section != "additions" or accepted_results(state, section))
            ):
                raise ValueError("out-of-order Review confirmation in " + section)
            incomplete = (
                incomplete
                or accepted_results(state, section).keys() != sections[section].keys()
            )
        if type(state["complete"]) is not bool or state["complete"] == incomplete:
            raise ValueError("corrupt Review completion state")
        pending = state["pending"]
        if pending is not None:
            exact(pending, {"batch_id", "section", "ids"}, "pending batch")
            section, ids = pending["section"], pending["ids"]
            if (
                section != self._next_section(state, sections)
                or not isinstance(ids, list)
                or not ids
            ):
                raise ValueError("invalid pending Review batch")
            accepted = accepted_results(state, section)
            remaining = [key for key in sections[section] if key not in accepted]
            if ids != remaining[: len(ids)] or pending["batch_id"] != self._batch_id(
                section, ids
            ):
                raise ValueError("corrupt pending Review batch IDs")
        return state

    def _write(self, state: Json, sections=None) -> None:
        state["complete"] = self._next_section(state, sections) is None
        content = encoded(dict(schema=1, state=state, digest=fingerprint(state)))
        atomic_replace_file(self.path, content, fsync=True)
        self._verified_bytes = content.encode("utf-8")

    def _status(self, state: Json, sections=None) -> Json:
        if sections is None:
            sections = self._sections(state)
        next_section = self._next_section(state, sections)
        error = None
        if next_section is None:
            try:
                validate_review(
                    self._artifact,
                    self._review(state),
                    naming_ids=self._base["naming"],
                    rule_index=self._rule_index,
                )
            except (ValueError, KeyError, TypeError) as failure:
                error = str(failure)
        return dict(
            scan_id=self._identity["scan_id"],
            automatically_reviewed_names=len(self._artifact["naming"]["names"])
            - len(self._base["naming"]),
            scope=deepcopy(self._identity["scope"]),
            sections={
                s: dict(
                    total=len(sections[s]),
                    reviewed=len(accepted_results(state, s)),
                    remaining=len(sections[s]) - len(accepted_results(state, s)),
                    pending_dependency=s == "diagnostics"
                    and set(self._base["judgments"])
                    != state["results"]["judgments"].keys(),
                )
                for s in SECTIONS
            },
            next_section=next_section,
            complete=next_section is None and error is None,
            exportable=next_section is None and error is None,
            **({"validation_error": error} if error else {}),
        )

    def initialize(self) -> Json:
        # Use the existing OS/process + thread mutex with a per-checkpoint namespace.
        with publication_lock(self.path, read_only=True):
            if self.path.exists():
                state = self._load()
            else:
                if self.artifact_path.read_bytes() != self._artifact_bytes:
                    raise ValueError("Scan artifact changed during Review")
                state = dict(
                    identity=self._identity,
                    results={s: {} for s in SECTIONS},
                    pending=None,
                    complete=False,
                )
                self._write(state)
            return self._status(state)

    def status(self) -> Json:
        with publication_lock(self.path, read_only=True):
            return self._status(self._load())

    def _material(self, section: str, item: Json) -> Json:
        a = self._artifact
        material = dict(item=item)
        if section in {"naming", "judgments", "diagnostics"}:
            material["human_confirmations"] = [
                h
                for h in self._base["human_confirmations"].values()
                if (item.get("service") is None or h["service"] == item["service"])
                and (
                    h["scope"] == {k: item.get(k) for k in ("resource", "property")}
                    or any(e["diagnostic_id"] == item["id"] for e in h["exceptions"])
                )
            ]
            material["reviewed_human_context"] = dict(
                artifact=str(self.artifact_path),
                section="human_confirmations",
                service=item.get("service"),
                detail="detail --section human_confirmations --offset 0 --limit 20",
            )
        if section == "naming":
            kind = item["resourceType"].partition(".")[0]
            material["naming_rule_refs"] = [
                k for k in a["naming_context"].get("rules", {}) if k in {"common", kind}
            ]
        if section == "judgments":
            material["selected_services"] = a["services"]
        return material

    def next_batch(self, limit: int = 20, max_bytes: int = DEFAULT_MAX_BYTES) -> Json:
        if limit < 1 or max_bytes < 256:
            raise ValueError("Review limit must be positive and max_bytes at least 256")
        with publication_lock(self.path, read_only=True):
            state = self._load()
            sections = self._sections(state)
            section = self._next_section(state, sections)
            if section is None:
                return self._status(state)
            accepted = accepted_results(state, section)
            remaining = [key for key in sections[section] if key not in accepted]
            items: list[Json] = []
            output: Json = {}
            ids: list[str] = []
            for key in remaining[:limit]:
                material = self._material(section, sections[section][key])
                if section == "additions" and key in state["results"][section]:
                    material["previous_result"] = state["results"][section][key]
                candidate_ids = [*ids, key]
                candidate = dict(
                    scan_id=self._identity["scan_id"],
                    section=section,
                    batch_id=self._batch_id(section, candidate_ids),
                    expected_ids=candidate_ids,
                    items=[*items, material],
                )
                if section == "naming":
                    kinds = {
                        ref for m in candidate["items"] for ref in m["naming_rule_refs"]
                    }
                    context = self._artifact["naming_context"]
                    candidate["naming_context"] = {
                        **context,
                        "rules": {
                            k: v
                            for k, v in context.get("rules", {}).items()
                            if k in kinds
                        },
                    }
                size = len(encoded(candidate).encode("utf-8"))
                if size > max_bytes:
                    if not items:
                        return dict(
                            blocked=True,
                            section=section,
                            id=key,
                            reason="one complete Review item exceeds max_bytes; remains unreviewed",
                            required_bytes=size,
                            max_bytes=max_bytes,
                        )
                    break
                ids, items, output = candidate_ids, candidate["items"], candidate
            state["pending"] = dict(
                batch_id=output["batch_id"], section=section, ids=ids
            )
            self._write(state, sections)
            return deepcopy(output)

    def submit(self, submission: Json) -> Json:
        exact(submission, {"batch_id", "section", "results"}, "Review submission")
        section = submission["section"]
        if section not in SECTIONS or not isinstance(submission["results"], list):
            raise ValueError("invalid Review section/results")
        results = index_items(submission["results"], "batch")
        ids = list(results)
        if not ids or submission["batch_id"] != self._batch_id(section, ids):
            raise ValueError("Review Batch ID/target IDs mismatch")
        with publication_lock(self.path, read_only=True):
            state = self._load()
            accepted = accepted_results(state, section)
            if any(key in accepted for key in ids):
                if all(
                    key in accepted and accepted[key] == result
                    for key, result in results.items()
                ):
                    return self._status(state)
                raise ValueError("Review conflict: implicit overwrite prohibited")
            pending = state["pending"]
            if (
                pending is None
                or pending["batch_id"] != submission["batch_id"]
                or pending["section"] != section
                or set(pending["ids"]) != set(ids)
            ):
                raise ValueError("Review Batch not issued or incomplete/stale IDs")
            results = {key: results[key] for key in pending["ids"]}
            sections = self._sections(state)
            for key, result in results.items():
                try:
                    self._validate_result(section, sections[section][key], result)
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(
                        f"invalid Review {section}/{key}: {error}"
                    ) from error
            candidate = dict(state, results=dict(state["results"]))
            candidate["results"][section] = dict(
                state["results"][section], **deepcopy(results)
            )
            candidate["pending"] = None
            candidate_sections = (
                self._sections(candidate) if section == "judgments" else sections
            )
            self._validate_candidate(candidate, candidate_sections)
            self._write(candidate, candidate_sections)
            return self._status(candidate, candidate_sections)

    def _validate_candidate(self, state: Json, sections=None) -> None:
        if sections is None:
            sections = self._sections(state)
        review = self._review(state)
        additions = review_additions(self._artifact, review["issues"], self._rule_index)
        ordinary = list(sections["diagnostics"].values())
        diagnostic_index([*ordinary, *additions], self._artifact["services"])
        if self._next_section(state, sections) is None:
            validate_review(
                self._artifact,
                review,
                naming_ids=self._base["naming"],
                rule_index=self._rule_index,
            )

    def inspect(self, section: str, key: str) -> Json:
        with publication_lock(self.path, read_only=True):
            state = self._load()
            if section not in SECTIONS or key not in state["results"][section]:
                raise ValueError("unknown recorded Review section/ID")
            result = state["results"][section][key]
            return dict(
                scan_id=self._identity["scan_id"],
                section=section,
                id=key,
                result=result,
                result_digest=fingerprint(result),
            )

    def revise(self, revision: Json) -> Json:
        exact(
            revision,
            {"scan_id", "section", "id", "expected_digest", "reason", "result"},
            "Review revision",
        )
        required_text(revision, "reason")
        digest = required_text(revision, "expected_digest")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("invalid expected Review result digest")
        section, key = required_text(revision, "section"), required_text(revision, "id")
        with publication_lock(self.path, read_only=True):
            state = self._load()
            if revision["scan_id"] != self._identity["scan_id"]:
                raise ValueError("Review revision Scan mismatch")
            if section not in SECTIONS or key not in accepted_results(state, section):
                raise ValueError("revision requires an accepted section/ID")
            current, result = state["results"][section][key], revision["result"]
            self._validate_result(section, self._sections(state)[section][key], result)
            if current == result:
                return self._status(state)
            if fingerprint(current) != digest:
                raise ValueError(
                    "Review revision conflict: expected result digest differs"
                )
            candidate = deepcopy(state)
            candidate["results"][section][key] = deepcopy(result)
            before = self._sections(state)["diagnostics"]
            after = self._sections(candidate)["diagnostics"]
            for diagnostic_id in list(candidate["results"]["diagnostics"]):
                old, new = before[diagnostic_id], after.get(diagnostic_id)
                if new is None or dict(old, assignment=None) != dict(
                    new, assignment=None
                ):
                    del candidate["results"]["diagnostics"][diagnostic_id]
            if section != "additions" and candidate["results"]["additions"]:
                candidate["results"]["additions"]["final"]["reviewed"] = False
            candidate["pending"] = None
            sections = self._sections(candidate)
            for name in SECTIONS:
                for result_id, retained in candidate["results"][name].items():
                    self._validate_result(
                        name,
                        sections[name][result_id],
                        dict(retained, reviewed=True)
                        if name == "additions"
                        else retained,
                    )
            self._validate_candidate(candidate, sections)
            self._write(candidate, sections)
            return self._status(candidate, sections)

    def export(self, path: Path) -> Json:
        path = external_path(self.root, path)
        if path in {self.path, self.artifact_path}:
            raise ValueError("Review export must differ from checkpoint/Scan")
        with publication_lock(self.path, read_only=True):
            state = self._load()
            if self._next_section(state) is not None:
                raise ValueError(
                    "incomplete Review; remaining IDs: "
                    + encoded(self._status(state)).strip()
                )
            review = self._review(state)
            validate_artifact(self._artifact)
            review_snapshot(self._artifact, review)
            atomic_replace_file(path, encoded(review), fsync=True)
            return dict(
                scan_id=self._identity["scan_id"], review=str(path), complete=True
            )
