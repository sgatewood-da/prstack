import json
import pathlib
import shlex
import subprocess
import typing
import webbrowser
from tempfile import NamedTemporaryFile

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


def get_pr_link(branch: str) -> str:
    try:
        return json.loads(cmd(f'gh pr view "{branch}" --json url'))['url']
    except subprocess.CalledProcessError:
        return "(none)"


def create_pr(branch: str, title: str, base: str, body: str) -> None:
    print(cmd(f'gh pr create --draft --head "{branch}" --title "{title}" --base "{base}" --body \'{body}\''))


def edit_existing_pr(branch: str, base: str, body_prefix: str) -> None:
    current_body = json.loads(cmd(f'gh pr view "{branch}" --json body'))['body']
    new_body = body_prefix + current_body.split("## Description")[1]
    print(cmd(f'gh pr edit "{branch}" --body \'{new_body}\' --base "{base}"'))


class Stack:

    def __init__(self, name: str) -> None:
        self.name = name

    def generate_dicts(self) -> typing.Generator:
        for i, sha in enumerate(cmd("git log --reverse '@{upstream}..HEAD' --pretty=format:'%H'").splitlines()):
            subject = cmd(f'git log --format="%s" -n 1 "{sha}"')
            yield {
                "subject": subject,
                "branch": f"prstack-{self.name}-{i+1}",
                "title": f"{i+1}) {subject}",
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
            upstream = "master" if i == 0 else stack[i - 1]['branch']
            print(cmd(f'git branch -u "origin/{upstream}" "{branch}"'))

            # push branch if it's only local
            if not branch_exists(f"origin/{branch}"):
                print(cmd(f'git push origin "{branch}"'))

    def open_pr(self, num: int) -> None:
        link = get_pr_link(self.load()[num - 1]['branch'])
        if link != "(none)":
            webbrowser.open(link)
        else:
            print('no PR found :(')

    def ensure_prs(self) -> None:
        stack = self.load()
        for i, d in enumerate(stack):
            branch = d['branch']
            try:
                current_pr_state = json.loads(cmd(f'gh pr view "{branch}" --json state'))["state"]
            except subprocess.CalledProcessError:
                current_pr_state = "CLOSED"

            upstream = "master" if i == 0 else stack[i - 1]['branch']
            body_prefix = "".join(self.get_pr_body(i))

            if current_pr_state == "CLOSED":
                create_pr(
                    branch=branch,
                    title=d['title'],
                    base=upstream,
                    body=body_prefix
                )
            else:
                edit_existing_pr(
                    branch=branch,
                    base=upstream,
                    body_prefix=body_prefix)

    def get_pr_links(self, marker: int) -> typing.Generator:
        for i, d in enumerate(self.load()):
            emoji = '🐣' if i == marker else '🥚'
            yield f"- {emoji} {get_pr_link(d['branch'])}\n"

    def get_pr_body(self, marker: int) -> typing.Generator:
        yield "## Links\n"
        yield from self.get_pr_links(marker)
        yield "\n## Description"


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
    stack.ensure_prs()


@app.command()
def open(stack_name: str, num: int):
    stack = Stack(stack_name)
    stack.open_pr(num)


if __name__ == "__main__":
    app()
