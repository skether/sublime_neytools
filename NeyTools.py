import base64
import itertools
import os
import re
import shlex
import subprocess
from pathlib import Path
from shutil import which

import sublime
import sublime_plugin
import toml
import yaml

# For Development Purposes
# Used to enable logging and development tools
NT_DEVMODE = False
package_git_head = Path(sublime.packages_path(), "sublime_neytools/.git/HEAD")
if package_git_head.exists():
    with package_git_head.open("rt") as head:
        if head.read().strip() != "ref: refs/heads/main":
            NT_DEVMODE = True


# Loading Settings
def plugin_loaded():
    GlobalState.load_global_state()


class GlobalState():
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


class FormatDict(dict):
    def __init__(self, *args, command_instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_instance = command_instance
        self.proxies = {
            "directory": lambda: self.command_instance.file_path.parent,
            "drive": lambda: self.command_instance.file_path.drive,

            "filename": lambda: self.command_instance.file_path.name,
            "filepath": lambda: self.command_instance.file_path,
            "file_name": lambda: self.command_instance.file_path.name,
            "file_path": lambda: self.command_instance.file_path,

            "file_text": lambda: self.command_instance.view.substr(sublime.Region(0, self.command_instance.view.size())),
            "file_text_base64": lambda: base64.b64encode(self.command_instance.view.substr(sublime.Region(0, self.command_instance.view.size())).encode(self.command_instance.view.encoding().replace('Undefined', 'utf-8'))).decode('utf-8'),

            "git_root": lambda: self.command_instance.git_root,
        }

    def __getitem__(self, key):
        if key in self.proxies:
            return self.proxies[key]()
        else:
            try:
                return super().__getitem__(key)
            except KeyError as e:
                command_instance_vars = vars(self.command_instance)
                if key in command_instance_vars:
                    return command_instance_vars[key]
                raise e


class Runtime():
    __registry = {}

    fallback_runtime = None

    def __init_subclass__(cls, *args, name, **kwargs):
        super().__init_subclass__(*args, **kwargs)
        if isinstance(name, str):
            Runtime.__registry[name] = cls
        else:
            for n in (str(n).lower() for n in name):
                Runtime.__registry[n] = cls

    def __init__(self):
        if type(self) == Runtime:
            raise TypeError("The base Runtime class should not be instantiated! Use a valid subclass instead!")
        self.type = self.__registry[type(self)]

    @staticmethod
    def get_by_name(name):
        name = str(name).lower()
        if name not in Runtime.__registry:
            raise ValueError(f"{name} is an invalid Runtime type!")
        runtime = Runtime.__registry[name]
        if not runtime.enabled():
            raise ValueError(f"Runtime of type ({name}) is not enabled!")
        return Runtime.__registry[name]

    @staticmethod
    def enabled():
        return True

    @staticmethod
    def wrap_command(*command, wait_for_user=False):
        if wait_for_user:
            print("None Runtime does not support wait_for_user==True, ignoring...")
        return command

    @classmethod
    def execute(cls, *command, extra_env=None, path=None, wait_for_user=True):
        args = cls.wrap_command(*command, wait_for_user=wait_for_user)

        env = os.environ
        if extra_env:
            env.update(extra_env)

        print(f"Executing runtime {cls.__name__} with {args=}")
        subprocess.Popen(args, cwd=path, env=env)


class NoneRuntime(Runtime, name='none'):
    pass


class CommandPrompt(Runtime, name='cmd'):

    @staticmethod
    def enabled():
        return which('cmd') is not None

    @staticmethod
    def wrap_command(*command, wait_for_user=True):
        return list(itertools.chain(
            ['cmd', '/K'],
            command,
            ['&', 'pause'] if wait_for_user else [],
            ['&', 'exit']
        ))


class WSL(Runtime, name=('wsl', 'bash')):

    @staticmethod
    def enabled():
        return which('wsl') is not None

    @staticmethod
    def wrap_command(*command, wait_for_user=True):
        return list(itertools.chain(
            ['wsl'],
            command,
            [';', 'echo', '-e', '----------------------------------------\\nThe program exited with: $?\\nPress any key to continue . . . ', ';', 'read', '-srn1'] if wait_for_user else []
        ))


class PowerShell5(Runtime, name=('powershell5', 'ps5')):

    @staticmethod
    def enabled():
        return which('powershell') is not None

    @staticmethod
    def wrap_command(*command, wait_for_user=True):
        return ['powershell', '-EncodedCommand', base64.b64encode((' '.join(command) + '; pause' if wait_for_user else '').encode('utf-16-le')).decode('utf-8')]


class PWSH(Runtime, name='pwsh'):

    @staticmethod
    def enabled():
        return which('pwsh') is not None

    @staticmethod
    def wrap_command(*command, wait_for_user=True):
        return ['pwsh', '-EncodedCommand', base64.b64encode((' '.join(command) + '; pause' if wait_for_user else '').encode('utf-16-le')).decode('utf-8')]


class AutoPowerShell(Runtime, name=('powershell', 'ps')):

    @staticmethod
    def enabled():
        return PWSH.enabled() or PowerShell5.enabled()

    @staticmethod
    def wrap_command(*command, wait_for_user=True):
        runtime = PWSH if GlobalState.powershell_use_pwsh else PowerShell5
        return runtime.wrap_command(*command, wait_for_user=wait_for_user)


class __CommandBase(sublime_plugin.TextCommand):
    """ The base of all NeyTools Text commands. """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__format_dict = FormatDict(command_instance=self)
        self.__file_path = None
        self.__git_root = None

    @property
    def file_path(self):
        if (self.__file_path is None) and (fp := self.view.file_name()):
            self.__file_path = Path(fp)
        return self.__file_path

    @property
    def git_root(self):
        if self.__git_root is None:
            for root_candidate in self.file_path.parents:
                if root_candidate.joinpath('.git').exists():
                    break
            else:
                root_candidate = "NO_GIT_ROOT"
            self.__git_root = root_candidate
        return self.__git_root

    def execute(self, *command, extra_env=None, runtime=None, path=None, wait_for_user=True):
        if self.view.is_dirty():
            self.view.run_command("save")

        if not self.is_ready():
            return

        if path is None:
            path = self.file_path.parent

        if (override_runtime := self._get_override('runtime')) or (override_runtime := self._get_override('global_runtime')):
            runtime = override_runtime

        runtime = Runtime.get_by_name(runtime)
        runtime.execute(*self.__format_command(command), extra_env=extra_env, path=path, wait_for_user=wait_for_user)

    def is_ready(self):
        return bool(self.file_path)

    def __parse_property_line(self, line):
        match = re.fullmatch(r"(?:#|\/\/) ?nt:(?P<property_name>\w+)(?: (?P<property_arguments>.*))?", line)

        if not match:
            return (None, None)

        return (match.group('property_name'), match.group('property_arguments'))

    def __get_override_from_annotation(self, property_name):
        for row in range(0, 100):  # Using for instead of while for cheap insurance against runaway situations.
            textpoint = self.view.text_point(row=row, col=0)

            if textpoint >= self.view.size():
                break

            region = self.view.line(textpoint)
            line = self.view.substr(region)

            prop_name, prop_args = self.__parse_property_line(line)

            if prop_name == property_name:
                return prop_args
            elif prop_name is None and row != 0:
                break

        return None

    def __get_override_from_config_file(self, property_name):
        if not self.file_path:
            return

        # Currently open file's path
        current_file_name = self.file_path.absolute()

        # Get currently open folders in this window
        open_folders = [Path(p).absolute() for p in self.view.window().folders()]

        # Find closest open parent folder in open folders
        best_relative_path = None
        best_relative_base_components_count = 0
        for base_folder in open_folders:
            relative_path = None
            try:
                relative_path = current_file_name.relative_to(base_folder)
            except ValueError:
                relative_path = None
            if relative_path is not None and best_relative_base_components_count < len(base_folder.parts):
                best_relative_base_components_count = len(base_folder.parts)
                best_relative_path = (base_folder, relative_path)

        # print(f"{best_relative_path=}")
        # print(f"{best_relative_base_components_count=}")

        if best_relative_path is None:
            return None

        # Recursively check for neytools config file
        override_config_file = None
        for folder in (best_relative_path[0].joinpath(p) for p in best_relative_path[1].parents):
            config_file = folder.joinpath(".neytools.yml")
            if config_file.exists():
                override_config_file = config_file
                break

        # print(f"{override_config_file=}")

        if override_config_file is None:
            return None

        with override_config_file.open('rt') as f:
            override_configs = yaml.safe_load(f)

        for config in override_configs:
            if self.file_path.match(str(override_config_file.parent.joinpath(config['filter']))) and (value := config.get(property_name, None)) is not None:
                return value

        return None

    def _get_override(self, property_name):
        if (prop := self.__get_override_from_annotation(property_name)) is not None:
            return prop
        return self.__get_override_from_config_file(property_name)

    def __format_command(self, command):
        if isinstance(command, tuple) or isinstance(command, list):
            return (arg.format_map(self.__format_dict) for arg in command)
        raise TypeError("command is not intance of str or list")


# For Development Purposes
class NeyToolsDebugTriggerCommand(__CommandBase):
    """Used for triggering the base class, while in developement."""

    def run(self, edit):
        print("NeyTools Debug")
        print(f"{GlobalState.powershell_use_pwsh=}")

    def is_visible(self):
        return NT_DEVMODE

    def is_enabled(self):
        return NT_DEVMODE


# COMMANDS
class NeyToolsRunCommand(__CommandBase):
    """Used for intelligenly running the current document."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._syntaxHandlers = {
            'Packages/Python/Python.sublime-syntax': self.h_python,
            'Packages/PowerShell/PowerShell.sublime-syntax': self.h_powershell,
            'Packages/PowerShell/Support/PowershellSyntax.tmLanguage': self.h_powershell,
        }

    def run(self, edit):
        if override_command := self._get_override('run_command'):
            self.h_override_command(override_command)
            return

        syntax = self.view.settings().get("syntax")
        handler = self._syntaxHandlers.get(syntax, None)
        if handler:
            handler()
        else:
            print("Handler for this systax is not available!", syntax)

    def h_override_command(self, command):
        executable, *arguments = shlex.split(command)
        match = re.fullmatch(r"((?P<runtime>\w+):)?(?P<executable>.+)", executable)
        self.execute(match.group('executable'), *arguments, runtime=match.group('runtime'))

    def h_python(self):
        self.execute('python3' if GlobalState.python_use_wsl else 'py', '{file_name}', runtime='wsl' if GlobalState.python_use_wsl else 'cmd')

    def h_powershell(self):
        self.execute('pwsh' if GlobalState.powershell_use_pwsh else 'powershell', './{file_name}', runtime='cmd')

    def is_visible(self):
        return (self.view.settings().get("syntax") in self._syntaxHandlers or bool(self._get_override('run_command'))) and self.is_ready()

    def is_enabled(self):
        return (self.view.settings().get("syntax") in self._syntaxHandlers or bool(self._get_override('run_command'))) and self.is_ready()


class NeyToolsRunPoetryCommand(__CommandBase):
    """Used for running the current Poetry Project"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.poetry_base_dir = None
        self.poetry_project_name = None
        self.__refresh_poetry()

    def run(self, edit):
        self.__refresh_poetry()
        if (self.poetry_base_dir is not None) and (self.poetry_project_name is not None):
            extra_args = []
            extra_env = {}

            arguments_file = self.poetry_base_dir.joinpath('neytools_run.yml')
            if arguments_file.exists():
                with arguments_file.open('rt') as f:
                    content = yaml.safe_load(f)
                    extra_args = content.get('args', [])
                    extra_env = content.get('env', {})

            self.execute('poetry', 'run', 'python', '-m', '{poetry_project_name}', *extra_args, extra_env=extra_env, path=self.poetry_base_dir, runtime='wsl' if GlobalState.python_use_wsl else 'cmd')

    def __refresh_poetry(self):
        if not self.file_path:
            return

        # Currently open file's path
        current_file_name = self.file_path.absolute()

        # Get currently open folders in this window
        open_folders = [Path(p).absolute() for p in self.view.window().folders()]

        # Find closest open parent folder in open folders
        best_relative_path = None
        best_relative_base_components_count = 0
        for base_folder in open_folders:
            relative_path = None
            try:
                relative_path = current_file_name.relative_to(base_folder)
            except ValueError:
                relative_path = None
            if relative_path is not None and best_relative_base_components_count < len(base_folder.parts):
                best_relative_base_components_count = len(base_folder.parts)
                best_relative_path = (base_folder, relative_path)

        # Recursively check for Poetry setup
        self.poetry_base_dir = None
        if best_relative_path is not None:
            for folder in (best_relative_path[0].joinpath(p) for p in best_relative_path[1].parents):
                lock_file = folder.joinpath("poetry.lock")
                pyproject_file = folder.joinpath("pyproject.toml")
                if lock_file.exists() and pyproject_file.exists():
                    self.poetry_base_dir = folder
                    break

        # Parse pyproject.toml to find package name
        self.poetry_project_name = None
        if self.poetry_base_dir:
            try:
                pyproject = toml.load(str(self.poetry_base_dir.joinpath("pyproject.toml")))
                self.poetry_project_name = pyproject["tool"]["poetry"]["name"]
            except Exception as e:
                self.poetry_project_name = None
                print(e)

    def is_visible(self):
        return self.is_ready() and (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)

    def is_enabled(self):
        return self.is_ready() and (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)


class NeyToolsOpenCmdCommand(__CommandBase):
    """Opens a new Windows Command Prompt in the current directory."""

    def run(self, edit):
        self.execute('cmd', runtime=None)

    def is_visible(self):
        return GlobalState.cmd_available

    def is_enabled(self):
        return GlobalState.cmd_available and self.is_ready()


class NeyToolsOpenPowerShellCommand(__CommandBase):
    """Opens a new PowerShell terminal in the current directory."""

    def run(self, edit):
        self.execute('pwsh' if GlobalState.powershell_use_pwsh else 'powershell', runtime=None)

    def is_visible(self):
        return GlobalState.powershell_available

    def is_enabled(self):
        return GlobalState.powershell_available and self.is_ready()


class NeyToolsOpenWslCommand(__CommandBase):
    """Opens a new WSL terminal in the current directory."""

    def run(self, edit):
        self.execute('wsl', runtime=None)

    def is_visible(self):
        return GlobalState.wsl_available

    def is_enabled(self):
        return GlobalState.wsl_available and self.is_ready()
