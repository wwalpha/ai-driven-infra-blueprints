"""Runtime source embedded into each generated file; requires only Python stdlib."""

import argparse
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from functools import partial as _bind_framework_callback
from functools import partialmethod
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _callback_engine_load_model(m, snapshot, /, path):
    address = path.relative_to(m.ROOT / "model").with_suffix("").as_posix()
    if address not in snapshot["models"]:
        raise m.Unresolved("producer Design is absent from audit snapshot: " + address)
    values = snapshot["models"][address]
    return SimpleNamespace(
        values=values,
        locations={key: (Path("embedded") / path.name, 0) for key in values},
    )


def _callback_engine_resolve_json(self, m, original_resolve, /, value, norm="typed"):
    if m.is_reference(value):
        raise m.Unresolved(
            "Design reference unresolved: missing generated row resolution"
        )
    if isinstance(value, dict) and "Fn::GetAtt" in value:
        item = value["Fn::GetAtt"]
        attribute = (
            item[1]
            if isinstance(item, list) and len(item) == 2
            else item.partition(".")[2]
            if isinstance(item, str)
            else None
        )
        if len(value) != 1 or attribute != "Arn":
            raise m.Unresolved(
                "unsupported GetAtt attribute; only Arn has a confirmed identity mapping"
            )
    return original_resolve(self, value, norm)


def contains_reference(value):
    if isinstance(value, dict):
        return "$modelRef" in value or any(
            contains_reference(v) for v in value.values()
        )
    if isinstance(value, list):
        return any(contains_reference(v) for v in value)
    if isinstance(value, str) and value.strip("`").lstrip().startswith(("{", "[")):
        try:
            return contains_reference(json.loads(value.strip("`")))
        except ValueError:
            return False
    return False


def row_resolution(snapshot, resource, row):
    address = (
        resource.model.path.relative_to(resource.ctx.root / "model")
        .with_suffix("")
        .as_posix()
    )
    return snapshot["referenceRows"].get(address, {}).get(row.get("auditRowId"))


def resolution_error(resolved):
    if resolved["status"] != "resolved":
        return resolved["reason"] or resolved["status"]
    if contains_reference(resolved["value"]):
        return "generated value still contains a Design reference"
    return None


def _callback_engine_resource_init(self, original_init, /, *args):
    original_init(self, *args)
    self.rows = [(rid, {**row, "auditRowId": rid}) for rid, row in self.rows]


def validate_design_value(m, snapshot, row, value):
    schema = snapshot["schemas"].get(row["property"])
    if schema:
        values = m.normalize_literals(row["property"], value, m.value_shape(row)).values
        for element in values:
            errors = m.native_type_errors(schema, element)
            if errors:
                raise m.Unresolved("candidate Property " + errors[0])


def _callback_engine_parse(self, snapshot, m, original_parse, /, row, norm="typed"):
    resolved = row_resolution(snapshot, self, row)
    if resolved is not None:
        reason = resolution_error(resolved)
        if reason:
            raise m.Unresolved("Design reference unresolved: " + reason)
        value = resolved["value"]
        materialized = dict(row)
        validate_design_value(m, snapshot, row, value)
        if "document" in row:
            materialized["document"] = json.dumps(value, ensure_ascii=False)
        else:
            raw = (
                value
                if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False)
            )
            materialized["value"] = "`" + raw + "`"
    elif contains_reference(row.get("document", row["value"])):
        raise m.Unresolved(
            "Design reference unresolved: missing generated row resolution"
        )
    else:
        materialized = row
    parsed = original_parse(self, materialized, norm)
    validate_design_value(m, snapshot, row, parsed)
    return parsed


def _callback_engine_reference(self, m, snapshot, /, value):
    node = m.parse_model_reference(value)
    address = self.model.path.relative_to(m.ROOT / "model").parts[:2]
    matches = [
        resource
        for name in snapshot["models"]
        if Path(name).parts[:2] == address
        for resource in self.ctx.model(
            m.ROOT / "model" / (name + ".properties")
        ).resources
        if resource.spec["logicalId"] == node.logical_id
    ]
    if len(matches) != 1:
        raise m.Unresolved("Design reference has no unique producer in audit snapshot")
    return matches[0]


