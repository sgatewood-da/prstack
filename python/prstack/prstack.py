import asyncio
import contextlib
import functools
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import typing
import webbrowser

import rich
import typer

prstack_home = pathlib.Path.home() / ".prstack"
prstack_pointer = prstack_home / "current"
app = typer.Typer(pretty_exceptions_enable=False)
PR_LINK_CACHE = {}


def get_pointer_value() -> str:
    return prstack_pointer.read_text()


def cmd(cmd: str) -> str:
    print(f">>> {cmd}", file=sys.stderr)
    return subprocess.check_output(shlex.split(cmd)).decode().strip()


async def cmd_async(cmd: str) -> str:
    print(f">>> {cmd}", file=sys.stderr)
    proc = await asyncio.create_subprocess_shell(cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    await proc.wait()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
    data = await proc.stdout.read()
    return data.decode().strip()


def branch_exists(branch: str) -> bool:
    try:
        cmd(f'git rev-parse --verify "{branch}"')
        return True
    except subprocess.CalledProcessError:
        return False


def async_main(func):
    def wrapper(*args, **kwargs):
        return asyncio.run(func(*args, **kwargs))

    return wrapper


@functools.cache
def get_pr_link(ref: str) -> str:
    try:
        return json.loads(cmd(f'gh pr view "{ref}" --json url'))['url']
    except subprocess.CalledProcessError:
        return "(none)"


@functools.cache
def get_default_branch_name() -> str:
    r = re.compile(r'origin/HEAD -> origin/([\w-]+)')
    return r.search(cmd('git branch -r')).group(1)


@functools.cache
def get_default_branch_ref() -> str:
    return f'origin/{get_default_branch_name()}'


class PullRequest:

    def __init__(self, ref: str) -> None:
        self.ref = ref

    def get_link(self) -> str:
        return get_pr_link(self.ref)

    async def create(self, title: str, base: str, body: str) -> None:
        print(await cmd_async(
            f'gh pr create --draft --head "{self.ref}" --title "{title}" --base "{base}" --body \'{body}\''))

    async def edit(self, base: typing.Optional[str], body_prefix: str) -> None:
        current_body = json.loads(cmd(f'gh pr view "{self.ref}" --json body'))['body']
        new_body = body_prefix + current_body.split("## Description")[1]

        with tempfile.NamedTemporaryFile() as tmpfile:
            pathlib.Path(tmpfile.name).write_text(new_body)
            tmpfile.flush()
            base_arg = "" if base is None else f'--base "{base}"'
            print(await cmd_async(f'gh pr edit "{self.ref}" --body-file \'{tmpfile.name}\' {base_arg}'))

    def open(self) -> None:
        link = self.get_link()
        if link != "(none)":
            webbrowser.open(link)
        else:
            print('no PR found :(')

    async def get_state(self) -> str:
        try:
            return json.loads(await cmd_async(f'gh pr view "{self.ref}" --json state'))["state"]
        except subprocess.CalledProcessError:
            return "CLOSED"

    async def ensure(self, title: str, base: str, body: str, disabled: bool) -> None:
        if await self.get_state() == "CLOSED" and not disabled:
            self.hack_skip_ci()
            await self.create(
                title=title,
                base=base,
                body=body
            )
        else:
            await self.edit(
                base=None if disabled else base,
                body_prefix=body
            )

    def hack_skip_ci(self):
        cmd(f'git checkout {self.ref}')
        cmd('git rebase')
        cmd(f'git commit --allow-empty -m "skip ci [skip ci]"')
        cmd(f'git push -f origin {self.ref}')
        cmd(f'git checkout -')

    def submit(self):
        print(cmd(f'gh pr ready {self.ref}'))


class StackItem:

    def __init__(self, subject: str, branch: str, title: str, initial_sha: str, enabled: bool, prev=None,
                 upstream=None) -> None:
        self.subject = subject
        self.branch = branch
        self.title = title
        self.initial_sha = initial_sha
        self.enabled = enabled
        self.prev = prev
        self.upstream = upstream

    def to_dict(self) -> typing.Dict:
        return {
            "subject": self.subject,
            "branch": self.branch,
            "title": self.title,
            "initial_sha": self.initial_sha,
            "enabled": self.enabled,
        }


class Stack:

    def __init__(self, name: str) -> None:
        self.name = name

    def generate_stack_items(self, base: str) -> typing.Generator[StackItem, None, None]:
        for i, sha in enumerate(
                cmd(f"git log --reverse '{base}..HEAD' --pretty=format:'%H'").splitlines()):
            subject = cmd(f'git log --format="%s" -n 1 "{sha}"')
            yield StackItem(
                subject=subject,
                branch=f"prstack-{self.name}-{i + 1}",
                title=f"{i + 1}) {subject}",
                initial_sha=sha,
                enabled=True
            )

    def generate_file(self, base: str) -> None:
        stack_file = self.get_path()
        if stack_file.exists():
            if input("stack already exists. Replace it? [y/N] ") != "y":
                print("exiting")
                exit(1)

        stack_file.parent.mkdir(exist_ok=True)

        stack = [s.to_dict() for s in self.generate_stack_items(base)]
        stack_file.write_text(json.dumps(stack, indent=2))
        cmd(f"jsonnetfmt -i {stack_file.absolute()}")

    def get_path(self) -> pathlib.Path:
        return pathlib.Path.home() / ".prstack" / self.name / "stack.jsonnet"

    def load_json(self) -> str:
        return cmd(f"jsonnet {self.get_path().absolute()}")

    def show(self) -> None:
        rich.print_json(self.load_json())

    def load(self, include_disabled=False) -> typing.List[StackItem]:
        items = [StackItem(**d) for d in json.loads(self.load_json())]
        items = [item for item in items if item.enabled or include_disabled]
        for i, item in enumerate(items):
            item.prev = None if i == 0 else items[i - 1]
            item.upstream = get_default_branch_name() if (item.prev is None or not item.prev.enabled) else item.prev.branch
        return items

    def store(self, items: typing.List[StackItem]) -> None:
        stack_file = self.get_path()
        stack_file.write_text(json.dumps([s.to_dict() for s in items]))
        cmd(f"jsonnetfmt -i {stack_file.absolute()}")

    def extend(self, title: str) -> None:
        items = self.load()
        prev = items[-1]
        num = len(items) + 1
        items.append(StackItem(
            subject=title,
            branch=f"prstack-{self.name}-{len(items) + 1}",
            title=f"{num}) {title}",
            initial_sha=prev.initial_sha,
            enabled=True
        ))
        self.store(items)

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
        branch = self.load(include_disabled=True)[num - 1].branch
        PullRequest(branch).open()

    def open_all_prs(self):
        for item in self.load(include_disabled=True):
            PullRequest(item.branch).open()

    @async_main
    async def ensure_prs(self) -> None:

        async def ensure_pr(i: int, item: StackItem) -> None:
            print("kicked off")
            branch = item.branch
            body_prefix = "".join(self.get_pr_body(i))
            await PullRequest(branch).ensure(
                title=item.title,
                base=item.upstream,
                body=body_prefix,
                disabled=not item.enabled
            )

        await asyncio.gather(*[
            ensure_pr(i, item) for i, item in enumerate(self.load(include_disabled=True))
        ])

    def get_pr_links(self, marker: int) -> typing.Generator:
        for i, item in enumerate(self.load(include_disabled=True)):
            link = PullRequest(item.branch).get_link()
            emoji = '🐢' if i == marker else '🥚'
            yield f"- {emoji} {link}\n"

    def get_pr_body(self, marker: int) -> typing.Generator:
        yield "## Links\n"
        yield from self.get_pr_links(marker)
        yield "\n## Description"

    def rebase_all(self, start: int) -> None:
        for i, item in enumerate(self.load()):
            num = i + 1
            if num < start:
                continue
            print(cmd(f'git checkout "{item.branch}"'))
            print(cmd(f'git fetch origin "{item.upstream}"'))
            print(cmd(f'git rebase'))
            subprocess.run(shlex.split("bash /Users/seangatewood/scripts/aliasscripts/sendit.sh"), capture_output=False,
                           check=True)

    def disable(self, num: int) -> None:
        items = self.load(include_disabled=True)
        items[num - 1].enabled = False
        self.store(items)

    def enable(self, num: int) -> None:
        items = self.load(include_disabled=True)
        items[num - 1].enabled = True
        self.store(items)

    def checkout(self, num: int) -> None:
        branch = self.load(include_disabled=True)[num - 1].branch
        print(cmd(f"git checkout {branch}"))

    def delete(self):
        if input("Are you sure? [y/N] ") != "y":
            print("exiting")
            exit(1)
        shutil.rmtree(self.get_path().parent)

    def submit(self):
        for item in self.load(include_disabled=False):
            PullRequest(item.branch).submit()


@app.command()
def use(stack_name: str):
    prstack_pointer.write_text(stack_name)


@app.command()
def generate(stack_name: str, base: typing.Annotated[str, typer.Argument(default_factory=lambda: get_default_branch_ref)]):
    stack = Stack(stack_name)
    stack.generate_file(base)
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
def cmd_open(num: typing.Annotated[int, typer.Argument(default_factory=lambda: None)],
             stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    if num is not None:
        stack.open_pr(num)
    else:
        stack.open_all_prs()


@app.command()
def rebase_all(start: typing.Annotated[int, typer.Argument(default_factory=lambda: 0)], stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.rebase_all(start)


@app.command()
def enable(num: int, stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.enable(num)
    stack.show()


@app.command()
def disable(num: int, stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.disable(num)
    stack.show()


@app.command()
def checkout(num: int, stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.checkout(num)


@app.command()
def list():
    for file in os.listdir(prstack_home.absolute()):
        if file != prstack_pointer.name:
            print(file)


@app.command(help="extends your stack by adding a new branch on the end")
def extend(title: str, stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.extend(title)
    stack.ensure_branches()
    stack.show()


@app.command()
def delete(stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    stack = Stack(stack_name)
    stack.delete()


@app.command()
def submit(stack_name: typing.Annotated[str, typer.Argument(default_factory=get_pointer_value)]):
    if input("Are you sure you want to submit? [y/N] ") != "y":
        print("exiting")
        exit(1)
    stack = Stack(stack_name)
    stack.submit()


if __name__ == "__main__":
    app()
