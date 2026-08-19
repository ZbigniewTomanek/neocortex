"""Unit tests for entity name and type normalization utilities."""

from __future__ import annotations

import pytest

from neocortex.normalization import (
    canonicalize_name,
    names_are_similar,
    normalize_edge_type,
    normalize_node_type,
)

# --- canonicalize_name ---


@pytest.mark.parametrize(
    "input_name, expected",
    [
        # Parenthetical alias extraction
        ("Fluoxetine (Prozac)", ("Fluoxetine", ["Prozac"])),
        (
            "serotonin (5-hydroxytryptamine, 5-HT)",
            ("Serotonin", ["5-hydroxytryptamine, 5-HT"]),
        ),
        # No parenthetical
        ("Apache Kafka", ("Apache Kafka", [])),
        # Whitespace collapsing + all-lowercase title casing
        ("  apache   kafka  ", ("Apache Kafka", [])),
        # Mixed case preservation
        ("gRPC", ("gRPC", [])),
        ("iOS", ("iOS", [])),
        ("PostgreSQL", ("PostgreSQL", [])),
        ("DataForge", ("DataForge", [])),
        # Acronym preservation in title-cased output
        ("5-HT", ("5-HT", [])),
        # All-lowercase with known acronyms
        ("rest api", ("REST API", [])),
        ("sql database", ("SQL Database", [])),
        # Empty / whitespace-only
        ("", ("", [])),
        ("   ", ("", [])),
        # Single word, already correct
        ("Python", ("Python", [])),
        # Single word, all lowercase
        ("python", ("Python", [])),
    ],
)
def test_canonicalize_name(input_name: str, expected: tuple[str, list[str]]) -> None:
    assert canonicalize_name(input_name) == expected


# --- normalize_edge_type ---


@pytest.mark.parametrize(
    "input_type, expected",
    [
        ("RelatesTo", "RELATES_TO"),
        ("relates_to", "RELATES_TO"),
        ("RELATES_TO", "RELATES_TO"),  # idempotent
        ("relates-to", "RELATES_TO"),
        ("hasMember", "HAS_MEMBER"),
        ("MEMBER_OF", "MEMBER_OF"),  # idempotent
        ("RELATES TO", "RELATES_TO"),  # space → underscore
        ("relates  to", "RELATES_TO"),  # multiple spaces
        ("usedBy", "USED_BY"),
    ],
)
def test_normalize_edge_type(input_type: str, expected: str) -> None:
    result = normalize_edge_type(input_type)
    assert result == expected
    # Verify idempotent
    assert normalize_edge_type(result) == result


# --- normalize_node_type ---


@pytest.mark.parametrize(
    "input_type, expected",
    [
        ("SoftwareTool", "SoftwareTool"),  # idempotent
        ("software_tool", "SoftwareTool"),  # snake_case → PascalCase
        ("SOFTWARE_TOOL", "SoftwareTool"),  # ALL_CAPS with separator → PascalCase
        ("SOFTWARETOOL", "SOFTWARETOOL"),  # ALL_CAPS no separator → preserve
        ("Person", "Person"),  # idempotent
        ("gRPC", "GRPC"),  # mixed case → uppercase start enforced
        ("software tool", "SoftwareTool"),  # space-separated → PascalCase
    ],
)
def test_normalize_node_type(input_type: str, expected: str) -> None:
    result = normalize_node_type(input_type)
    assert result == expected


# --- normalize_node_type: invalid character rejection ---


def test_node_type_strips_json_corruption():
    """Invalid chars like } are stripped; valid remainder passes through."""
    assert normalize_node_type("Constraint}OceanScience") == "ConstraintOceanScience"


def test_node_type_strips_and_rejects_only_invalid():
    """If only invalid chars remain after stripping, raise ValueError."""
    with pytest.raises(ValueError):
        normalize_node_type("()")
    with pytest.raises(ValueError):
        normalize_node_type("}{}")


