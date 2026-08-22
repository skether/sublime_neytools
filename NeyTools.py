import base64
import itertools
import os
import re
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from pathlib import Path
from shutil import which
from types import EllipsisType
from typing import Annotated, ClassVar, NamedTuple, Self, SupportsIndex, overload, override

import sublime
import sublime_plugin
import yaml

try:
    import pydantic
except (ModuleNotFoundError, ImportError):
    sys.path.insert(0, str(Path(sublime.packages_path(), "sublime_neytools/libs")))
    import pydantic

# For Development Purposes
# Used to enable logging and development tools
NT_DEVMODE = False
package_git_head = Path(sublime.packages_path(), "sublime_neytools/.git/HEAD")
if package_git_head.exists():
    with package_git_head.open("rt") as head:
        if head.read().strip() != "ref: refs/heads/main":
            NT_DEVMODE = True


def plugin_loaded() -> None:
    GlobalState.load_global_state()


class GlobalState:
    cmd_available = False

    powershell_available = False
    pwsh_available = False
    powershell_use_pwsh = False

    wsl_available = False

    windows_terminal_available = False

    plugin_settings = None

    python_use_wsl = False

    @staticmethod
    def load_global_state():
        GlobalState.cmd_available = which("cmd") is not None
        GlobalState.powershell_available = which("powershell") is not None
        GlobalState.pwsh_available = which("pwsh") is not None
        GlobalState.wsl_available = which("wsl") is not None
        GlobalState.windows_terminal_available = which("wt") is not None

        GlobalState.plugin_settings = sublime.load_settings("NeyTools.sublime-settings")

        GlobalState.python_use_wsl = GlobalState.wsl_available and (GlobalState.plugin_settings.get("python_use_wsl", "native") == "wsl")
        GlobalState.powershell_use_pwsh = GlobalState.pwsh_available and (GlobalState.plugin_settings.get("powershell_prefer_pwsh", False))

    @staticmethod
    def save_plugin_settings():
        sublime.save_settings("NeyTools.sublime-settings")


# SETTING COMMANDS
class NeyToolsSettingPythonEnvironmentCommand(sublime_plugin.ApplicationCommand):
    """ Used for selecting the Python environment. """

    def run(self, env):
        GlobalState.python_use_wsl = env == "wsl"
        GlobalState.plugin_settings.set("python_use_wsl", GlobalState.python_use_wsl)
        GlobalState.save_plugin_settings()

    def is_visible(self, env):
        return GlobalState.wsl_available or not (env == "wsl")

    def is_enabled(self, env):
        return GlobalState.wsl_available or not (env == "wsl")

    def is_checked(self, env):
        return GlobalState.python_use_wsl == (env == "wsl")


class NeyToolsSettingPowerShellEnvironmentCommand(sublime_plugin.ApplicationCommand):
    """ Used for selecting the PowerShell environment. """

    def run(self, env):
        GlobalState.powershell_use_pwsh = (env == "pwsh")
        GlobalState.plugin_settings.set("powershell_prefer_pwsh", GlobalState.powershell_use_pwsh)
        GlobalState.save_plugin_settings()

    def is_visible(self, env):
        return GlobalState.pwsh_available or not (env == "pwsh")

    def is_enabled(self, env):
        return GlobalState.pwsh_available or not (env == "pwsh")

    def is_checked(self, env):
        return GlobalState.powershell_use_pwsh == (env == "pwsh")


class FormatDict(dict[str, str]):
    def __init__(self, command_instance: __CommandBase) -> None:
        super().__init__()

        self.command_instance: __CommandBase = command_instance
        self.proxies: dict[str, Callable[[], Path | str]] = {
            'directory': lambda: self.command_instance.file_path.parent if self.command_instance.file_path else '',
            'drive': lambda: self.command_instance.file_path.drive if self.command_instance.file_path else '',

            'filename': lambda: self.command_instance.file_path.name if self.command_instance.file_path else '',
            'file_name': lambda: self.command_instance.file_path.name if self.command_instance.file_path else '',
            'filepath': lambda: self.command_instance.file_path if self.command_instance.file_path else '',
            'file_path': lambda: self.command_instance.file_path if self.command_instance.file_path else '',

            'file_text': lambda: self.command_instance.view.substr(sublime.Region(0, self.command_instance.view.size())),
            'file_text_base64': lambda: base64.b64encode(self.command_instance.view.substr(sublime.Region(0, self.command_instance.view.size())).encode(self.command_instance.view.encoding().replace('Undefined', 'utf-8'))).decode('utf-8'),

            'git_root': lambda: self.command_instance.git_root if (self.command_instance.git_root is not None) and (self.command_instance.git_root != ...) else ''
        }

    @override
    def __getitem__(self, key: str) -> str:
        if key in self.proxies:
            return str(self.proxies[key]())
        else:
            return super().__getitem__(key)