def engine(snapshot):
    """Bind copied comparison code to immutable, embedded Model/Mapping inputs."""
    m = ModuleType("audit_comparison")
    sys.modules[m.__name__] = m
    exec(compile(snapshot["engine"], "<existing-comparator>", "exec"), m.__dict__)
    m._imports_iac_values = m
    m.SERVICES = tuple(snapshot["adapters"])
    adapters = {}
    for name, source in snapshot["adapters"].items():
        adapter = ModuleType("audit_" + name.replace("-", "_"))
        adapter.__dict__["_audit_comparison"] = m
        exec(compile(source, "<adapter:" + name + ">", "exec"), adapter.__dict__)
        adapters[name] = adapter
    m.service_module = adapters.__getitem__
    m.model_paths = lambda root, environment, directory: [
        root / "model" / (name + ".properties")
        for name in snapshot["models"]
        if name.rsplit("/", 1)[0] == environment + "/" + directory
    ]

    load_model = _bind_framework_callback(_callback_engine_load_model, m, snapshot)

    original_resolve = m.Resource.resolve_json
    m.Resource.resolve_json = partialmethod(
        _callback_engine_resolve_json, m, original_resolve
    )
    m.Resource.__init__ = partialmethod(
        _callback_engine_resource_init, m.Resource.__init__
    )
    m.Resource.reference = partialmethod(_callback_engine_reference, m, snapshot)
    m.Resource.parse = partialmethod(
        _callback_engine_parse, snapshot, m, m.Resource.parse
    )
    m.load_model = load_model
    m.DesignSchemaCatalog = lambda root: SimpleNamespace(
        property_schema=lambda kind, path: snapshot["schemas"][kind + "." + path]
    )
    m.catalog_outputs = lambda root, kind: snapshot["outputs"].get(kind, [])
    mappings = {}
    for name, data in snapshot["mappings"].items():
        props = {
            key: SimpleNamespace(**{**prop, "field": m.Field(**prop["field"])})
            for key, prop in data["properties"].items()
        }
        mapping = SimpleNamespace(
            getters=data["getters"],
            identities={
                key: SimpleNamespace(**value)
                for key, value in data["identities"].items()
            },
        )
        mappings[name] = (mapping, props)
    m.Context.comparison = lambda self, service: mappings[service]
    projection = ModuleType("audit_projection")
    projection.module = lambda *args: m
    exec(
        compile(snapshot["projection"], "<existing-mapping-projection>", "exec"),
        projection.__dict__,
    )
    mapped = ModuleType("aws_mapping_compare")
    mapped.select, mapped.module, mapped.project = (
        m.select,
        projection.module,
        projection.project,
    )
    exec(
        compile(snapshot["mapped"], "<existing-mapping-value>", "exec"), mapped.__dict__
    )
    sys.modules[mapped.__name__] = mapped
    m._imports_aws_mapping_compare = mapped
    return m


def reference_result(m, snapshot, resource, item):
    rows = resource.rows_for(item["propertiesKey"])
    resolutions = [row_resolution(snapshot, resource, row) for _, row in rows]
    if not any(resolutions) and not any(
        contains_reference(row.get("document", row["value"])) for _, row in rows
    ):
        return item
    reasons = list(
        dict.fromkeys(
            resolution_error(resolved)
            if resolved
            else "missing generated row resolution"
            for (_, row), resolved in zip(rows, resolutions, strict=True)
            if resolved
            and resolution_error(resolved)
            or resolved is None
            and contains_reference(row.get("document", row["value"]))
        )
    )
    if reasons:
        reason = "Design reference unresolved: " + "; ".join(reasons)
        if item.get("reason") and reason not in item["reason"]:
            reason += "; " + item["reason"]
        return {
            **item,
            "status": item["status"]
            if item["status"] in {"resource_missing", "acquisition_failed"}
            else "design_unresolved",
            "designValue": None,
            "reason": reason,
        }
    if item["status"] in {"match", "difference"}:
        return item
    # Acquisition failed before parsing: display fixed values without another AWS call.
    expected = {}
    prop = item["propertiesKey"]
    try:
        for (_, row), resolved in zip(rows, resolutions, strict=True):
            value = (
                resolved["value"]
                if resolved
                else m.typed_value(row, row["value"], snapshot["schemas"].get(prop, {}))
            )
            validate_design_value(m, snapshot, row, value)
            (m.project if m.value_shape(row) == "projection" else m.put_row)(
                expected, prop, value
            )
        value = m.select(m.canonical(expected), prop)
    except (m.Unresolved, ValueError, TypeError, KeyError) as error:
        return {
            **item,
            "status": item["status"]
            if item["status"] in {"resource_missing", "acquisition_failed"}
            else "design_unresolved",
            "designValue": None,
            "reason": "Design reference projection failed: "
            + str(error)
            + "; "
            + item.get("reason", ""),
        }
    return {
        **item,
        "designValue": "[REDACTED]"
        if resource.module.sensitive(prop)
        else m.redacted(value),
    }


