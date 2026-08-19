"""Entity name and type normalization utilities.

These functions are called in the adapter layer BEFORE database lookups,
ensuring consistent matching regardless of how the LLM formats names.
"""

from __future__ import annotations

import re

_VALID_NODE_TYPE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_VALID_EDGE_TYPE = re.compile(r"^[A-Z]([A-Z0-9_]*[A-Z0-9])?$")
_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9_\- ]")
_MAX_TYPE_NAME_LENGTH = 60
_MAX_TYPE_WORD_COUNT = 5
_MIN_TYPE_NAME_LENGTH = 2
_PASCAL_WORD_BOUNDARY = re.compile(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")

# Gemini Flash artifacts: internal function-call syntax leaking into type names
_TOOL_CALL_ARTIFACT = re.compile(
    r"(functiondefault|calldefault|ApicreateOr|UpdateNode|UpdateEdge|"
    r"createOrUpdate|defaultApi|endcall|"
    r"functionName|"  # JS method name leakage (I5: BrandfunctionNameCreateOrUpdateNode)
    r"Updating\w*Id\d|"
    r"<think>|</think>|<tool_call>|</tool_call>|<function=|<parameter=)",
    re.IGNORECASE,
)

# Common base types that, when followed by 1+ PascalCase segments, indicate
# instance-level type names (e.g., DishGreg, LocationSalCapeVerde)
_COMMON_BASE_TYPES = {
    "Asset",
    "Dish",
    "Dream",
    "Event",
    "Insight",
    "Location",
    "Device",
    "Activity",
    "Condition",
    "Mentalstate",
    "Utensil",
    "Preparation",
    "Specification",
}

# Legitimate compound types starting with a base type word — bypass instance check
_COMPOUND_TYPE_WHITELIST = {
    "EventDrivenArchitecture",
    "ActivityLevel",
    "ConditionMonitoring",
    "LocationService",
    "AssetManagement",
    "InsightGeneration",
    "PreparationTechnique",
}

_KNOWN_ACRONYMS: list[str] = [
    "API",
    "SQL",
    "AI",
    "ML",
    "LLM",
    "HTTP",
    "REST",
    "gRPC",
    "OAuth",
    "SSO",
    "JWT",
    "5-HT",
]


def canonicalize_name(name: str) -> tuple[str, list[str]]:
    """Normalize an entity name and extract any parenthetical aliases.

    Returns (canonical_name, aliases).
    """
    # 1. Strip whitespace
    name = name.strip()
    if not name:
        return (name, [])

    # 2. Extract parenthetical aliases (single parenthetical at end)
    aliases: list[str] = []
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", name)
    if m:
        name = m.group(1).strip()
        aliases.append(m.group(2).strip())

    # 3. Title case normalization — only when input is all-lowercase
    if name == name.lower():
        name = name.title()
        # Restore known acronyms (word boundaries prevent matching inside words
        # e.g., "AI" must not match "ai" in "Main" or "Container")
        for acronym in _KNOWN_ACRONYMS:
            pattern = re.compile(r"\b" + re.escape(acronym) + r"\b", re.IGNORECASE)
            name = pattern.sub(acronym, name)

    # 4. Collapse internal whitespace
    name = re.sub(r"\s+", " ", name).strip()

    return (name, aliases)


def normalize_edge_type(name: str) -> str:
    """Convert any edge type name to SCREAMING_SNAKE_CASE."""
    if _TOOL_CALL_ARTIFACT.search(name):
        raise ValueError(f"Edge type name contains tool-call artifact: '{name[:50]}'")
    # Strip invalid characters before processing (preserve hyphens for conversion)
    name = _INVALID_CHARS.sub("", name).strip()
    if not name:
        raise ValueError("Edge type name is empty after stripping invalid characters")

    # Reject names shorter than minimum length
    if len(name) < _MIN_TYPE_NAME_LENGTH:
        raise ValueError(f"Edge type name too short ({len(name)} chars, min {_MIN_TYPE_NAME_LENGTH})")

    # Reject tool-call artifacts (Gemini Flash internal function-call leakage)
    if _TOOL_CALL_ARTIFACT.search(name):
        raise ValueError(f"Edge type name contains tool-call artifact: '{name[:50]}'")

    # Reject excessive length (LLM reasoning leaks)
    if len(name) > _MAX_TYPE_NAME_LENGTH:
        raise ValueError(
            f"Edge type name too long ({len(name)} chars, max {_MAX_TYPE_NAME_LENGTH}): " f"'{name[:50]}...'"
        )

    # Reject names with too many PascalCase segments (reasoning contamination)
    word_count = len(_PASCAL_WORD_BOUNDARY.findall(name))
    if word_count > _MAX_TYPE_WORD_COUNT:
        raise ValueError(
            f"Edge type name has too many segments ({word_count}, max {_MAX_TYPE_WORD_COUNT}): " f"'{name[:50]}...'"
        )

    # Replace hyphens with underscores
    name = name.replace("-", "_")
    # Insert underscore before uppercase letters preceded by lowercase or digit (PascalCase split)
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    # Replace spaces with underscores
    name = name.replace(" ", "_")
    # Uppercase everything
    name = name.upper()
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")

    # Final validation
    if not _VALID_EDGE_TYPE.match(name):
        raise ValueError(f"Edge type '{name}' does not match SCREAMING_SNAKE pattern after normalization")
    return name


def _is_instance_level_node_type(name: str) -> bool:
    """Check if a node type looks like a base type + instance name concatenation."""
    if name in _COMPOUND_TYPE_WHITELIST:
        return False
    segments = _PASCAL_WORD_BOUNDARY.findall(name)
    if len(segments) < 2:
        return False
    # Check if the first segment is a known base type
    first_segment = segments[0]
    return first_segment in _COMMON_BASE_TYPES


def normalize_node_type(name: str) -> str:
    """Ensure PascalCase for node type names."""
    if _TOOL_CALL_ARTIFACT.search(name):
        raise ValueError(f"Node type name contains tool-call artifact: '{name[:50]}'")
    # Strip invalid characters before any other processing
    name = _INVALID_CHARS.sub("", name).strip()
    if not name:
        raise ValueError("Node type name is empty after stripping invalid characters")

    # Reject names shorter than minimum length
    if len(name) < _MIN_TYPE_NAME_LENGTH:
        raise ValueError(f"Node type name too short ({len(name)} chars, min {_MIN_TYPE_NAME_LENGTH})")

    # Reject tool-call artifacts (Gemini Flash internal function-call leakage)
    if _TOOL_CALL_ARTIFACT.search(name):
        raise ValueError(f"Node type name contains tool-call artifact: '{name[:50]}'")

    # Reject instance-level type names (e.g., DishGreg, LocationSalCapeVerde)
    if _is_instance_level_node_type(name):
        raise ValueError(f"Node type name looks like instance-level (base type + instance name): '{name[:50]}'")

    # Reject excessive length (LLM reasoning leaks)
    if len(name) > _MAX_TYPE_NAME_LENGTH:
        raise ValueError(
            f"Node type name too long ({len(name)} chars, max {_MAX_TYPE_NAME_LENGTH}): " f"'{name[:50]}...'"
        )

    # Reject names with too many PascalCase segments (reasoning contamination)
    word_count = len(_PASCAL_WORD_BOUNDARY.findall(name))
    if word_count > _MAX_TYPE_WORD_COUNT:
        raise ValueError(
            f"Node type name has too many segments ({word_count}, max {_MAX_TYPE_WORD_COUNT}): " f"'{name[:50]}...'"
        )

    # Check if it has separators (underscores, spaces, or hyphens)
    has_separators = "_" in name or " " in name or "-" in name

    if has_separators:
        # Split on separators and capitalize each part
        parts = re.split(r"[_ \-]+", name)
        result = "".join(part.capitalize() for part in parts if part)
    elif name == name.upper() and len(name) > 1:
        # ALL_CAPS single word with no separators → preserve as-is
        result = name
    elif name == name.lower() and len(name) > 0:
        # Single lowercase word → capitalize to PascalCase
        result = name.capitalize()
    else:
        # Already PascalCase or mixed case → keep as-is
        result = name

    # Ensure first character is uppercase
    if result and result[0].islower():
        result = result[0].upper() + result[1:]

    # Final validation
    if not _VALID_NODE_TYPE.match(result):
        raise ValueError(f"Node type '{result}' does not match PascalCase pattern after normalization")
    return result


def names_are_similar(a: str, b: str, threshold: float = 0.6) -> bool:
    """Pure-Python string similarity check for use in the mock adapter.

    Checks exact match (case-insensitive), then word-level containment.
    Requires the shorter name to have at least 2 words to prevent
    false positives like "Serotonin" matching "Serotonin Receptor".

    For single-word containment (e.g., "Kafka" vs "Apache Kafka"),
    the PostgreSQL adapter uses trigram similarity instead. This function
    is intentionally conservative to avoid false merges in mock tests.
    """
    a_lower = a.lower()
    b_lower = b.lower()

    # 1. Exact match after lowering
    if a_lower == b_lower:
        return True

    # 2. Word-level containment: all words of shorter are in longer,
    #    but only when the shorter name has 2+ words to avoid false
    #    positives from single-word matches (e.g., "Serotonin" should
    #    NOT match "Serotonin Receptor")
    a_words = set(a_lower.split())
    b_words = set(b_lower.split())
    if not a_words or not b_words:
        return False

    shorter, longer = (a_words, b_words) if len(a_words) <= len(b_words) else (b_words, a_words)
    return bool(shorter <= longer and len(shorter) >= 2)
