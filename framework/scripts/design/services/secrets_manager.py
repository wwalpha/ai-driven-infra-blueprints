"""Secrets Manager display parsing."""


def subnet_list_items(raw):
    return [item.strip() for item in raw.split(",")]
