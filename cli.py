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
    else:
        parser.print_help()


def _read_stdin() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


if __name__ == "__main__":
    main()
