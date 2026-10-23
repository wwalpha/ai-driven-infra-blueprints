"""Lexical, repository-relative Resource addresses shared by contracts and Models."""



def resource_address(value):
    parts = tuple(value.split('/')) if isinstance(value, str) else ()
    if len(parts) != 4 or any(not part or part in {'.', '..'} or '\\' in part for part in parts):
        raise ValueError('resource address requires environment/target/service/fixed-ID')
    return parts
