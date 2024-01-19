import json
import pathlib
import shlex
import subprocess
import typing
import webbrowser

import rich
import typer

prstack_home = pathlib.Path.home() / ".prstack"
prstack_pointer = prstack_home / "current"
app = typer.Typer(pretty_exceptions_enable=False)


def get_pointer_value() -> str:
    return prstack_pointer.read_text()


def cmd(cmd: str) -> str:
    print(f">>> {cmd}")
    return subprocess.check_output(shlex.split(cmd)).decode().strip()


def branch_exists(branch: str) -> bool:
    try:
        cmd(f'git rev-parse --verify "{branch}"')
        return True
    except subprocess.CalledProcessError:
        return False


class PullRequest:

    def __init__(self, ref: str) -> None:
        self.ref = ref

    def get_link(self) -> str:
        try:
            return json.loads(cmd(f'gh pr view "{self.ref}" --json url'))['url']
        except subprocess.CalledProcessError:
            return "(none)"

    def create(self, title: str, base: str, body: str) -> None:
        print(cmd(f'gh pr create --draft --head "{self.ref}" --title "{title}" --base "{base}" --body \'{body}\''))

    def edit(self, base: str, body_prefix: str) -> None:
        current_body = json.loads(cmd(f'gh pr view "{self.ref}" --json body'))['body']
        new_body = body_prefix + current_body.split("## Description")[1]
        print(cmd(f'gh pr edit "{self.ref}" --body \'{new_body}\' --base "{base}"'))

    def open(self) -> None:
        link = self.get_link()
        if link != "(none)":
            webbrowser.open(link)
        else:
            print('no PR found :(')

    def get_state(self) -> str:
        try:
            return json.loads(cmd(f'gh pr view "{self.ref}" --json state'))["state"]
        except subprocess.CalledProcessError:
            return "CLOSED"

    def ensure(self, title: str, base: str, body: str) -> None:
        if self.get_state() == "CLOSED":
            self.create(
                title=title,
                base=base,
                body=body
            )
        else:
            self.edit(
                base=base,
                body_prefix=body
            )


class StackItem:

    def __init__(self, subject: str, branch: str, title: str, initial_sha: str, prev=None, upstream=None) -> None:
        self.subject = subject
        self.branch = branch
        self.title = title
        self.initial_sha = initial_sha
        self.prev = prev
        self.upstream = upstream

    def to_dict(self) -> typing.Dict:
        return {
            "subject": self.subject,
            "branch": self.branch,
            "title": self.title,
            "initial_sha": self.initial_sha
        }


class Stack:

    def __init__(self, name: str) -> None:
        self.name = name

    def generate_stack_items(self) -> typing.Generator[StackItem, None, None]:
        for i, sha in enumerate(cmd("git log --reverse '@{upstream}..HEAD' --pretty=format:'%H'").splitlines()):
            subject = cmd(f'git log --format="%s" -n 1 "{sha}"')
            yield StackItem(
                subject=subject,
                branch=f"prstack-{self.name}-{i + 1}",
                title=f"{i + 1}) {subject}",
                initial_sha=sha
            )

    def get_path(self) -> pathlib.Path:
        return pathlib.Path.home() / ".prstack" / self.name / "stack.jsonnet"

    def load_json(self) -> str:
        return cmd(f"jsonnet {self.get_path().absolute()}")

    def load(self) -> typing.List[StackItem]:
        items = [StackItem(**d) for d in json.loads(self.load_json())]
        for i, item in enumerate(items):
            item.prev = None if i == 0 else items[i-1]
            item.upstream = "master" if i == 0 else item.prev.branch
        return items

    def show(self) -> None:
        rich.print_json(self.load_json())

    def generate_file(self) -> None:
        stack_file = self.get_path()
        if stack_file.exists():
            if input("stack already exists. Replace it? [y/N] ") != "y":
                print("exiting")
                exit(1)

        stack_file.parent.mkdir(exist_ok=True)

        stack = [s.to_dict() for s in self.generate_stack_items()]
        stack_file.write_text(json.dumps(stack))
        cmd(f"jsonnetfmt -i {stack_file.absolute()}")

    def ensure_branches(self) -> None:
        for item in self.load():
            branch = item.branch

            # if branch doesn't exist locally, create it from the initialSha
            if not branch_exists(branch):
                print(cmd(f'git branch "{branch}" "{item.initial_sha}"'))

            print(cmd(f'git branch -u "origin/{item.upstream}" "{branch}"'))

            # push branch if it's only local
            if not branch_exists(f"origin/{branch}"):
                print(cmd(f'git push origin "{branch}"'))

    def open_pr(self, num: int) -> None:
        branch = self.load()[num - 1].branch
        PullRequest(branch).open()

    def ensure_prs(self) -> None:
        for i, item in enumerate(self.load()):
            branch = item.branch

            body_prefix = "".join(self.get_pr_body(i))
            PullRequest(branch).ensure(
                title=item.title,
                base=item.upstream,
                body=body_prefix
            )

    def get_pr_links(self, marker: int) -> typing.Generator:
        for i, item in enumerate(self.load()):
            emoji = '🐣' if i == marker else '🥚'
            link = PullRequest(item.branch).get_link()
            yield f"- {emoji} {link}\n"

    def get_pr_body(self, marker: int) -> typing.Generator:
        yield "## Links\n"
        yield from self.get_pr_links(marker)
        yield "\n## Description"

    def rebase_all(self) -> None:
        for item in self.load():
            print(cmd(f'git checkout "{item.branch}"'))
            print(cmd(f'git fetch origin "{item.upstream}"'))
            print(cmd(f'git rebase'))
            subprocess.run(shlex.split("bash /Users/seangatewood/scripts/aliasscripts/sendit.sh"), capture_output=False,
                           check=True)


@app.command()
def use(stack_name: str):
    prstack_pointer.write_text(stack_name)


@app.command()
def generate(stack_name: str):
    stack = Stack(stack_name)
    stack.generate_file()
    stack.show()


@app.command()
def show(stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.show()


@app.command()
def sync(stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.ensure_branches()
    stack.ensure_prs()


@app.command(name="open")
def cmd_open(num: int, stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.open_pr(num)


@app.command()
def rebase_all(stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.rebase_all()


if __name__ == "__main__":
    app()
