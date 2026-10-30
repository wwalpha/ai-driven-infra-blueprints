"""Tracked, lazy input session for local comparison and bounded repair evaluation."""

from __future__ import annotations

import hashlib
import re
from functools import partial

import design.array_display as _imports_array_display
import model.environment_values as environment_values
import model.identity as _imports_model_identity
import model.sources as _imports_model_sources
import utils.cloudformation.format as _imports_cfn_format
from design.catalog import DesignSchemaCatalog
from design.layout import resource_mode
from design.policy_tables import literal
from iac_evaluation import RETURN_ATTRIBUTE_PROPERTIES
from model.adapters.observed import mapped_resource, resource_index
from model.core import ReferenceResolutionError, entries, stack_model
from model.files import load_model, resource_row_index
from model.identity import anchor_index, parse_reference, select_anchor
from model.literal_values import value_shape
from model.projection import reference_attribute
from model.sources import _invocation_reads, model_exists, model_paths
from task_contract_core import task_reads
from utils.arn_values import context_value, named_arn
from utils.aws_catalogs import catalog_outputs
from utils.aws_sdk import aws_runtime
from utils.cloudformation.inputs import (
    Blocked,
    condition_active,
    load_template_inputs,
)
from utils.comparison_rows import MISSING, select
from utils.iac_values import Expression, ResourceReference, cfn_resource_identity, same
from utils.json_format import policy_json as strict_json
from utils.project_targets import load_target_directory as load_target
from utils.reference_contracts import (
    ARN_SHAPES,
    ATTRIBUTE_SUFFIXES,
    REF_ATTRIBUTES,
    REFERENCE_PROPERTIES,
    getatt_attribute,
    row_contexts,
)

from . import (
    arn_projection,
    design_link,
    evaluation,
    model_reference,
    reference_evidence,
    references,
    registry,
    values,
)
from .deferral import defer_import_reference
from .result import redacted
from .rules.kms import kms_format


