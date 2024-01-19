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
    print(f">>> {cmd}")
    return subprocess.check_output(shlex.split(cmd)).decode().strip()


def branch_exists(branch: str) -> bool:
    try:
        cmd(f'git rev-parse --verify "{branch}"')
        return True
    except subprocess.CalledProcessError:
        return False


class Stack:

    def __init__(self, name: str) -> None:
        self.name = name

    def generate_dicts(self) -> typing.Generator:
        for i, sha in enumerate(cmd("git log --reverse '@{upstream}..HEAD' --pretty=format:'%H'").splitlines()):
            subject = cmd(f'git log --format="%s" -n 1 "{sha}"')
            yield {
                "subject": subject,
                "branch": f"prstack-{self.name}-{i}",
                "title": f"{i}) {subject}",
                "initialSha": sha
            }

    def get_path(self) -> pathlib.Path:
        return pathlib.Path.home() / ".prstack" / self.name / "stack.jsonnet"

    def load_json(self) -> str:
        return cmd(f"jsonnet {self.get_path().absolute()}")

    def load(self) -> typing.List[typing.Dict]:
        return json.loads(self.load_json())

    def show(self) -> None:
        rich.print_json(self.load_json())

    def generate_file(self) -> None:
        stack_file = self.get_path()
        if stack_file.exists():
            if input("stack already exists. Replace it? [y/N] ") != "y":
                print("exiting")
                exit(1)

        stack_file.parent.mkdir(exist_ok=True)

        stack = list(self.generate_dicts())
        stack_file.write_text(json.dumps(stack))
        cmd(f"jsonnetfmt -i {stack_file.absolute()}")

    def ensure_branches(self) -> None:
        stack = self.load()
        for i, d in enumerate(stack):
            branch = d['branch']

            # if branch doesn't exist locally, create it from the initialSha
            if not branch_exists(branch):
                print(cmd(f'git branch "{branch}" "{d["initialSha"]}"'))

            # set upstream branch
            upstream = "master" if i == 0 else stack[i-1]['branch']
            print(cmd(f'git branch -u "origin/{upstream}" "{branch}"'))

            # push branch if it's only local
            if not branch_exists(f"origin/{branch}"):
                print(cmd(f'git push origin "{branch}"'))



@app.command()
def generate(stack_name: str):
    stack = Stack(stack_name)
    stack.generate_file()
    stack.show()


@app.command()
def show(stack_name: str):
    stack = Stack(stack_name)
    stack.show()


@app.command()
def sync(stack_name: str):
    stack = Stack(stack_name)
    stack.ensure_branches()


if __name__ == "__main__":
    app()