SENSITIVE = re.compile(
    r"password|secret|token|credential|privatekey|accesskey|authorization", re.I
)


def masked(value, key=""):
    if SENSITIVE.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: masked(v, k) for k, v in value.items()}
    if isinstance(value, list):
        # Tag/variable maps store sensitive names in Key/Name, outside the Value key.
        return [
            (
                "[REDACTED]"
                if isinstance(v, dict)
                and SENSITIVE.search(str(v.get("Key", v.get("Name", ""))))
                else masked(v)
            )
            for v in value
        ]
    if isinstance(value, str):
        if "{{resolve:" in value:
            return "[REDACTED]"
        raw = value.strip("`")
        if raw.startswith(("{", "[")):
            try:
                return masked(json.loads(raw))
            except ValueError:
                pass
    return value


def different_paths(left, right, path="$"):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        return [
            p
            for key in sorted(left.keys() | right.keys())
            for p in (
                [path + "." + key]
                if key not in left or key not in right
                else different_paths(left[key], right[key], path + "." + key)
            )
        ]
    if isinstance(left, list):
        return [
            p
            for index in range(max(len(left), len(right)))
            for p in (
                [f"{path}[{index}]"]
                if index >= len(left) or index >= len(right)
                else different_paths(left[index], right[index], f"{path}[{index}]")
            )
        ]
    return [] if left == right else [path]


def attributes(result):
    """Existing acquisition diagnostics group failures; audit rows remain independent."""
    for item in result:
        if item.get("affectedKeys"):
            for prop in item["affectedKeys"]:
                yield {
                    **item,
                    "propertiesKey": prop,
                    "designValue": item.get("designValues", {}).get(prop),
                }
        else:
            yield item


def observed_identifier(raw, literal, confirmed_display_name, confirmed):
    if not isinstance(raw, str) or not confirmed_display_name(raw):
        return None
    value = literal(raw).strip()
    if value.startswith(("[", "{")):
        return None
    try:
        return value if confirmed(value) else None
    except ValueError:
        return None