class Runtime(ABC):
    __registry: dict[str, type[Runtime]] = {}

    fallback_runtime: type[Runtime] | None = None

    def __init_subclass__(cls: type[Runtime], *args: object, name: str | tuple[str, ...], **kwargs: object) -> None:
        super().__init_subclass__(*args, **kwargs)
        if isinstance(name, str):
            Runtime.__registry[name] = cls
        else:
            for n in (str(n).lower() for n in name):
                Runtime.__registry[n] = cls

    def __init__(self) -> None:
        if type(self) is Runtime:
            raise TypeError("The base Runtime class should not be instantiated! Use a valid subclass instead!")

    @staticmethod
    def get_by_name(name: str, default: type[Runtime] | None = None) -> type[Runtime]:
        name = str(name).lower()

        runtime = Runtime.__registry.get(name, None)
        if runtime is None:
            if default is None:
                raise ValueError(f"{name} is an invalid Runtime type!")
            return default

        if not runtime.enabled():
            if default is None:
                raise ValueError(f"Runtime of type ({name}) is not enabled!")
            return default

        return runtime

    @staticmethod
    @abstractmethod
    def enabled() -> bool:
        ...

    @classmethod
    @abstractmethod
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = False) -> Iterable[str]:
        ...

    @classmethod
    def execute(cls, command: Iterable[str], extra_env: dict[str, str] | None = None, path: Path | None = None, wait_for_user: bool = True) -> None:
        args = cls.wrap_command(command, wait_for_user=wait_for_user)

        env = os.environ
        if extra_env:
            env.update(extra_env)

        print(f"Executing runtime {cls.__name__} with {args=}")
        _ = subprocess.Popen(tuple(args), cwd=path, env=env)


class NoneRuntime(Runtime, name='none'):
    @staticmethod
    @override
    def enabled() -> bool:
        return True

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = False) -> Iterable[str]:
        if wait_for_user:
            print(f"{NoneRuntime.__name__} does not support 'wait_for_user', ignoring...")
        return command


class CommandPrompt(Runtime, name='cmd'):

    @staticmethod
    @override
    def enabled() -> bool:
        return which('cmd') is not None

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = True) -> Iterable[str]:
        return itertools.chain(
            ('cmd', '/K'),
            command,
            ('&', 'pause') if wait_for_user else (),
            ('&', 'exit')
        )


class WSL(Runtime, name=('wsl', 'bash')):

    @staticmethod
    @override
    def enabled() -> bool:
        return which('wsl') is not None

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = True) -> Iterable[str]:
        return itertools.chain(
            ('wsl',),
            command,
            (';', 'echo', '-e', '----------------------------------------\\nThe program exited with: $?\\nPress any key to continue . . . ', ';', 'read', '-srn1') if wait_for_user else ()
        )


class PowerShell5(Runtime, name=('powershell5', 'ps5')):

    @staticmethod
    @override
    def enabled() -> bool:
        return which('powershell') is not None

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = True) -> Iterable[str]:
        return ('powershell', '-EncodedCommand', base64.b64encode((' '.join(command) + '; pause' if wait_for_user else '').encode('utf-16-le')).decode('utf-8'))


class PowerShell7(Runtime, name=('pwsh', 'powershell7', 'ps7')):

    @staticmethod
    @override
    def enabled() -> bool:
        return which('pwsh') is not None

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = True) -> Iterable[str]:
        return ('pwsh', '-EncodedCommand', base64.b64encode((' '.join(command) + '; pause' if wait_for_user else '').encode('utf-16-le')).decode('utf-8'))


class AutoPowerShell(Runtime, name=('powershell', 'ps')):

    @staticmethod
    @override
    def enabled() -> bool:
        return PowerShell7.enabled() or PowerShell5.enabled()

    @classmethod
    @override
    def wrap_command(cls, command: Iterable[str], wait_for_user: bool = True) -> Iterable[str]:
        runtime = PowerShell7 if GlobalState.powershell_use_pwsh else PowerShell5
        return runtime.wrap_command(command, wait_for_user=wait_for_user)


