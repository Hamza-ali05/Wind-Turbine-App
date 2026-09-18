"""Pipeline business logic (filled in later phases)."""


def not_implemented(stage: str, **extra: object) -> dict[str, object]:
    return {"status": "not_implemented", "stage": stage, **extra}
