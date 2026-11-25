"""Parser and mock mapper for the X-Simulate-Failure test hook."""

SUPPORTED_STATUSES = frozenset({429, 500, 502, 503})


def parse_simulation_header(
    header_value: str | None,
    key_ids: list[str],
    enabled: bool,
) -> dict[str, int]:
    """Parse X-Simulate-Failure into {key_id: status_code} for a single request.

    Malformed pairs, unsupported statuses, and unknown key IDs are ignored so bad
    headers never break normal chat handling. Returns {} when simulation is disabled.
    """
    if not enabled or not header_value or not key_ids:
        return {}

    known = set(key_ids)
    simulated: dict[str, int] = {}

    for raw_pair in header_value.split(","):
        pair = raw_pair.strip()
        if "=" not in pair:
            continue
        raw_target, raw_status = pair.split("=", 1)
        target = raw_target.strip()
        try:
            status = int(raw_status.strip())
        except ValueError:
            continue

        if status not in SUPPORTED_STATUSES:
            continue

        if target == "*":
            for key_id in key_ids:
                simulated[key_id] = status
        elif target in known:
            simulated[target] = status

    return simulated


def status_to_mock_string(status: int) -> str:
    """Map simulated HTTP status to LiteLLM's native mock_response error string."""
    if status == 429:
        return "litellm.RateLimitError"
    return "litellm.InternalServerError"