def identifier_result(m, ctx, resource, item):
    if item["propertiesKey"] not in m.catalog_outputs(m.ROOT, resource.kind):
        return item
    rows = resource.rows_for(item["propertiesKey"])
    if len(rows) != 1:
        return {
            **item,
            "status": "design_unresolved"
            if item["status"] == "identifier"
            else item["status"],
            "designValue": None,
            "reason": "observed identifier is ambiguous"
            if item["status"] == "identifier"
            else item.get("reason", item["status"]),
        }
    rid, row = rows[0]
    raw = resource.model.values.get("observed.row." + rid + ".value")
    if not isinstance(raw, str) or not raw.strip():
        return {
            **item,
            "status": "design_unresolved"
            if item["status"] == "identifier"
            else item["status"],
            "designValue": None,
            "reason": "observed identifier is missing"
            if item["status"] == "identifier"
            else item.get("reason", item["status"]),
        }
    value = observed_identifier(raw, m.literal, m.confirmed_display_name, m.confirmed)
    if value is None:
        return {
            **item,
            "status": "design_unresolved"
            if item["status"] == "identifier"
            else item["status"],
            "designValue": None,
            "reason": "observed identifier is unresolved or invalid"
            if item["status"] == "identifier"
            else item.get("reason", item["status"]),
        }
    if item["status"] != "identifier":
        return {
            **item,
            "designValue": "[REDACTED]"
            if resource.module.sensitive(item["propertiesKey"])
            else m.redacted(value),
        }
    field = ctx.comparison(resource.model.service)[1][item["propertiesKey"]].field
    try:
        observed_row = {**row, "value": raw}
        observed_row.pop("document", None)
        observed_row.pop("auditRowId", None)
        expected = m.normalize(
            ctx, resource.parse(observed_row, field.norm), field.norm
        )
        actual = m.normalize(ctx, item["awsValue"], field.norm)
        if (
            isinstance(expected, (list, dict))
            or isinstance(actual, (list, dict))
            or actual is None
        ):
            raise ValueError("identifier is not scalar")
        matches = m.stable(expected) == m.stable(actual)
        return {
            **item,
            "status": "match" if matches else "difference",
            "designValue": "[REDACTED]"
            if resource.module.sensitive(item["propertiesKey"])
            else m.redacted(expected),
            "awsValue": "[REDACTED]"
            if resource.module.sensitive(item["propertiesKey"])
            else m.redacted(actual),
            "reason": "" if matches else "value differs",
        }
    except (m.AcquisitionError, m.Unresolved, ValueError, TypeError, KeyError):
        return {
            **item,
            "status": "design_unresolved",
            "designValue": None,
            "reason": "identifier comparison could not be resolved",
        }


def audit(snapshot, profile=None, cli_runner=None):
    m = engine(snapshot)
    target = dict(snapshot["target"])
    ctx = None
    account, records = "unverified", []
    try:
        selected = m.select_profile(target, profile)
        if selected is not None:
            target["awsProfile"] = selected
        ctx = m.Context(m.ROOT, target, cli_runner=cli_runner)
        account = ctx.verify()
    except Exception as error:
        reason = (
            error.code
            if isinstance(error, (m.AcquisitionError, m.IdentityError))
            else str(error)
            if isinstance(error, (m.Unresolved, ValueError))
            else type(error).__name__
        )
        if ctx is None:
            ctx = m.Context(m.ROOT, snapshot["target"], cli_runner=cli_runner)
        # Account/credential failure stops all resource APIs, but records every attribute.
        model = ctx.model(
            m.ROOT
            / "model"
            / target["environment"]
            / target["directory"]
            / (snapshot["service"] + ".properties")
        )
        for resource in model.resources:
            for prop in dict.fromkeys(row["property"] for _, row in resource.rows):
                records.append(
                    reference_result(
                        m,
                        snapshot,
                        resource,
                        identifier_result(
                            m,
                            ctx,
                            resource,
                            {
                                "resource": resource.spec["logicalId"],
                                "propertiesKey": prop,
                                "status": "acquisition_failed",
                                "reason": reason,
                                "designValue": [
                                    row.get("document", row["value"])
                                    for _, row in resource.rows
                                    if row["property"] == prop
                                ],
                                "awsValue": None,
                                "apis": ctx.trace,
                            },
                        ),
                    )
                )
        return m, account, records
    model = ctx.model(
        m.ROOT
        / "model"
        / target["environment"]
        / target["directory"]
        / (snapshot["service"] + ".properties")
    )
    for resource in model.resources:
        try:
            records.extend(
                reference_result(
                    m, snapshot, resource, identifier_result(m, ctx, resource, item)
                )
                for item in attributes(m.compare_resource(ctx, resource))
            )
        except Exception as error:
            # Never turn a new upstream dependency or malformed response into a silent skip.
            for prop in dict.fromkeys(row["property"] for _, row in resource.rows):
                records.append(
                    reference_result(
                        m,
                        snapshot,
                        resource,
                        identifier_result(
                            m,
                            ctx,
                            resource,
                            {
                                "resource": resource.spec["logicalId"],
                                "propertiesKey": prop,
                                "status": "design_unresolved",
                                "reason": "comparison failed: " + type(error).__name__,
                                "designValue": [
                                    row.get("document", row["value"])
                                    for _, row in resource.rows
                                    if row["property"] == prop
                                ],
                                "awsValue": None,
                                "apis": ctx.trace,
                            },
                        ),
                    )
                )
    return m, account, records