class ListRootModel[T](pydantic.RootModel[list[T]], Sequence[T]):  # pyright: ignore[reportUnsafeMultipleInheritance]
    root: Annotated[list[T], pydantic.Field(default_factory=list)]

    @overload
    def __getitem__(self, index: SupportsIndex) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> Self: ...
    @override
    def __getitem__(self, index: SupportsIndex | slice) -> T | Self:
        if isinstance(index, slice):
            return type(self).model_construct(root=self.root[index])
        return self.root[index]

    @override
    def __len__(self) -> int:
        return len(self.root)

    @override
    def __iter__(self) -> Iterator[T]:  # pyright: ignore[reportIncompatibleMethodOverride]  # Needs to override the RootModel's implementation
        return iter(self.root)


class OverrideEntry(pydantic.BaseModel):
    model_config: ClassVar[pydantic.ConfigDict] = pydantic.ConfigDict(extra='ignore')

    filter: str = '*'
    run_command: str | None = None
    runtime: Annotated[str | None, pydantic.Field(validation_alias=pydantic.AliasChoices('runtime', 'global_runtime'))] = None

    _base_dir: Path | None = None

    @pydantic.model_validator(mode='after')
    def save_base_dir(self, info: pydantic.ValidationInfo) -> Self:
        if isinstance(info.context, Path):
            self._base_dir = info.context.parent
        return self

    def is_match(self, file_path: Path) -> bool:
        pattern = str(self._base_dir / self.filter) if self._base_dir is not None else self.filter
        return file_path.match(pattern)

    def update(self, other: Self) -> None:
        if other.filter != '*':
            self.filter = other.filter

        if other.run_command is not None:
            self.run_command = other.run_command

        if other.runtime is not None:
            self.runtime = other.runtime

    @classmethod
    def merge_entries(cls, entries: Iterable[Self]) -> Self | None:
        iterator = iter(entries)

        if (first := next(iterator, None)) is None:
            return None

        new = first.model_copy()

        for entry in iterator:
            new.update(entry)

        return new


class OverrideFile(ListRootModel[OverrideEntry]):
    @classmethod
    def load_from_file(cls, file_path: Path) -> Self | None:
        if not file_path.is_file():
            return None

        try:
            with file_path.open('rt', encoding='utf-8') as f:
                return cls.model_validate(yaml.safe_load(f), context=file_path)  # pyright: ignore[reportUnknownMemberType]  # Pydantic will handle validating the data
        except Exception:
            pass

        return None

    def calculate_entry_for_file(self, file_path: Path) -> OverrideEntry:
        matching_entries = (e for e in self.root if e.is_match(file_path))
        entry = OverrideEntry.merge_entries(matching_entries)
        return entry if entry is not None else OverrideEntry()


def calculate_best_open_folder(file_path: Path) -> Path | None:
    open_folders: set[Path] = {Path(p).resolve() for p in itertools.chain.from_iterable(window.folders() for window in sublime.windows())}

    best_candidate: Path | None = None
    best_candidate_diff_count: int = 999

    for base_path in open_folders:
        with suppress(ValueError):
            relative_path = file_path.relative_to(base_path, walk_up=False)
            parts_count = len(relative_path.parts)
            if parts_count < best_candidate_diff_count:
                best_candidate = base_path
                best_candidate_diff_count = parts_count

    return best_candidate


def get_git_root_for_view(view: sublime.View) -> Path | None:
    if (file_path := view.file_name()) is None:
        return None
    file_path = Path(file_path).resolve()

    for root_candidate in file_path.parents:
        if root_candidate.joinpath('.git').is_dir():
            break
    else:
        root_candidate = None

    return root_candidate


class OverrideAnnotationProperty(NamedTuple):
    property: str
    value: str


def parse_annotation_line(line: str) -> OverrideAnnotationProperty | None:
    match = re.fullmatch(r'(?:#|\/\/) ?nt:(?P<property_name>\w+)(?: (?P<property_arguments>.*))?', line)

    if not match:
        return None

    return OverrideAnnotationProperty(match.group('property_name'), match.group('property_arguments'))


def load_overrides_for_view(view: sublime.View) -> OverrideEntry:
    if (file_path := view.file_name()) is None:
        return OverrideEntry()
    file_path = Path(file_path).resolve()

    override_entry = OverrideEntry()

    # Search for override config files #

    search_root = get_git_root_for_view(view)
    if search_root is None:
        search_root = calculate_best_open_folder(file_path)

    if search_root is not None:
        for config_file in (search_root / p / '.neytools.yml' for p in reversed(file_path.relative_to(search_root, walk_up=False).parents)):
            config_file = OverrideFile.load_from_file(config_file)
            if config_file is not None:
                override_entry.update(config_file.calculate_entry_for_file(file_path))

    # Search for in-file annotations

    raw_properties: dict[str, str] = {}
    for row in range(0, 100):  # Using for instead of while for cheap insurance against runaway situations.
        textpoint = view.text_point(row=row, col=0)

        if textpoint >= view.size():
            break

        region = view.line(textpoint)
        line = view.substr(region)

        annotation = parse_annotation_line(line)
        if annotation is None:
            continue

        raw_properties[annotation.property] = annotation.value
    annotation_entry = OverrideEntry.model_validate(raw_properties)

    override_entry.update(annotation_entry)

    return override_entry