def test_node_type_strips_invalid_chars_and_normalizes():
    """Invalid chars stripped, remaining text normalized to PascalCase."""
    assert normalize_node_type("Constraint!Science") == "ConstraintScience"


def test_node_type_valid_pascal_case():
    assert normalize_node_type("DataStore") == "DataStore"
    assert normalize_node_type("tool") == "Tool"
    assert normalize_node_type("data_store") == "DataStore"


def test_node_type_empty_string_raises():
    with pytest.raises(ValueError):
        normalize_node_type("")
    with pytest.raises(ValueError):
        normalize_node_type("   ")


# --- normalize_edge_type: invalid character rejection ---


def test_edge_type_strips_json_corruption():
    """Invalid chars like { are stripped; valid remainder passes through."""
    assert normalize_edge_type("RELATES{TO") == "RELATESTO"


def test_edge_type_valid_screaming_snake():
    assert normalize_edge_type("RELATES_TO") == "RELATES_TO"
    assert normalize_edge_type("relates to") == "RELATES_TO"
    assert normalize_edge_type("relatesTo") == "RELATES_TO"


def test_edge_type_hyphen_preserved():
    """Hyphens are converted to underscores, so RELATES-TO works."""
    assert normalize_edge_type("RELATES-TO") == "RELATES_TO"


def test_edge_type_empty_after_strip_raises():
    with pytest.raises(ValueError):
        normalize_edge_type("{}")
    with pytest.raises(ValueError):
        normalize_edge_type("")


# --- names_are_similar ---


@pytest.mark.parametrize(
    "a, b, expected",
    [
        # Exact match (case-insensitive)
        ("DataForge", "DataForge", True),
        ("dataforge", "DataForge", True),
        # Multi-word containment (shorter has 2+ words)
        ("John Doe", "Doe John", True),
        # Single-word containment is intentionally rejected to avoid
        # false positives like "Serotonin" matching "Serotonin Receptor".
        # PG adapter uses trigram similarity for these cases instead.
        ("Kafka", "Apache Kafka", False),
        ("Team Atlas", "Atlas", False),
        # Not similar
        ("Alice", "Bob", False),
        ("Python", "JavaScript", False),
    ],
)
def test_names_are_similar(a: str, b: str, expected: bool) -> None:
    assert names_are_similar(a, b) == expected


# --- normalize_node_type: length and word-count rejection (Plan 19, M6) ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "DatasetNoteTheSearchResultsShowed" + "x" * 400,  # 440+ chars
        "OperationbrSomeLongGarbage" + "x" * 300,  # 300+ chars
        "A" * 61,  # Just over limit
    ],
)
def test_normalize_node_type_rejects_too_long(bad_name: str) -> None:
    with pytest.raises(ValueError, match="too long"):
        normalize_node_type(bad_name)


@pytest.mark.parametrize(
    "bad_name",
    [
        "FeatureMergesWithEntityObjectId167",  # 7 PascalCase segments
        "ThisIsAVeryLongCompoundTypeName",  # 6 segments
    ],
)
def test_normalize_node_type_rejects_too_many_segments(bad_name: str) -> None:
    with pytest.raises(ValueError, match="too many segments"):
        normalize_node_type(bad_name)


def test_normalize_node_type_enforces_uppercase_start() -> None:
    assert normalize_node_type("algorithm") == "Algorithm"
    assert normalize_node_type("tool") == "Tool"


@pytest.mark.parametrize(
    "good_name,expected",
    [
        ("Algorithm", "Algorithm"),
        ("SoftwareSystem", "SoftwareSystem"),
        ("Bug", "Bug"),
    ],
)
def test_normalize_node_type_accepts_valid(good_name: str, expected: str) -> None:
    assert normalize_node_type(good_name) == expected


# --- normalize_edge_type: length and word-count rejection (Plan 19, M6) ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "A" * 61,
        "RELATES_TO_" + "X" * 50,
    ],
)
def test_normalize_edge_type_rejects_too_long(bad_name: str) -> None:
    with pytest.raises(ValueError, match="too long"):
        normalize_edge_type(bad_name)