def _callback_report_line(output, /, value=""):
    print(value, file=output)


def report(snapshot, profile, account, records, timestamp):
    output = io.StringIO()
    line = _bind_framework_callback(_callback_report_line, output)
    target = snapshot["target"]
    line("Executed: " + timestamp.isoformat())
    for label, value in [
        ("Environment", target["environment"]),
        ("Alias", target["directory"]),
        ("Service", snapshot["service"]),
        ("Profile", profile or "(default credential chain)"),
        ("Region", target["awsRegion"]),
        ("Account", account),
        ("Design SHA256", snapshot["modelHash"]),
    ]:
        line(f"{label}: {value}")
    line()
    counts = Counter()
    for item in records:
        state = {"match": "OK", "difference": "NG"}.get(item["status"], "ERROR")
        counts[state] += 1
        prop = item.get("propertiesKey") or "(resource)"
        kind = item.get("resourceType") or ".".join(prop.split(".")[:2])
        name = snapshot.get("names", {}).get(item["resource"], "（名前未設定）")
        attribute = prop.removeprefix(kind + ".")
        line(f"[{state}] {kind} | {name} | {attribute}")
        expected = masked(item.get("designValue"), prop)
        actual = masked(item.get("awsValue"), prop)
        line("  Design: " + json.dumps(expected, ensure_ascii=False, sort_keys=True))
        line("  AWS:    " + json.dumps(actual, ensure_ascii=False, sort_keys=True))
        if state != "OK":
            line(
                "  Reason: "
                + item.get(
                    "reason", "value differs" if state == "NG" else item["status"]
                )
                .replace("Model reference", "Design reference")
                .replace("producer Model is absent", "producer Design is absent")
            )
        if state == "NG":
            line(
                "  Diff paths: "
                + ", ".join(
                    different_paths(expected, actual) or ["$ (redacted values differ)"]
                )
            )
        line()
    if not records:
        counts["ERROR"] += 1
        line("[ERROR] No selected desired attributes")
    line("--------------------------------")
    line(f"Total: {sum(counts.values())}")
    for state in ("OK", "NG", "ERROR"):
        line(f"{state}: {counts[state]}")
    code = 2 if counts["ERROR"] else 1 if counts["NG"] else 0
    line("Result: " + ("FAIL" if code else "PASS"))
    return output.getvalue(), code


def main(argv=None, cli_runner=None, script_path=None):
    SNAPSHOT = globals()["SNAPSHOT"]
    parser = argparse.ArgumentParser(
        description="Read-only audit against embedded Design expectations"
    )
    parser.add_argument("--profile")
    args = parser.parse_args(argv)
    timestamp = datetime.now().astimezone()
    target = SNAPSHOT["target"]
    script = Path(script_path or __file__).resolve()
    # tests/<environment>/<alias>/<service>.py -> tests/results/<environment>/<alias>/
    layout = ("tests", target["environment"], target["directory"])
    tests = (
        script.parents[2]
        if script.parent.parts[-3:] == layout
        else Path.cwd() / "tests"
    )
    directory = tests / "results" / target["environment"] / target["directory"]
    try:
        directory.mkdir(parents=True, exist_ok=True)
        filename = SNAPSHOT["service"] + "-" + timestamp.strftime("%Y%m%d-%H%M%S")
        path = directory / (filename + ".log")
        try:
            handle = path.open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            handle = (directory / (filename + timestamp.strftime("-%f") + ".log")).open(
                "x", encoding="utf-8", newline="\n"
            )
        with handle:
            _, account, records = audit(SNAPSHOT, args.profile, cli_runner)
            text, code = report(
                SNAPSHOT,
                args.profile or target.get("awsProfile"),
                account,
                records,
                timestamp,
            )
            handle.write(text)
            handle.flush()
            sys.stdout.write(text)
        return code
    except OSError as error:
        print("[ERROR] audit log unavailable: " + type(error).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