class __CommandBase(sublime_plugin.TextCommand, ABC):
    """ The base of all NeyTools Text commands. """

    def __init__(self, view: sublime.View) -> None:
        super().__init__(view)

        self.__format_dict: FormatDict = FormatDict(command_instance=self)
        self.__file_path: Path | None = None
        self.__git_root: Path | EllipsisType | None = None

    @property
    def file_path(self) -> Path | None:
        if (self.__file_path is None) and (fp := self.view.file_name()):
            self.__file_path = Path(fp)
        return self.__file_path

    @property
    def git_root(self) -> Path | EllipsisType | None:
        if self.__git_root is None and self.file_path:
            for root_candidate in self.file_path.parents:
                if root_candidate.joinpath('.git').exists():
                    break
            else:
                root_candidate = ...
            self.__git_root = root_candidate
        return self.__git_root

    def execute(self, command: Iterable[str], extra_env: dict[str, str] | None = None, runtime: type[Runtime] = NoneRuntime, path: Path | None = None, wait_for_user: bool = True) -> None:
        if self.view.is_dirty():
            self.view.run_command("save")

        if not self.is_ready():
            return

        if self.file_path is None:
            return

        if path is None:
            path = self.file_path.parent

        override_entry = load_overrides_for_view(self.view)

        if override_entry.runtime is not None:
            runtime = Runtime.get_by_name(override_entry.runtime)

        runtime.execute(self.__format_command(command), extra_env=extra_env, path=path, wait_for_user=wait_for_user)

    def is_ready(self) -> bool:
        return bool(self.file_path)

    def __format_command(self, command: Iterable[str]) -> Iterable[str]:
        return (arg.format_map(self.__format_dict) for arg in command)

    @abstractmethod
    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None: ...

    @abstractmethod
    @override
    def is_visible(self) -> bool: ...

    @abstractmethod
    @override
    def is_enabled(self) -> bool: ...


# For Development Purposes
class NeyToolsDebugTriggerCommand(__CommandBase):
    """Used for triggering the base class, while in developement."""

    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None:
        print("NeyTools Debug")
        print(f"{GlobalState.powershell_use_pwsh=}")

    @override
    def is_visible(self) -> bool:
        return NT_DEVMODE

    @override
    def is_enabled(self) -> bool:
        return NT_DEVMODE


# COMMANDS
class NeyToolsRunCommand(__CommandBase):
    """Used for intelligenly running the current document."""

    def __init__(self, view: sublime.View) -> None:
        super().__init__(view)
        self._syntaxHandlers: dict[str, Callable[[], None]] = {
            'Packages/Python/Python.sublime-syntax': self.h_python,
            'Packages/PowerShell/PowerShell.sublime-syntax': self.h_powershell,
            'Packages/PowerShell/Support/PowershellSyntax.tmLanguage': self.h_powershell,
        }

    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None:
        if override_command := load_overrides_for_view(self.view).run_command:
            self.h_override_command(override_command)
            return

        syntax = str(self.view.settings().get("syntax"))
        handler = self._syntaxHandlers.get(syntax, None)
        if handler:
            handler()
        else:
            print("Handler for this systax is not available!", syntax)

    def h_override_command(self, command: str) -> None:
        executable, *arguments = shlex.split(command)
        match = re.fullmatch(r"((?P<runtime>\w+):)?(?P<executable>.+)", executable)

        if match is None:
            return None

        self.execute((match.group('executable'), *arguments), runtime=Runtime.get_by_name(match.group('runtime'), NoneRuntime))

    def h_python(self) -> None:
        self.execute(('python3' if GlobalState.python_use_wsl else 'py', '{file_name}'), runtime=WSL if GlobalState.python_use_wsl else CommandPrompt)

    def h_powershell(self) -> None:
        self.execute(('pwsh' if GlobalState.powershell_use_pwsh else 'powershell', './{file_name}'), runtime=CommandPrompt)

    @override
    def is_visible(self) -> bool:
        return (self.view.settings().get("syntax") in self._syntaxHandlers or bool(load_overrides_for_view(self.view).run_command)) and self.is_ready()

    @override
    def is_enabled(self) -> bool:
        return (self.view.settings().get("syntax") in self._syntaxHandlers or bool(load_overrides_for_view(self.view).run_command)) and self.is_ready()


