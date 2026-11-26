from pathlib import Path

import pytest

from shared import enums

DESIGN = Path(__file__).resolve().parents[3] / "docs/04_Database_Design.md"


def test_canonical_enum_registry_matches_design():
    section = DESIGN.read_text(encoding="utf-8").split("## Canonical Enums", 1)[1]
    registry = section.split("| Enum | Values |", 1)[1].split("\n\n", 1)[0]
    for name, values in (
        line.strip("|").split("|") for line in registry.splitlines()[2:]
    ):
        assert [value.value for value in getattr(enums, name.strip())] == [
            part.strip() for part in values.split(",")
        ]

    message_types = section.split("MessageType values: ", 1)[1].split(".", 1)[0]
    assert [member.value for member in enums.MessageType] == [
        value.strip() for value in message_types.split(",")
    ]


def test_stop_and_execution_hint_vocabularies_are_separate():
    assert enums.StopType("PRICE_STOP") is enums.StopType.PRICE_STOP
    assert enums.OrderType("STOP") is enums.OrderType.STOP
    with pytest.raises(ValueError):
        enums.OrderType("STRUCTURE_CONFIRMATION")
    with pytest.raises(ValueError):
        enums.StopType("STOP")
    with pytest.raises(ValueError):
        enums.Action("WAIT_FOR_LIMIT_ENTRY")
