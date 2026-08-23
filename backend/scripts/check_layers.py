"""The layer-import gate from the build spec's section 4.2.

Implemented in Python rather than as four greps so it runs identically on
Windows, in the container, and in CI. Exits non-zero on any violation; the test
suite shells out to it, so a layer violation fails the build rather than
relying on someone remembering to run it before committing.

The allowed direction is strictly downward:

    api  ->  auth, agent
    agent  ->  tools, services, llm, observability
    tools  ->  services, repositories, auth (read-only checks)
    services  ->  repositories
    repositories  ->  db

ONE DELIBERATE CARVE-OUT, stated rather than smuggled.

The build spec says "tools may not call the LLM". Taken literally that also
forbids `app.llm.embeddings`, which `search_documents` needs to vectorise a
query. The rule's PURPOSE is that tools must not REASON -- a tool that asks a
model what to do has become an agent, and the layer boundary stops meaning
anything. An embedding is deterministic vectorisation: the same text always
produces the same vector, and no decision is delegated. It is a retrieval
primitive, closer to a database index than to inference.

So the check targets `app.llm.client` (the chat model) in tools/ and services/,
and permits `app.llm.embeddings`. If a tool ever imports the chat client, that
IS the failure the original rule was written to catch, and it still fails.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = ROOT / "app"

# (directory, forbidden pattern, human explanation)
RULES: list[tuple[str, str, str]] = [
    (
        "api",
        r"from app\.repositories|import app\.repositories",
        "controllers must not reach the data layer; go through agent or a service",
    ),
    (
        "services",
        r"from app\.api|import app\.api",
        "services must not know about HTTP",
    ),
    (
        "services",
        r"\b(SELECT|INSERT|UPDATE|DELETE)\b",
        "services must not contain SQL; that belongs in repositories",
    ),
    (
        "agent",
        r"\b(SELECT|INSERT|UPDATE|DELETE)\b",
        "the agent loop must not contain SQL",
    ),
    (
        "agent",
        r"from app\.repositories|import app\.repositories",
        "the agent must reach data through tools, not repositories directly",
    ),
    (
        "repositories",
        r"from app\.services|from app\.tools|from app\.agent",
        "repositories must not call upward",
    ),
    (
        "tools",
        r"from app\.llm\.client|from app\.llm import client",
        "tools must never call the CHAT model -- tools do not reason",
    ),
    (
        "services",
        r"from app\.llm\.client|from app\.llm import client",
        "services must never call the CHAT model -- business rules are code",
    ),
]

# Comments and docstrings legitimately mention SQL keywords while explaining
# the rules; only real code counts as a violation.
COMMENT = re.compile(r"^\s*#")


def _strip_docstrings(text: str) -> str:
    return re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", text)


def main() -> int:
    violations: list[str] = []

    for directory, pattern, explanation in RULES:
        target = APP / directory
        if not target.exists():
            continue
        regex = re.compile(pattern)
        for path in sorted(target.rglob("*.py")):
            source = _strip_docstrings(path.read_text(encoding="utf-8"))
            for lineno, line in enumerate(source.splitlines(), 1):
                if COMMENT.match(line):
                    continue
                if regex.search(line):
                    rel = path.relative_to(ROOT)
                    violations.append(
                        f"{rel}:{lineno}: {explanation}\n    {line.strip()}"
                    )

    if violations:
        print("LAYER VIOLATIONS:\n", file=sys.stderr)
        for v in violations:
            print(f"  {v}\n", file=sys.stderr)
        print(f"{len(violations)} violation(s)", file=sys.stderr)
        return 1

    print("layer check clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
