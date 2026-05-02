import argparse
import os
import sys

from dotenv import load_dotenv

from memory import get_client, GLOBAL_USER_ID, project_user_id
from project import get_project_id

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="cerebral CLI")
    subparsers = parser.add_subparsers(dest="command")

    save_parser = subparsers.add_parser("save-session", help="Save end-of-session learnings")
    save_parser.add_argument("--summary", default="", help="Session summary text")
    save_parser.add_argument("--project", default="", help="Project name override")

    inspect_parser = subparsers.add_parser("inspect", help="Show all memories ranked by retrieval count")
    inspect_parser.add_argument("--scope", choices=["global", "project", "both"], default="both")

    args = parser.parse_args()

    if args.command == "save-session":
        summary = args.summary or _read_stdin()
        if not summary.strip():
            print("No summary provided, skipping.")
            sys.exit(0)

        project_name = args.project or get_project_id(os.getcwd())
        mem0 = get_client()
        mem0.add([{"role": "user", "content": summary}], user_id=GLOBAL_USER_ID)
        mem0.add([{"role": "user", "content": summary}], user_id=project_user_id(project_name))
        print(f"Session learnings saved (project: {project_name})")
    elif args.command == "inspect":
        _cmd_inspect(args)
    else:
        parser.print_help()


def _format_inspect_table(rows: list[dict]) -> str:
    def _meta(r):
        return r.get("metadata") or {}

    def _count(r):
        return int(_meta(r).get("retrieval_count", 0))

    def _last(r):
        return _meta(r).get("last_retrieved_at") or "-"

    def _type(r):
        return _meta(r).get("cerebral_type", "untyped")

    def _scope(r):
        return "project" if str(r.get("user_id", "")).startswith("project:") else "global"

    rows = sorted(rows, key=lambda r: -_count(r))
    lines = [f"{'count':>5}  {'last_retrieved':<32}  {'type':<12}  {'scope':<7}  text"]
    lines.append("-" * 110)
    for r in rows:
        text = r.get("memory", "")
        if len(text) > 60:
            text = text[:57] + "..."
        lines.append(f"{_count(r):>5}  {_last(r):<32}  {_type(r):<12}  {_scope(r):<7}  {text}")
    return "\n".join(lines)


def _cmd_inspect(args):
    mem0 = get_client()
    rows = []
    if args.scope in ("global", "both"):
        rows.extend(mem0.get_all(filters={"user_id": GLOBAL_USER_ID}).get("results", []))
    if args.scope in ("project", "both"):
        project_name = get_project_id(os.getcwd())
        rows.extend(mem0.get_all(filters={"user_id": project_user_id(project_name)}).get("results", []))
    print(_format_inspect_table(rows))


def _read_stdin() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


if __name__ == "__main__":
    main()
