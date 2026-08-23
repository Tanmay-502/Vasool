"""
INTEGRITY RULE (see app/models.py's GroundTruth docstring): the Root Cause
Agent and Recovery Strategy Agent must never read ground_truth_labels — that
table exists purely to score their output after the fact (Day 6, and the
Day 3 spot-check in scripts/calibrate_confidence.py, which is deliberately
OUTSIDE app/agents/ for exactly this reason).

This turns the promise into an invariant CI actually checks, instead of
trusting a comment never to bit-rot.

Uses the `ast` module rather than a plain substring search on purpose: the
modules under app/agents/ have docstrings that *explain* this rule by name
("must never import GroundTruth..."), and a naive `"GroundTruth" in text`
check flags its own explanatory comments as violations. Walking the parsed
syntax tree lets this test flag real references — an import, a class/attr
usage, a `.ground_truth` relationship traversal, or the literal table name
used in a string — while ignoring prose in comments and docstrings.
"""
import ast
import pathlib

AGENTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "agents"

_SENSITIVE_IDENTIFIERS = {"GroundTruth", "ground_truth"}
_SENSITIVE_STRING_LITERALS = {"ground_truth_labels"}


def _references_ground_truth(path: pathlib.Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(node, ast.alias) and node.name in _SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in _SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(node, ast.Constant) and node.value in _SENSITIVE_STRING_LITERALS:
            return True
    return False


def test_agents_package_never_references_ground_truth():
    offenders = [str(p) for p in AGENTS_DIR.rglob("*.py") if _references_ground_truth(p)]

    assert not offenders, (
        "app/agents/ must never import GroundTruth, traverse a .ground_truth "
        "relationship, or reference the ground_truth_labels table — found "
        f"real code references in: {offenders}"
    )


def test_the_integrity_check_itself_catches_a_real_violation(tmp_path):
    """Guards against the checker silently becoming a no-op — e.g. if a
    future edit narrows _SENSITIVE_IDENTIFIERS until nothing matches."""
    violating_file = tmp_path / "would_be_agent.py"
    violating_file.write_text(
        "from app.models import GroundTruth\n\n"
        "def peek(db):\n"
        "    return db.query(GroundTruth).first()\n"
    )
    assert _references_ground_truth(violating_file) is True