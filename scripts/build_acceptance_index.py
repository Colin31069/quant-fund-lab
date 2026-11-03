"""Index acceptance evidence without treating recorded claims as release approval."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CASE = r"(?:P0|Q|S|E|R|L|J)-A\d+"


@dataclass
class CaseIndex:
    case_id: str
    specifications: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    test_reference_review: list[dict] = field(default_factory=list)
    accepted: bool = False

    def to_dict(self) -> dict:
        return {**asdict(self), "status": "evidence_available_requires_review"
                if self.evidence else "evidence_mapping_missing"}


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("evidence reference escapes repository")
    return path


def _test_reference(root: Path, ref: str) -> dict:
    filename, _, node = ref.partition("::")
    path = _inside(root, filename)
    names = node.split("[")[0].split("::") if node else []
    exists = path.is_file()
    if exists and names:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        body = tree.body
        for name in names:
            match = next((item for item in body if isinstance(item,
                (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name), None)
            if match is None:
                exists = False
                break
            body = match.body
    return {"test_node": ref, "file_and_function_exist": exists,
            "execution_verified_by_this_check": False}


def build_index(root: Path) -> dict:
    """Read specifications and evidence; never execute referenced tests or commands."""
    root = root.resolve()
    cases: dict[str, CaseIndex] = {}
    for spec in sorted((root / "src/ARCHITECTURE/plans").glob("*.md")):
        for identity in re.findall(r"^\|\s*(" + CASE + r")\s*\|", spec.read_text(), re.MULTILINE):
            row = cases.setdefault(identity, CaseIndex(identity))
            relative = str(spec.relative_to(root))
            if relative not in row.specifications:
                row.specifications.append(relative)

    def visit(value: object, path: Path, digest: str, locator: str) -> None:
        if isinstance(value, dict):
            identity = value.get("case_id")
            match = re.match(r"^(" + CASE + r")(?:$|_)", identity) if isinstance(identity, str) else None
            if match and match[1] in cases:
                row = cases[match[1]]
                row.evidence.append({"path": str(path.relative_to(root)), "sha256": digest,
                                     "locator": locator, "record": value})
                refs = value.get("tests", [])
                refs = list(refs) if isinstance(refs, list) else []
                if isinstance(value.get("test"), str):
                    refs.append(value["test"])
                row.test_reference_review.extend(_test_reference(root, ref)
                    for ref in refs if isinstance(ref, str))
            for key, item in value.items():
                visit(item, path, digest, locator + "/" + str(key))
        elif isinstance(value, list):
            for number, item in enumerate(value):
                visit(item, path, digest, locator + "/" + str(number))

    for path in sorted((root / "artifacts/acceptance").rglob("acceptance.json")):
        payload = path.read_bytes()
        visit(json.loads(payload), path, hashlib.sha256(payload).hexdigest(), "")
    return {"schema_version": 1, "work_id": "B01", "status": "in_progress",
            "limitations": ["Evidence claims and partial scope require individual review.",
                            "Reference existence does not prove test execution or acceptance."],
            "cases": [cases[key].to_dict() for key in sorted(cases)]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_index(args.repo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(args.output)
    print(f"Indexed {len(payload['cases'])} cases; all remain subject to acceptance review.")


if __name__ == "__main__":
    main()