# --- Tool-call artifact rejection (Plan 28, Stage 1) ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "ActivityfunctiondefaultApicreateOrUpdateNodecontent",
        "MentalstatecalldefaultApicreateOrUpdateEdgeedgeType",
        "PersoncreateOrUpdateNodeContent",
        "defaultApiCreateNode",
        "TypeUpdateNodeContent",
        "SomethingEndcallResult",
        # I4: DB ID + operation verb leakage (Plan 29)
        "ComponentUpdatingB47EngineId48",
        "ComponentUpdatingId46",
        "MetricUpdating142000KmId47",
        # I5: JS method name leakage (Plan 29)
        "BrandfunctionNameCreateOrUpdateNode",
        "Entity<think>",
        "Entity</think>",
        "Entity<tool_call>",
        "Entity<function=",
        "Entity<parameter=",
    ],
)
def test_normalize_node_type_rejects_tool_call_artifacts(bad_name: str) -> None:
    with pytest.raises(ValueError, match="tool-call artifact"):
        normalize_node_type(bad_name)


@pytest.mark.parametrize(
    "bad_name",
    [
        "functiondefaultApiRelateTo",
        "calldefaultEdgeType",
        "createOrUpdateEdge",
        "UpdateNodeRelation",
    ],
)
def test_normalize_edge_type_rejects_tool_call_artifacts(bad_name: str) -> None:
    with pytest.raises(ValueError, match="tool-call artifact"):
        normalize_edge_type(bad_name)


# --- Instance-level type rejection (Plan 28, Stage 1) ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "DishGreg",  # Dish + Greg (3 segments: Dish, Gre, g? No — let's check)
        "DreamAiPresentation",
        "LocationSalCapeVerde",
        "DeviceMacMiniServer",
        "AssetSnowboardguards",
        "ConditionDurationForFirstFermentation",
        "InsightEngineKnock",
        "InsightSubstanceOverstimulation",
    ],
)
def test_normalize_node_type_rejects_instance_level_types(bad_name: str) -> None:
    with pytest.raises(ValueError, match="instance-level"):
        normalize_node_type(bad_name)


# --- Legitimate compound types still pass (Plan 28, Stage 1) ---


@pytest.mark.parametrize(
    "good_name,expected",
    [
        ("BodyPart", "BodyPart"),
        ("HealthState", "HealthState"),
        ("FoodItem", "FoodItem"),
        ("MedicalProcedure", "MedicalProcedure"),
        ("CookingMethod", "CookingMethod"),
        ("InterpersonalDynamic", "InterpersonalDynamic"),
        ("Supplement", "Supplement"),
    ],
)
def test_normalize_node_type_accepts_legitimate_compounds(good_name: str, expected: str) -> None:
    assert normalize_node_type(good_name) == expected


# --- Whitelisted compound types pass (Plan 28, Stage 1) ---


@pytest.mark.parametrize(
    "good_name",
    [
        "EventDrivenArchitecture",
        "ActivityLevel",
        "ConditionMonitoring",
        "LocationService",
        "AssetManagement",
        "InsightGeneration",
        "PreparationTechnique",
    ],
)
def test_normalize_node_type_accepts_whitelisted_compounds(good_name: str) -> None:
    normalize_node_type(good_name)


# --- Minimum length rejection (Plan 28, Stage 1) ---


@pytest.mark.parametrize(
    "bad_name",
    [
        "A",
        "X",
    ],
)
def test_normalize_node_type_rejects_too_short(bad_name: str) -> None:
    with pytest.raises(ValueError, match="too short"):
        normalize_node_type(bad_name)


@pytest.mark.parametrize(
    "bad_name",
    [
        "A",
        "X",
    ],
)
def test_normalize_edge_type_rejects_too_short(bad_name: str) -> None:
    with pytest.raises(ValueError, match="too short"):
        normalize_edge_type(bad_name)
