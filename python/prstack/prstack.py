import json
import pathlib
import shlex
import subprocess
import typing

import rich
import typer

prstack_home = pathlib.Path.home() / ".prstack"
app = typer.Typer()


def cmd(cmd: str) -> str:
    return subprocess.check_output(shlex.split(cmd)).decode().strip()


def get_stack_dicts(stack_name: str) -> typing.Generator:
    for i, sha in enumerate(cmd("git log --reverse '@{upstream}..HEAD' --pretty=format:'%H'").splitlines()):
        subject = cmd(f'git log --format="%s" -n 1 "{sha}"')
        yield {
            "subject": subject,
            "branch": f"prstack-{stack_name}-{i}",
            "title": f"{i}) {subject}",
            "initialSha": sha
        }


def get_stack_path(stack_name: str) -> pathlib.Path:
    return pathlib.Path.home() / ".prstack" / stack_name / "stack.jsonnet"


def show_stack(stack_name):
    rich.print_json(cmd(f"jsonnet {get_stack_path(stack_name).absolute()}"))


@app.command()
def generate(stack_name: str):
    stack_file = get_stack_path(stack_name)
    stack_file.parent.mkdir(exist_ok=True)

    stack = list(get_stack_dicts(stack_name))
    stack_file.write_text(json.dumps(stack))
    cmd(f"jsonnetfmt -i {stack_file.absolute()}")
    show_stack(stack_name)


@app.command()
def show(stack_name: str):
    show_stack(stack_name)


if __name__ == "__main__":
    app()