class Inputs:
    def __init__(self, root, environment, directory, services, *, catalog=None):
        with task_reads(_imports_model_sources.project_root(root)):
            self._initialize(root, environment, directory, services, catalog=catalog)

    def _initialize(self, root, environment, directory, services, *, catalog=None):
        self.root, self.environment, self.directory = root, environment, directory
        self.services = sorted(set(services))
        self.target = load_target(root, environment, directory, include_naming=True)
        self.catalog = catalog or DesignSchemaCatalog(root)
        self.models, self.rows, self.resources = {}, {}, {}
        self.documents, self.stack_inputs = {}, {}
        self.template_locations = {}
        self._index, self.symbols = None, {}
        self.local_comparison, self.reference_models_loaded = False, False
        self.exports = None
        self.model_references = {}
        self.export_provenance = {}
        self.select_provenance = {}
        self.export_failures, self.stack_errors = [], {}
        self._templates, self.reference_formats = None, {}
        self.read_hashes, self.sensitive_values = {}, set()
        self.model_reads = _invocation_reads(root)
        self.unreadable_inputs = False
        self.view_errors = {}
        self.load_errors, self.warnings = [], []
        self.reference_unavailable = {}
        self.inputs = {root / "project.json"}
        self.metrics = {
            "model_loads": 0,
            "model_parses": 0,
            "template_decodes": 0,
            "stack_evaluations": 0,
        }
        for service in self.services:
            try:
                self.model(service)
            except ReferenceResolutionError as error:
                self.warnings.append({**error.diagnostic, "service": service})
                self.reference_unavailable[service] = str(error)
                load_source = _imports_model_sources.load_model
                try:
                    analysis = load_source(
                        root
                        / "model"
                        / environment
                        / directory
                        / (service + ".properties"),
                        self.model_reads,
                    )
                    self.inputs.update(analysis.files)
                    self.warnings.extend(analysis.warnings)
                finally:
                    self.retain_reads()
                self.resources[service], self.rows[service] = {}, {}
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.load_errors.append((service, str(error)))
                self.resources[service], self.rows[service] = {}, {}

    def retain_reads(self):
        observed = getattr(self, "model_observations", {})
        self.model_observations = observed
        for file in self.model_reads.contents.keys() - observed:
            raw = self.model_reads.contents[file]
            if file.is_relative_to(self.root):
                self.retain_hash(
                    file, None if raw is None else hashlib.sha256(raw).hexdigest()
                )
            observed[file] = raw

    def retain_model_dependencies(self, dependencies):
        observed = self.model_observations
        for file, raw in dependencies.items():
            value = (
                self.read_hashes[file]
                if file in observed and observed[file] == raw
                else None
                if raw is None
                else hashlib.sha256(raw).hexdigest()
            )
            self.retain_hash(file, value)

    def retain_hash(self, path, value):
        self.inputs.add(path)
        if self.read_hashes.setdefault(path, value) != value:
            self.stale_inputs = True
            raise ValueError(
                "stale scan: contradictory input observations: "
                + path.relative_to(self.root).as_posix()
            )

    def model(self, service):
        if not re.fullmatch(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", service):
            raise ValueError("invalid reference service")
        if service not in self.models:
            path = (
                self.root
                / "model"
                / self.environment
                / self.directory
                / (service + ".properties")
            )
            # Discovery must precede any parsing failure; never take a later repair as baseline.
            self.model_reads.select(path.with_suffix(""), "*", recursive=True)
            try:
                loaded = load_model(path, self.model_reads)
            except OSError as error:
                if not isinstance(error, FileNotFoundError):
                    self.unreadable_inputs = True
                raise
            finally:
                self.retain_reads()
            self.retain_model_dependencies(loaded.dependencies)
            self.warnings.extend(getattr(loaded, "warnings", ()))
            if (
                service != "cloudformation-stacks"
                and loaded.values.get(f"desired.service.{service}.serviceId") != service
            ):
                raise ValueError(f"mismatched service ID: {path}")
            self.models[service] = loaded
            self._index = None
            self.symbols.clear()
            self.metrics["model_loads"] += 1
            self.metrics["model_parses"] += 1
            self.resources[service] = dict(entries(loaded.values, "desired.resource."))
            self.rows[service] = resource_row_index(loaded.values)
            for rows in self.rows[service].values():
                for _, row in rows:
                    if re.search(
                        r"password|secretstring|secretbinary|token|credential|privatekey",
                        ".".join(row.get("property", "").split(".")[2:]),
                        re.I,
                    ):
                        raw = row.get("document", row.get("value", ""))
                        self.sensitive_values.update((raw, literal(raw)))
        return self.models[service]

    def source(self, service, key):
        location = (
            self.models[service].locations.get(key) if service in self.models else None
        )
        return (
            {
                "path": location[0].relative_to(self.root).as_posix(),
                "line": location[1],
                "key": key,
            }
            if location
            else None
        )

    def track(self, path):
        if path in self.read_hashes:
            return
        try:
            value = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            value = None
        except OSError:
            self.unreadable_inputs = True
            raise
        self.retain_hash(path, value)

    def index(self):
        if self._index is None:
            loaded = {
                self.root
                / "model"
                / self.environment
                / self.directory
                / (service + ".properties"): model.values
                for service, model in self.models.items()
                if service != "cloudformation-stacks"
            }
            self._index = resource_index(loaded, self.catalog)
        return self._index

    def templates(self):
        if self._templates is not None:
            return self._templates
        stackpath = (
            self.root
            / "model"
            / self.environment
            / self.directory
            / "cloudformation-stacks.properties"
        )
        self.model_reads.select(stackpath.with_suffix(""), "*", recursive=True)
        try:
            if not model_exists(stackpath, self.model_reads):
                self._templates = []
                return self._templates
        finally:
            self.retain_reads()
        _, stacks = stack_model(self.model("cloudformation-stacks").values)
        self._templates = stacks
        return self._templates

    def stack(self, unit):
        name = unit["name"]
        if name in self.stack_errors:
            raise self.stack_errors[name].with_traceback(None)
        try:
            return self.stack_input(unit)
        except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
            self.stack_errors[name] = error
            raise

    def stack_input(self, unit):
        name = unit["name"]
        template = (
            self.root
            / "infra/cloudformation/templates"
            / self.target.get("alias", "")
            / unit["template"]
        )
        parameters_path = (
            self.root
            / "infra/cloudformation/parameters"
            / self.environment
            / self.directory
            / unit["parameters"]
        )
        self.track(template)
        self.track(parameters_path)
        if name in self.stack_inputs:
            return template, self.stack_inputs[name]
        for path in (template, parameters_path):
            if not path.is_file():
                blocked = Blocked(
                    f"stack input missing: {path.relative_to(self.root).as_posix()}"
                )
                blocked.iac_cause = {
                    "kind": "template-missing"
                    if path == template
                    else "parameters-missing",
                    "path": path.relative_to(self.root).as_posix(),
                    "stack": name,
                    "relationship": "stack-input",
                }
                raise blocked
        if template not in self.documents:
            decode_file = _imports_cfn_format.decode_file
            document, errors = decode_file(template, locations=self.template_locations)
            self.metrics["template_decodes"] += 1
            if errors or not isinstance(document, dict):
                raise ValueError(f"invalid template: {template}")
            self.documents[template] = document
        document = self.documents[template]
        _, values = load_template_inputs(
            template, parameters_path, strict_parameters=True, document=document
        )
        definitions = document.get("Parameters", {})
        for key, definition in definitions.items():
            if definition.get("NoEcho") or re.search(
                r"password|secret|token|credential", key, re.I
            ):
                value = values[key]
                self.sensitive_values.update(
                    str(item)
                    for item in (value if isinstance(value, list) else [value])
                )
        pseudo = {
            "AWS::StackName": name,
            "AWS::AccountId": self.target.get(
                "awsExecutionAccountId", self.target["awsAccountId"]
            ),
            "AWS::Region": self.target["awsRegion"],
            "AWS::NoValue": {"$noValue": True},
        }
        if not hasattr(self, "partition"):
            Loader = aws_runtime().sdk_loader
            part = next(
                (
                    part
                    for part in Loader().load_data("endpoints")["partitions"]
                    if self.target["awsRegion"] in part["regions"]
                ),
                None,
            )
            self.partition = part["partition"] if part is not None else None
            self.url_suffix = part.get("dnsSuffix") if part is not None else None
        if self.partition is not None:
            pseudo["AWS::Partition"] = self.partition
        if self.url_suffix:
            pseudo["AWS::URLSuffix"] = self.url_suffix
        self.stack_inputs[name] = document, values, pseudo
        self.metrics["stack_evaluations"] += 1
        return template, self.stack_inputs[name]

    def reference(
        self, service, value, expected_attribute=None, *, protect_import=True
    ):
        if isinstance(value, ResourceReference):
            refservice, identity = value["$resource"]
            resource = self.resources[refservice][identity]
            if (
                expected_attribute is not None
                and reference_attribute(resource["resourceType"], expected_attribute)
                != value["$attribute"]
            ):
                raise Blocked(
                    "validated reference attribute differs from receiving property contract"
                )
            resolver = _imports_model_identity.Resolver(self.root)
            resolver.catalog = self.catalog
            try:
                resolver.validate_attribute(
                    resource["resourceType"], value["$attribute"]
                )
            except (ReferenceResolutionError, ValueError) as error:
                raise Blocked(str(error)) from error
            return (
                self.protect_import_reference(value, resource, None)
                if protect_import
                else value
            )
        Scope = _imports_model_sources.Scope
        consumer = Scope(self.root, self.environment, self.directory, service)
        environment, directory, refservice, anchor = parse_reference(value, consumer)
        if (environment, directory) != (self.environment, self.directory):
            Resolver = _imports_model_identity.Resolver
            Resolver(self.root).resolve(value, consumer)
            raise Blocked("cross-target IaC reference requires a proven handoff")
        model = self.model(refservice)
        if not hasattr(self, "reference_anchor_indexes"):
            self.reference_anchor_indexes = {}
        if refservice not in self.reference_anchor_indexes:
            self.reference_anchor_indexes[refservice] = anchor_index(model.values)
        try:
            identity, resource = select_anchor(
                self.reference_anchor_indexes[refservice], anchor, value
            )
        except ReferenceResolutionError as error:
            raise Blocked(str(error)) from error
        attributes = {
            row["property"].removeprefix(resource["resourceType"] + ".")
            for _, row in self.rows[refservice][identity]
            if row["property"] in catalog_outputs(self.root, resource["resourceType"])
        }
        schema = self.catalog.schema(resource["resourceType"])
        primary = schema.get("primaryIdentifier", [])
        if expected_attribute is None:
            expected_attribute = REF_ATTRIBUTES.get(resource["resourceType"])
            if expected_attribute is None:
                raise Blocked(
                    f"reference attribute is unproven: {resource['resourceType']}; explicit property contract required"
                )
        expected_attribute = reference_attribute(
            resource["resourceType"], expected_attribute
        )
        # The link label is never a physical ID, including PENDING_DEPLOY.
        readonly = schema.get("readOnlyProperties", [])
        alias_arn = resource[
            "resourceType"
        ] in ARN_SHAPES and expected_attribute == reference_attribute(
            resource["resourceType"], "Arn"
        )
        if (
            not alias_arn
            and expected_attribute not in attributes
            and expected_attribute not in schema.get("identifierOutputs", [])
            and "/properties/" + expected_attribute not in primary + readonly
        ):
            raise Blocked(f"reference attribute not confirmed: {expected_attribute}")
        symbol = ResourceReference(
            {"$resource": [refservice, identity], "$attribute": expected_attribute}
        )
        return (
            self.protect_import_reference(symbol, resource, None)
            if protect_import
            else symbol
        )

    def protect_import_reference(self, symbol, resource, consumer_property):
        expected_attribute = symbol["$attribute"]
        if resource_mode(resource) == "IMPORT":
            if (
                self.local_comparison
                and registry.resource(resource["resourceType"]).imported_arn is not None
                and REFERENCE_PROPERTIES.get(consumer_property)
                == (resource["resourceType"], expected_attribute)
                and self.target["iacEngine"] == "cloudformation"
            ):
                self.reference_literal(symbol)
                return symbol
            defer_import_reference(self, symbol, resource, consumer_property)
        return symbol

    def symbol(self, stack, logical, attribute=None, *, derived=False):
        attribute = str(attribute) if isinstance(attribute, str) else attribute
        cachekey = stack, logical, attribute, derived
        if cachekey in self.symbols:
            if self.symbols[cachekey] is None:
                raise Blocked(f"cyclic resource reference: {stack}/{logical}")
            return self.symbols[cachekey]
        document, parameters, pseudo = self.stack_inputs[stack]
        definition = document.get("Resources", {}).get(logical)
        if not definition or not condition_active(
            document, parameters, pseudo, definition
        ):
            raise Blocked(
                f"local resource reference missing/inactive: {stack}/{logical}"
            )
        if self.local_comparison and not self.reference_models_loaded:
            # Same-target model identities establish uniqueness, never physical values.
            for path in model_paths(self.root, self.environment, self.directory):
                if path.stem != "cloudformation-stacks":
                    self.model(path.stem)
            self.reference_models_loaded = True
        direct = self.index()
        try:
            entry = mapped_resource(direct, stack, logical, definition["Type"])
        except ValueError as error:
            if self.local_comparison:
                raise Blocked(
                    f"unproven resource correspondence: {stack}/{logical}: {error}"
                ) from error
            raise
        path, identity, resource, _ = entry
        if attribute is None:
            ref_rule = registry.resource(resource["resourceType"]).ref_attribute
            ref_property = registry.resource(resource["resourceType"]).ref_property
            if self.local_comparison and ref_rule and ref_property:
                self.symbols[cachekey] = None
                try:
                    attribute = ref_rule(
                        definition.get("Properties", {}).get(ref_property),
                        document,
                        parameters,
                        pseudo,
                        self.resource_type,
                        partial(self.evaluate, stack),
                    )
                finally:
                    self.symbols.pop(cachekey, None)
            else:
                attribute = REF_ATTRIBUTES.get(resource["resourceType"])
            if attribute is None:
                raise Blocked(
                    f"Ref return attribute is unproven: {resource['resourceType']}"
                )
        elif not (
            derived
            and (
                attribute == reference_attribute(resource["resourceType"], "Arn")
                and resource["resourceType"] in ARN_SHAPES
                or attribute == REF_ATTRIBUTES.get(resource["resourceType"])
            )
        ):
            if self.local_comparison and not getatt_attribute(
                resource["resourceType"],
                attribute,
                self.catalog.schema(resource["resourceType"]),
            ):
                raise Blocked(
                    f"unproven GetAtt return attribute: {logical}.{attribute}"
                )
            if not self.local_comparison:
                self.catalog.property_schema(resource["resourceType"], attribute)
        result = ResourceReference(
            {
                "$resource": [path.stem, identity],
                "$attribute": reference_attribute(resource["resourceType"], attribute),
            }
        )
        self.symbols[cachekey] = result
        return result

    def import_value(self, stack, argument, seen):
        name = self.evaluate(stack, argument, seen | {("export-name",)})
        if not isinstance(name, str):
            raise Blocked("ImportValue name is not a local string")
        token = ("import", stack, name)
        if token in seen:
            raise Blocked(f"cyclic ImportValue: {name}")
        scope = tuple(
            context_value(self.stack_inputs[stack][2], group)
            for group in ("partition", "account", "region")
        )
        if self.exports is None:
            # Cache the partial index and failures too: one broken stack is not a
            # reason to discard proven exports or retry the entire search per row.
            self.exports = {}
            for _, unit in self.templates():
                try:
                    _, (document, parameters, pseudo) = self.stack(unit)
                    if document.get("Transform"):
                        raise Blocked("Transform requires external evaluation")
                except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                    self.export_failures.append(error)
                    continue
                for output in document.get("Outputs", {}).values():
                    try:
                        if "Export" not in output or not condition_active(
                            document, parameters, pseudo, output
                        ):
                            continue
                        producer_scope = tuple(
                            context_value(pseudo, group)
                            for group in ("partition", "account", "region")
                        )
                        export = self.evaluate(
                            unit["name"],
                            output["Export"]["Name"],
                            frozenset({("export-name",)}),
                        )
                        if not isinstance(export, str):
                            raise Blocked("Export name is not a local string")
                        self.exports.setdefault((*producer_scope, export), []).append(
                            (unit["name"], output.get("Value"))
                        )
                    except (Blocked, ValueError, KeyError, TypeError, OSError) as error:
                        self.export_failures.append(error)
        candidates = self.exports.get((*scope, name), [])
        if self.export_failures:
            error = self.export_failures[0]
            blocked = Blocked(f"ImportValue handoff search incomplete: {error}")
            causes = [
                getattr(failure, "iac_cause", None) for failure in self.export_failures
            ]
            if (
                all(causes)
                and len({(cause["kind"], cause["path"]) for cause in causes}) == 1
            ):
                blocked.iac_cause = dict(
                    causes[0],
                    relationship="export-search-incomplete",
                    consumer_stack=stack,
                )
            else:
                blocked.iac_cause = {
                    "kind": "import-unresolved",
                    "export": name,
                    "relationship": "import",
                    "consumer_stack": stack,
                }
            raise blocked from error
        if len(candidates) != 1 or candidates[0][0] == stack:
            blocked = Blocked(
                f"ImportValue handoff matches={len(candidates)} or same-stack export: {name}"
            )
            blocked.iac_cause = {
                "kind": "import-unresolved",
                "export": name,
                "relationship": "import",
                "consumer_stack": stack,
                "matches": len(candidates),
            }
            raise blocked
        producer, value = candidates[0]
        try:
            deferred = None
            try:
                result = self.evaluate(
                    producer, value, (seen - {("comparison-select",)}) | {token}
                )
            except Blocked as error:
                if not str(error).startswith("Select bounds are unproven:"):
                    raise
                # Preserve expression identity only; concrete Select evaluation still fails closed.
                deferred = str(error)
                result = self.evaluate(
                    producer,
                    value,
                    (seen - {("comparison-select",)})
                    | {token, ("expression-identity",)},
                )
            if isinstance(result, (ResourceReference, Expression)):
                # Keep provenance on this import occurrence without mutating cached symbols.
                origins = reference_evidence.export_origins(
                    result, self.export_provenance
                )
                result = (
                    ResourceReference(result)
                    if isinstance(result, ResourceReference)
                    else Expression(
                        result.operation,
                        result.operands,
                        result.direct_origins,
                        result.export_origins,
                    )
                )
                origin = {"export_name": name, "export_stack": producer}
                if deferred:
                    origin.update(scope=scope, unproven=deferred)
                if isinstance(result, Expression):
                    result = Expression(
                        result.operation,
                        result.operands,
                        result.direct_origins,
                        tuple([origin, *origins]),
                    )
                self.export_provenance[id(result)] = (result, [origin, *origins])
            return result
        except Blocked as error:
            if not getattr(error, "iac_cause", None):
                error.iac_cause = {
                    "kind": "import-unresolved",
                    "export": name,
                    "relationship": "import",
                    "consumer_stack": stack,
                }
            raise

    def reference_literal(
        self, value, *, recorded=None, seen=frozenset(), symbolic_arn=False
    ):
        """Resolve local values; an optional comparison proof may use recorded outputs."""
        if isinstance(value, Expression):
            return references.literal_expression(
                value,
                resolve_literal=partial(
                    self.reference_literal, recorded=recorded, seen=seen
                ),
            )
        service, identity = value["$resource"]
        token = (service, identity, value["$attribute"])
        if token in seen:
            raise Blocked("cyclic reference literal dependency")
        seen = seen | {token}
        resource = self.resources[service][identity]
        suffix = ATTRIBUTE_SUFFIXES.get((resource["resourceType"], value["$attribute"]))
        if suffix:
            base = ResourceReference(dict(value, **{"$attribute": suffix[0]}))
            return (
                self.reference_literal(base, recorded=recorded, seen=seen) + suffix[1]
            )
        imported_arn = registry.resource(resource["resourceType"]).imported_arn
        if (
            self.local_comparison
            and imported_arn
            and resource_mode(resource) == "IMPORT"
            and value["$attribute"] == "Arn"
            and self.target["iacEngine"] == "cloudformation"
        ):
            return imported_arn(
                self.rows[service][identity],
                self.catalog,
                getattr(self, "partition", None),
                self.target,
                self.stack_inputs,
            )
        name, logical, document, pseudo = self.reference_context(value)
        attribute = value["$attribute"]
        secret_name = (
            attribute == registry.resource(resource["resourceType"]).explicit_name
        )
        evaluator = self.evaluator()
        properties = document["Resources"][logical].get("Properties", {})
        if resource["resourceType"] in ARN_SHAPES and attribute == reference_attribute(
            resource["resourceType"], "Arn"
        ):
            if resource_mode(resource) != "CREATE":
                raise Blocked(
                    "named ARN requires CREATE resource correspondence; IMPORT requires approved handoff"
                )
            return named_arn(
                resource["resourceType"],
                properties,
                pseudo,
                evaluate=partial(
                    self.reference_component, name, recorded=recorded, seen=seen
                ),
                schema=self.catalog.schema(resource["resourceType"]),
                recorded=(
                    lambda field: recorded(
                        ResourceReference(dict(value, **{"$attribute": field}))
                    )
                )
                if recorded is not None
                else None,
                reference=(
                    lambda field: ResourceReference(
                        dict(
                            value,
                            **{
                                "$attribute": reference_attribute(
                                    resource["resourceType"], field
                                )
                            },
                        )
                    )
                )
                if symbolic_arn
                else None,
            )
        setting = RETURN_ATTRIBUTE_PROPERTIES.get((resource["resourceType"], attribute))
        explicit_path = setting or attribute
        readonly = "/properties/" + explicit_path.replace(
            ".", "/"
        ) in self.catalog.schema(resource["resourceType"]).get("readOnlyProperties", ())
        if (
            (
                attribute != REF_ATTRIBUTES.get(resource["resourceType"])
                and not secret_name
                and setting is None
            )
            or select(properties, explicit_path) == MISSING
            or readonly
        ):
            if recorded is not None:
                return recorded(value)
            raise Blocked("reference has no explicit name property contract")
        result = evaluator.substitution(name, value, frozenset(), preserve=False)
        if not isinstance(result, str):
            raise Blocked("reference name remains symbolic")
        if not result or result in {"UNSET", "PENDING_DEPLOY", "TBD", "TODO", "未確定"}:
            raise Blocked("reference name is unresolved")
        return result

    def display_reference(self, value):
        """Resolve one displayed symbol using this run's proof and input caches."""
        service, identity = value["$resource"]
        attribute = value["$attribute"]
        key = service, identity, attribute
        if not hasattr(self, "_display_reference_cache"):
            self._display_reference_cache = {}
        cache = self._display_reference_cache
        if key not in cache:
            proof = reference_evidence.Evidence(self)
            try:
                if identity not in self.resources.get(service, {}):
                    raise Blocked(
                        "reference Producer is unavailable in comparison inputs"
                    )
                if not self.reference_models_loaded:
                    raise Blocked("reference comparison context is unavailable")
                literal = proof.resolve(value)
            except Blocked as error:
                cache[key] = None, None, str(error)
            else:
                cache[key] = (
                    literal,
                    "Observed（記録値・現在AWS未確認）"
                    if proof.observed
                    else "IaC（ローカル評価）",
                    None,
                )
        literal, source, error = cache[key]
        if error is not None:
            raise Blocked(error)
        return self.redacted(
            literal, self.resource_type(value) + "." + attribute
        ), source

    def reference_context(self, value):
        service, identity = value["$resource"]
        resource = self.resources[service][identity]
        name, logical = cfn_resource_identity(resource["cfn-logicalId"])
        units = [unit for _, unit in self.templates() if unit["name"] == name]
        if len(units) != 1:
            raise Blocked("reference stack correspondence is unproven")
        self.stack(units[0])
        attribute = value["$attribute"]
        if attribute == "Ref":
            raise Blocked(
                "opaque Ref requires the same proven Producer; no local literal contract"
            )
        secret_name = (
            attribute == registry.resource(resource["resourceType"]).explicit_name
        )
        bound = self.symbol(
            name, logical, None if secret_name else attribute, derived=not secret_name
        )
        if secret_name:
            bound = ResourceReference(dict(bound, **{"$attribute": "Name"}))
        if not same(bound, value):
            raise Blocked("reference resource correspondence is unproven")
        document, _, pseudo = self.stack_inputs[name]
        if document.get("Transform"):
            raise Blocked("Transform requires external evaluation")
        return name, logical, document, pseudo

    def producer_scope(self, value):
        service, identity = value["$resource"]
        if resource_mode(self.resources[service][identity]) != "CREATE":
            raise Blocked(
                "ARN projection requires CREATE correspondence; IMPORT requires approved handoff"
            )
        _, _, _, pseudo = self.reference_context(value)
        return {
            group: context_value(pseudo, group)
            for group in ("partition", "region", "account")
        }

    def project_arn(self, value):
        return arn_projection.project(
            value, resource_type=self.resource_type, producer_scope=self.producer_scope
        )

    def reference_component(self, stack, value, *, recorded=None, seen=frozenset()):
        value = self.evaluate(stack, value)
        return (
            self.reference_literal(value, recorded=recorded, seen=seen)
            if isinstance(value, (ResourceReference, Expression))
            else value
        )

    def parameter_keys(self, unit):
        path = (
            self.root
            / "infra/cloudformation/parameters"
            / self.environment
            / self.directory
            / unit["parameters"]
        )
        self.track(path)
        return path, {
            item["ParameterKey"]
            for item in strict_json(path.read_text(encoding="utf-8"))
        }

    def resource_type(self, reference):
        service, identity = reference["$resource"]
        return self.resources[service][identity]["resourceType"]

    def redacted(self, value, prop=""):
        return redacted(value, prop, sensitive_values=self.sensitive_values)

    def evaluator(self):
        return evaluation.evaluator(
            self.stack_inputs,
            self.resources,
            self.catalog.property_schema,
            self.symbol,
            self.import_value,
            self.local_comparison,
            self.catalog.schema,
            self.defer_select,
        )

    def defer_select(self, stack, value, reason, *, direct=False):
        if direct:
            scope = tuple(
                context_value(self.stack_inputs[stack][2], group)
                for group in ("partition", "account", "region")
            )
            return Expression(
                value.operation,
                value.operands,
                ({"stack": stack, "scope": scope, "unproven": reason},),
            )
        origins = reference_evidence.export_origins(
            value.operands[1], self.export_provenance
        )
        if not origins:
            return None
        scope = tuple(
            context_value(self.stack_inputs[stack][2], group)
            for group in ("partition", "account", "region")
        )
        if any(origin.get("scope", scope) != scope for origin in origins):
            return None
        return Expression(
            value.operation,
            value.operands,
            value.direct_origins,
            tuple(dict(origin, scope=scope, unproven=reason) for origin in origins),
        )

    def evaluate(self, stack, value, seen=frozenset()):
        return self.evaluator().evaluate(stack, value, seen)

    def evaluate_for_comparison(self, stack, value):
        if not self.local_comparison:
            return self.evaluate(stack, value)
        return self.evaluate(
            stack,
            value,
            frozenset({("comparison-select",), ("comparison-unresolved",)}),
        )

    def reference_forms(self, kind, path):
        key = self.local_comparison, kind, path
        if key not in self.reference_formats:
            self.reference_formats[key] = references.reference_forms(
                kind,
                path,
                local_comparison=self.local_comparison,
                property_schema=self.catalog.property_schema,
            )
        return self.reference_formats[key]

    def kms_format(self, value):
        return kms_format(value, self.resources, project_arn=self.project_arn)

    def reference_diagnostic(self, left, right, kind, path, reason, *, code=None):
        detail = references.reference_diagnostic(
            left,
            right,
            kind,
            path,
            reason,
            code=code,
            local_comparison=self.local_comparison,
            forms_for=self.reference_forms,
            kms_format=self.kms_format,
            resource_type=self.resource_type,
            redact=self.redacted,
        )
        origins = reference_evidence.export_origins(
            right, getattr(self, "export_provenance", {})
        )
        for origin in reference_evidence.export_origins(
            left, getattr(self, "export_provenance", {})
        ):
            if origin not in origins:
                origins.append(origin)
        if origins:
            detail["exports"] = self.redacted(origins)
        direct = reference_evidence.export_origins(
            [left, right], getattr(self, "select_provenance", {}), direct=True
        )
        if direct:
            detail["direct"] = self.redacted(direct)
        return detail

    def reference_decision(self, left, right, kind, path, *, context=None):
        selected = None
        if self.local_comparison:
            selected = registry.property_rule(kind, path).selected_decision
        if selected is not None:
            outcome = selected(
                self,
                left,
                right,
                path,
                export_origins=reference_evidence.export_origins,
            )
            if outcome is not NotImplemented:
                equal, reason = outcome
                detail = self.reference_diagnostic(left, right, kind, path, reason)
                origins = reference_evidence.export_origins(
                    [left, right], self.export_provenance
                )
                detail.update(
                    evidence_type="export_expression"
                    if origins
                    else "direct_expression",
                    structural_equivalence=equal,
                    current_aws_verified=False,
                    runtime_bounds_verified=False,
                )
                return references.ReferenceDecision(equal, (detail,), equal is True)
        direct = reference_evidence.export_origins(
            [left, right], getattr(self, "select_provenance", {}), direct=True
        )
        if direct:
            if (
                isinstance(left, (list, dict))
                and isinstance(right, (list, dict))
                and not isinstance(left, ResourceReference)
                and not isinstance(right, ResourceReference)
            ):
                return references.ReferenceDecision(NotImplemented)
            detail = self.reference_diagnostic(
                left,
                right,
                kind,
                path,
                "Select bounds and selection contract are unproven",
            )
            detail.update(
                evidence_type="direct_expression",
                runtime_bounds_verified=False,
                current_aws_verified=False,
            )
            return references.ReferenceDecision(None, (detail,))
        left_origins = reference_evidence.export_origins(
            left, getattr(self, "export_provenance", {})
        )
        right_origins = reference_evidence.export_origins(
            right, getattr(self, "export_provenance", {})
        )
        deferred = any(
            isinstance(value, (ResourceReference, Expression))
            for value in (left, right)
        ) and any("unproven" in origin for origin in left_origins + right_origins)
        if deferred and (
            not left_origins or not right_origins or left_origins != right_origins
        ):
            detail = self.reference_diagnostic(
                left,
                right,
                kind,
                path,
                "Export expression identity is unproven; Select bounds remain unproven",
            )
            detail.update(evidence_type="export_expression", current_aws_verified=False)
            return references.ReferenceDecision(None, (detail,))
        if (
            self.local_comparison
            and not deferred
            and any(
                reference_evidence.unproven_select(value, self.evaluator)
                for value in (left, right)
            )
        ):
            if all(
                isinstance(value, (list, dict))
                and not isinstance(value, ResourceReference)
                for value in (left, right)
            ):
                return references.ReferenceDecision(NotImplemented)
            detail = self.reference_diagnostic(
                left,
                right,
                kind,
                path,
                "Select bounds and selection contract are unproven",
            )
            return references.ReferenceDecision(None, (detail,))
        result = references.reference_same(
            left,
            right,
            kind,
            path,
            local_comparison=self.local_comparison,
            forms_for=self.reference_forms,
            resolve_literal=self.reference_literal,
            resource_type=self.resource_type,
            kms_format=self.kms_format,
            diagnostic=self.reference_diagnostic,
            evidence=self.reference_evidence if self.local_comparison else None,
            project_arn=self.project_arn,
            context=context,
            proven_export=deferred,
        )
        if deferred:
            detail = self.reference_diagnostic(
                left,
                right,
                kind,
                path,
                "same Export expression"
                if result.equal is True
                else "Export transformation equivalence is unproven",
            )
            detail.update(evidence_type="export_expression", current_aws_verified=False)
            return references.ReferenceDecision(
                True if result.equal is True else None,
                (*result.diagnostics, detail),
                result.equal is True and result.equivalent,
            )
        return result

    def reference_evidence(self, left, right, kind, path):
        return reference_evidence.compare(self, left, right, kind, path)

    def reference_same(self, left, right, kind, path):
        return self.reference_decision(left, right, kind, path).equal

    def desired_reference(
        self, service, value, kind, path, attribute=None, context=None
    ):
        return design_link.desired_reference(
            service,
            value,
            kind,
            path,
            attribute,
            context,
            local_comparison=self.local_comparison,
            reference=self.reference,
            resource_type=self.resource_type,
            forms_for=self.reference_forms,
            protect_import=lambda symbol, prop: self.protect_import_reference(
                symbol,
                self.resources[symbol["$resource"][0]][symbol["$resource"][1]],
                prop,
            ),
        )

    def normalize_model_reference(
        self, service, row_id, field, value, context=None, failures=None
    ):
        try:
            if service not in self.model_references:
                self.model_references[service] = model_reference.ModelReferences(
                    self, service
                )
            key = f"desired.row.{row_id}.{field}"
            if (
                context is None
                and row_id
                and row_id.rpartition("-")[0] in self.resources[service]
            ):
                number = row_id.rpartition("-")[0]
                kind = self.resources[service][number]["resourceType"]
                contexts = row_contexts(kind, self.rows[service][number])
                prop = (
                    self.model(service)
                    .authoritative.get(f"desired.row.{row_id}.property", "")
                    .removeprefix(kind + ".")
                )
                context = contexts.get(
                    row_id, contexts.get(prop, contexts.get(prop.rsplit(".", 1)[0]))
                )
            return self.model_references[service].normalize(
                self,
                key,
                value,
                "" if field == "document" or isinstance(value, (list, dict)) else None,
                context,
                failures,
            )
        except (KeyError, ValueError, TypeError) as error:
            raise Blocked(str(error)) from error

    def prepare_value(
        self, service, row, kind, *, stack=None, context=None, row_id=None
    ):
        normalize = (
            (
                lambda value, failures: self.normalize_model_reference(
                    service,
                    row_id,
                    "document" if "document" in row else "value",
                    value,
                    context,
                    failures,
                )
            )
            if self.local_comparison and row_id is not None
            else None
        )
        return values.desired_value(
            service,
            row,
            kind,
            stack=stack,
            context=context,
            local_comparison=self.local_comparison,
            desired_reference=self.desired_reference,
            property_schema=self.catalog.property_schema,
            evaluate=self.evaluate,
            model_path=self.root
            / "model"
            / self.environment
            / self.directory
            / (service + ".properties"),
            normalize=normalize,
            environment_mapping=environment_values.mapping_for(self.root, kind),
            catalog=self.catalog,
        )

    def project_rows(self, kind, rows):
        indexed_rows = _imports_array_display.indexed_rows
        prepare = registry.resource(kind).prepare_rows
        if prepare is None:
            return rows
        projected = [
            (rid, row) for rid, row in rows if value_shape(row) == "projection"
        ]
        leaves = [(rid, row) for rid, row in rows if value_shape(row) == "leaf"]
        return [
            *prepare(
                leaves,
                index_rows=lambda rows, kind: indexed_rows(rows, kind, self.root),
            ),
            *projected,
        ]
