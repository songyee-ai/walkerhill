"""저장된 응답을 새 요청 모양으로 바꾼다: 요청에서 `scenario_id` 를 빼고 해시를 다시 낸다 (11-18, T121. docs/FORMATS.md 10.3절).

    uv run python -m tools.rehash_answers                 # 이 폴더의 engine/samples/runs 와 private/ 아래 모두
    uv run python -m tools.rehash_answers <폴더> [<폴더> …]  # 가리킨 폴더 아래만
    uv run python -m tools.rehash_answers --check          # 바꾸지 않고 바꿀 것만 센다

답의 내용(`response`, `raw_text`, `usage`, `created_at`)은 건드리지 않는다. 바꾸는 것은 셋이다.
- `llm/`, `llm_rejected/` 의 파일: 요청의 `scenario_id` 를 지우고, `request_hash` 와 파일 이름을 새 해시로 바꾼다.
- 그 폴더 옆의 `ledger.csv`: `request_hash` 칸의 옛 해시를 새 해시로 바꾼다 (다른 글자는 그대로다).
이미 바꾼 파일은 건너뛰므로 여러 번 돌려도 된다. LLM 을 부르지 않는다.
받아 둔 압축 파일은 풀어서 돌린다. 돌리기 전에 폴더를 베껴 두면 되돌릴 수 있다.
"""

import argparse
import json
import sys
from pathlib import Path

from engine.formats.io import write_json
from engine.formats.run import compute_request_hash

ANSWER_FOLDERS = ("llm", "llm_rejected")
# 적지 않으면 보는 곳. private/ 는 통째로 훑는다 (실행 폴더, 검증의 답, 화면이 만든 예시 사본 private/try-example).
DEFAULT_FOLDERS = ("engine/samples/runs", "private")


def rehash_folder(folder: Path, write: bool = True) -> dict[str, str]:
    """`llm/` 이나 `llm_rejected/` 하나를 바꾼다. 돌려주는 것은 옛 해시 → 새 해시.

    새 해시의 파일이 이미 있고 내용이 다르면 아무것도 쓰지 않고 멈춘다 (한 폴더 안에서는 상황이 하나라 생기지 않아야 한다).
    """
    planned: dict[Path, tuple[Path, dict]] = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        request = data.get("request")
        if not isinstance(request, dict) or "scenario_id" not in request:
            continue
        del request["scenario_id"]
        data["request_hash"] = compute_request_hash(data["provider"], data["model"], request)
        planned[path] = (folder / f"{data['request_hash']}.json", data)
    # 쓰기 전에 모두 본다: 새 이름이 서로 겹치거나, 이미 바꾼 파일과 겹치는데 내용이 다르면 멈춘다.
    seen: dict[Path, dict] = {}
    for path, (target, data) in planned.items():
        if target in seen:
            other = seen[target]
        elif target.exists() and target not in planned:
            other = json.loads(target.read_text(encoding="utf-8"))
        else:
            other = None
        if other is not None and other != data:
            raise ValueError(f"{path} 를 바꾸면 {target.name} 이 되는데, 내용이 다른 같은 이름의 파일이 있다")
        seen[target] = data
    if write:
        for path, (target, data) in planned.items():
            write_json(target, data)
            if path != target:
                path.unlink()
    return {path.stem: target.stem for path, (target, _) in planned.items()}


def rehash_ledger(path: Path, renamed: dict[str, str], write: bool = True) -> int:
    """원장의 옛 해시를 새 해시로 바꾼다. 바꾼 줄 수를 돌려준다. 해시 말고는 글자 하나 바꾸지 않는다."""
    raw = path.read_bytes().decode("utf-8")
    lines = raw.split("\n")
    changed = 0
    for index, line in enumerate(lines):
        new = line
        for old_hash, new_hash in renamed.items():
            new = new.replace(f",{old_hash},", f",{new_hash},")
        if new != line:
            lines[index] = new
            changed += 1
    if write and changed:
        path.write_bytes("\n".join(lines).encode("utf-8"))
    return changed


def rehash_tree(top: Path, write: bool = True) -> tuple[int, int]:
    """`top` 아래의 모든 `llm/`, `llm_rejected/` 와 그 옆의 원장을 바꾼다. (바꾼 답, 바꾼 원장 줄)을 돌려준다."""
    answers = lines = 0
    parents = sorted({p.parent for name in ANSWER_FOLDERS for p in top.rglob(name) if p.is_dir()})
    for parent in parents:
        renamed: dict[str, str] = {}
        for name in ANSWER_FOLDERS:
            if (parent / name).is_dir():
                renamed |= rehash_folder(parent / name, write)
        answers += len(renamed)
        ledger = parent / "ledger.csv"
        if renamed and ledger.is_file():
            lines += rehash_ledger(ledger, renamed, write)
    return answers, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.rehash_answers", description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="*", type=Path, help="바꿀 폴더 (적지 않으면 이 폴더의 실행 폴더들)")
    parser.add_argument("--check", action="store_true", help="바꾸지 않고 바꿀 것만 센다. 바꿀 것이 있으면 끝 값이 1 이다")
    args = parser.parse_args(argv)
    folders = args.folders or [Path(name) for name in DEFAULT_FOLDERS]
    total = 0
    for folder in folders:
        if not folder.is_dir():
            if args.folders:
                print(f"폴더가 없다: {folder}", file=sys.stderr)
                return 1
            continue
        try:
            answers, lines = rehash_tree(folder, write=not args.check)
        except ValueError as exc:
            print(f"바꾸지 못했다: {exc}", file=sys.stderr)
            return 1
        total += answers
        word = "바꿀" if args.check else "바꾼"
        print(f"{folder}: {word} 답 {answers}개, 원장 {lines}줄")
    return 1 if args.check and total else 0


if __name__ == "__main__":
    sys.exit(main())