# class NeyToolsRunPoetryCommand(__CommandBase):
#     """Used for running the current Poetry Project"""

#     def __init__(self, view: sublime.View) -> None:
#         super().__init__(view)
#         self.poetry_base_dir: Path | None = None
#         self.poetry_project_name: str | None = None
#         self.__refresh_poetry()

#     @override
#     def run(self, edit: sublime.Edit, **kwargs: object) -> None:
#         self.__refresh_poetry()
#         if (self.poetry_base_dir is not None) and (self.poetry_project_name is not None):
#             extra_args = []
#             extra_env = {}

#             arguments_file = self.poetry_base_dir.joinpath('neytools_run.yml')
#             if arguments_file.exists():
#                 with arguments_file.open('rt') as f:
#                     content = yaml.safe_load(f)
#                     extra_args = content.get('args', [])
#                     extra_env = content.get('env', {})

#             self.execute(('poetry', 'run', 'python', '-m', '{poetry_project_name}', *extra_args), extra_env=extra_env, path=self.poetry_base_dir, runtime='wsl' if GlobalState.python_use_wsl else 'cmd')

#     def __refresh_poetry(self):
#         if not self.file_path:
#             return

#         # Currently open file's path
#         current_file_name = self.file_path.absolute()

#         # Get currently open folders in this window
#         open_folders = [Path(p).absolute() for p in self.view.window().folders()]

#         # Find closest open parent folder in open folders
#         best_relative_path = None
#         best_relative_base_components_count = 0
#         for base_folder in open_folders:
#             relative_path = None
#             try:
#                 relative_path = current_file_name.relative_to(base_folder)
#             except ValueError:
#                 relative_path = None
#             if relative_path is not None and best_relative_base_components_count < len(base_folder.parts):
#                 best_relative_base_components_count = len(base_folder.parts)
#                 best_relative_path = (base_folder, relative_path)

#         # Recursively check for Poetry setup
#         self.poetry_base_dir = None
#         if best_relative_path is not None:
#             for folder in (best_relative_path[0].joinpath(p) for p in best_relative_path[1].parents):
#                 lock_file = folder.joinpath("poetry.lock")
#                 pyproject_file = folder.joinpath("pyproject.toml")
#                 if lock_file.exists() and pyproject_file.exists():
#                     self.poetry_base_dir = folder
#                     break

#         # Parse pyproject.toml to find package name
#         self.poetry_project_name = None
#         if self.poetry_base_dir:
#             try:
#                 pyproject = toml.load(str(self.poetry_base_dir.joinpath("pyproject.toml")))
#                 self.poetry_project_name = pyproject["tool"]["poetry"]["name"]
#             except Exception as e:
#                 self.poetry_project_name = None
#                 print(e)

#     @override
#     def is_visible(self) -> bool:
#         return self.is_ready() and (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)

#     @override
#     def is_enabled(self) -> bool:
#         return self.is_ready() and (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)


class NeyToolsOpenCmdCommand(__CommandBase):
    """Opens a new Windows Command Prompt in the current directory."""

    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None:
        self.execute(('cmd',), runtime=NoneRuntime)

    @override
    def is_visible(self) -> bool:
        return GlobalState.cmd_available

    @override
    def is_enabled(self) -> bool:
        return GlobalState.cmd_available and self.is_ready()


class NeyToolsOpenPowerShellCommand(__CommandBase):
    """Opens a new PowerShell terminal in the current directory."""

    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None:
        self.execute(('pwsh' if GlobalState.powershell_use_pwsh else 'powershell',), runtime=NoneRuntime)

    @override
    def is_visible(self) -> bool:
        return GlobalState.powershell_available

    @override
    def is_enabled(self) -> bool:
        return GlobalState.powershell_available and self.is_ready()


class NeyToolsOpenWslCommand(__CommandBase):
    """Opens a new WSL terminal in the current directory."""

    @override
    def run(self, edit: sublime.Edit, **kwargs: object) -> None:
        self.execute(('wsl',), runtime=NoneRuntime)

    @override
    def is_visible(self) -> bool:
        return GlobalState.wsl_available

    @override
    def is_enabled(self) -> bool:
        return GlobalState.wsl_available and self.is_ready()
