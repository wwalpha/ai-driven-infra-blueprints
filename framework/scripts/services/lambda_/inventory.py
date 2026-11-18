"""Lambda IMPORT code-source acquisition and evidence checks."""

from aws_mapping import response_shape
from contracts.model import MODEL_PENDING_DEPLOY, MODEL_UNSET
from model.importing.sources import typed_equal
from utils.aws_sdk import sdk_for


def allows_missing_code(prop, capture, properties):
    package = properties.get("Lambda.Function.PackageType", {}).get("value")
    return (
        capture.get("reason") == "Lambda Image uses an image source"
        and package == "Image"
        or prop == "Lambda.Function.Code.ImageUri"
        and package == "Zip"
    )


def addition_issue(record, read_value):
    code = {}
    for name in ("S3Bucket", "S3Key", "ImageUri", "ZipFile"):
        prop = "Lambda.Function.Code." + name
        value = read_value(prop)
        capture = record["properties"].get(prop, {})
        code[name] = (
            isinstance(value, str)
            and bool(value.strip())
            and value not in {MODEL_UNSET, MODEL_PENDING_DEPLOY}
            and capture.get("status") == "captured"
            and typed_equal(value, capture.get("value"))
        )
    package = record["properties"].get("Lambda.Function.PackageType", {})
    if package.get("status") != "captured" or not (
        package.get("value") == "Zip"
        and code["S3Bucket"]
        and code["S3Key"]
        and not code["ImageUri"]
        and not code["ZipFile"]
        or package.get("value") == "Image"
        and code["ImageUri"]
        and not code["S3Bucket"]
        and not code["S3Key"]
        and not code["ZipFile"]
    ):
        return "Lambda deployment code source is not established"
    return None


def capture_contract(root, path, mapped, getter, reference):
    if (
        mapped.source != "aws"
        or mapped.field.classification != "supported"
        or mapped.field.getter != "base"
        or mapped.field.path != path
        or getter.get("kind") != "adapter"
    ):
        return None
    model = sdk_for(root).service_model("lambda")
    shape = model.operation_model("GetFunction").output_shape
    try:
        response_shape(shape, path)
    except ValueError:
        return None
    return {
        "status": "unobservable",
        "reasonCode": "OPTIONAL_CODE_SOURCE_NOT_RETURNED",
        "reason": "GetFunction did not return this Zip code source; Code.Location does not establish the original upload location and existing values are not AWS verified",
        "evidence": {
            "mapping": reference,
            "api": "lambda.get_function",
            "missingPath": path,
        },
    }


def classify_capture(field, response, identity, restriction):
    if restriction is None or not isinstance(response, dict):
        raise ValueError("Lambda code-source contract or response is invalid")
    config, code = response.get("Configuration"), response.get("Code", {})
    if (
        not isinstance(config, dict)
        or not isinstance(code, dict)
        or not isinstance(identity, str)
        or not identity
        or config.get("FunctionName") != identity
        or config.get("PackageType") not in {"Zip", "Image"}
        or code.get("Error")
    ):
        raise ValueError(
            "Lambda code-source identity, package type or response is unresolved"
        )
    resolved = code.get("ResolvedS3Object", {})
    if not isinstance(resolved, dict):
        raise ValueError("Lambda resolved code source is invalid")
    if field in resolved:
        raise ValueError("Lambda code-source property was not absent")
    if config["PackageType"] == "Image":
        return None
    restriction["evidence"]["packageType"] = "Zip"
    restriction["evidence"]["codeSource"] = {
        name: bool(resolved.get(name)) for name in ("S3Bucket", "S3Key")
    }
    restriction["evidence"]["locationReturned"] = bool(code.get("Location"))
    restriction["evidence"]["imageUriReturned"] = bool(
        code.get("ImageUri") or code.get("ResolvedImageUri")
    )
    return restriction


def valid_capture(prop, capture, record, expected_contract):
    evidence = capture.get("evidence", {})
    if not isinstance(evidence, dict):
        return False
    source = evidence.get("codeSource")
    expected = expected_contract()
    if (
        expected is None
        or not isinstance(source, dict)
        or set(source) != {"S3Bucket", "S3Key"}
    ):
        return False
    if any(type(value) is not bool for value in source.values()):
        return False
    for name in ("locationReturned", "imageUriReturned"):
        if type(evidence.get(name)) is not bool:
            return False
    expected["evidence"].update(
        packageType="Zip",
        codeSource=source,
        locationReturned=evidence["locationReturned"],
        imageUriReturned=evidence["imageUriReturned"],
    )
    props = record.get("properties", {})
    if (
        capture != expected
        or record.get("identityStatus", "known") != "known"
        or not record.get("identity")
        or props.get("Lambda.Function.PackageType", {}).get("status") != "captured"
        or props.get("Lambda.Function.PackageType", {}).get("value") != "Zip"
        or props.get("Lambda.Function.FunctionName", {}).get("status") != "captured"
        or props.get("Lambda.Function.FunctionName", {}).get("value")
        != record["identity"]
        or source[prop.rsplit(".", 1)[1]]
    ):
        return False
    for name, present in source.items():
        other = props.get("Lambda.Function.Code." + name, {})
        if present != (other.get("status") == "captured"):
            return False
    return True
