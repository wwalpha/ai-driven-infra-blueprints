"""EC2 row display and restoration; no file reads or publication."""

import json
import re


EC2_BLOCK_DEVICE = "EC2.Instance.BlockDeviceMappings[]."
EC2_NAME_TAG = re.compile(r"^<!-- ec2-name-tag: (.+?) -->\s*")


def ec2_display_rows(rows: list[list[str]]) -> list[list[str]]:
    """Number block devices and compact Instance/VPCEndpoint Name tags."""
    result = []
    device = 0
    fields = set()
    index = 0
    while index < len(rows):
        identity, prop, value, comment = rows[index]
        if prop.startswith("BlockDeviceMappings[]."):
            field = prop.removeprefix("BlockDeviceMappings[].")
            if field == "DeviceName":
                device += 1
                fields = set()
            if not device or field in fields:
                raise ValueError("EC2 block device rows must start with DeviceName and contain unique fields")
            fields.add(field)
            prop = f"BlockDeviceMappings[{device}].{field}"
        elif prop == "Tags[].Key" and value.strip("`\"") == "Name":
            if index + 1 >= len(rows) or rows[index + 1][1] != "Tags[].Value":
                raise ValueError("EC2 Name tag requires the corresponding Tags[].Value")
            metadata = json.dumps([value, comment], ensure_ascii=True)
            for char in "|<>":
                metadata = metadata.replace(char, f"\\u{ord(char):04x}")
            prop = "Name"
            value, comment = rows[index + 1][2:]
            comment = f"<!-- ec2-name-tag: {metadata} --> " + comment
            index += 1
        result.append([identity, prop, value, comment])
        index += 1
    return result


def ec2_formal_rows(rows: list[list[str]], resource_type: str) -> list[list[str]]:
    """Restore compact EC2 rows without losing tag values or source comments."""
    result = []
    device = 0
    fields = set()
    for identity, prop, value, comment in rows:
        display = prop.removeprefix(resource_type + ".")
        marker = EC2_NAME_TAG.match(comment)
        if "<!-- ec2-name-tag:" in comment and (not marker or display != "Name"):
            raise ValueError("EC2 Name tag source marker requires a Name display row")
        if display == "Name":
            if not marker:
                raise ValueError("EC2 Name display requires its Name tag source marker")
            source = json.loads(marker[1])
            if not isinstance(source, list) or len(source) != 2 or any(not isinstance(item, str) for item in source) or source[0].strip("`\"") != "Name":
                raise ValueError("invalid EC2 Name tag source marker")
            result.append([identity, resource_type + ".Tags[].Key", *source])
            result.append([identity, resource_type + ".Tags[].Value", value, comment[marker.end():]])
            continue
        if display.startswith("BlockDeviceMappings[") and not display.startswith("BlockDeviceMappings[]."):
            match = re.fullmatch(r"BlockDeviceMappings\[([1-9]\d*)\]\.(.+)", display)
            if not match:
                raise ValueError("EC2 block devices must use BlockDeviceMappings[N], starting at 1")
            number, field = int(match[1]), match[2]
            if number != device:
                if number != device + 1 or field != "DeviceName":
                    raise ValueError("EC2 block device indexes must be sequential and start with DeviceName")
                device, fields = number, set()
            if field in fields:
                raise ValueError("duplicate EC2 block device field")
            fields.add(field)
            prop = EC2_BLOCK_DEVICE + field
        result.append([identity, prop, value, comment])
    return result


