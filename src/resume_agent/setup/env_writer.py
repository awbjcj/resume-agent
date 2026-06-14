"""Pure .env read/merge/format. The actual file write lives in writer.py."""


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote = value[0]
            value = value[1:-1]
            if quote == '"':
                value = value.replace('\\"', '"')  # undo format_env's escaping
        out[key.strip()] = value
    return out


def merge_env(existing: dict[str, str], updates: dict[str, str]) -> dict[str, str]:
    """Overwrite managed keys; never drop an unmanaged key."""
    merged = dict(existing)
    merged.update(updates)
    return merged


def _fmt_value(value: str) -> str:
    if value == "" or any(c in value for c in " #\"'"):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def format_env(data: dict[str, str]) -> str:
    return "".join(f"{key}={_fmt_value(value)}\n" for key, value in data.items())
