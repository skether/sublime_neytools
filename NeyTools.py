import itertools
import subprocess
from pathlib import Path
from shutil import which

import sublime

import sublime_plugin

import toml


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

        GlobalState.python_use_wsl = GlobalState.wsl_available and GlobalState.plugin_settings.get("python_use_bash", False)


# SETTING COMMANDS
class NeyToolsSettingPythonEnvironmentCommand(sublime_plugin.ApplicationCommand):
    """Used for selecting the Python environment."""

    def run(self, env):
        GlobalState.python_use_wsl = env
        GlobalState.plugin_settings.set("python_use_bash", GlobalState.python_use_wsl)

    def is_visible(self, env):
        return GlobalState.wsl_available or not env

    def is_enabled(self, env):
        return GlobalState.wsl_available or not env

    def is_checked(self, env):
        return GlobalState.python_use_wsl == env


class FormatDict(dict):
    def __init__(self, *args, command_instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_instance = command_instance
        self.proxies = {
            "filename": lambda: self.command_instance.filepath.name,
            "filepath": lambda: self.command_instance.filepath,
            "drive": lambda: self.command_instance.filepath.drive,
            "directory": lambda: self.command_instance.filepath.parent,
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


# New generation base class
class __CommandBase(sublime_plugin.TextCommand):
    """ The base of all NeyTools Text commands. """
    __runtimes__ = {
        'wsl': (['wsl'], [';', 'echo', '-e', '----------------------------------------\\nThe program exited with: $?\\nPress any key to continue . . . ', ';', 'read', '-srn1'], []),
        'cmd': (['cmd', '/K'], ['&', 'pause', '&', 'exit'], ['&', 'exit']),
        None: ([], [], [])
    }  # idx0: pre-commands, idx1: wait_for_user=True commands, idx2: wait_for_user=False commands

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.format_dict = FormatDict(command_instance=self)
        self.__refresh_path_components()

    def execute(self, *command, runtime=None, path=None, wait_for_user=True):
        if self.view.is_dirty():
            self.view.run_command("save")

        if not self.is_ready():
            self.__refresh_path_components()

        if path is None:
            path = self.filepath.parent

        runtime_args = self.__runtimes__.get(runtime, None)
        if runtime_args is None:
            raise ValueError(f"{runtime} is an invalid runtime!")

        args = list(itertools.chain(runtime_args[0], self.__format_command(command), runtime_args[1] if wait_for_user else runtime_args[2]))
        subprocess.Popen(args, cwd=path)

    def is_ready(self):
        return bool(self.filepath)

    def __refresh_path_components(self):
        file_name = self.view.file_name()
        self.filepath = Path(file_name) if file_name else None

    def __format_command(self, command):
        if isinstance(command, tuple) or isinstance(command, list):
            return (arg.format_map(self.format_dict) for arg in command)
        raise TypeError("command is not intance of str or list")


# For Development Purposes
class NeyToolsDebugTriggerCommand(__CommandBase):
    """Used for triggering the base class, while in developement."""

    def run(self, edit):
        print("NeyTools Debug")

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
            'Packages/PowerShell/Support/PowershellSyntax.tmLanguage': self.h_powershell
        }

    def run(self, edit):
        syntax = self.view.settings().get("syntax")
        handler = self._syntaxHandlers.get(syntax, None)
        if handler:
            handler()
        else:
            print("Handler for this systax is not available!", syntax)

    def h_python(self):
        self.execute('python3', '{filename}', runtime='wsl' if GlobalState.python_use_wsl else 'cmd')

    def h_powershell(self):
        self.execute('powershell', './{filename}', runtime='cmd')

    def is_visible(self):
        return self.view.settings().get("syntax") in self._syntaxHandlers and self.is_ready()

    def is_enabled(self):
        return self.view.settings().get("syntax") in self._syntaxHandlers and self.is_ready()


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
            self.execute('poetry', 'run', 'python', '-m', '{poetry_project_name}', path=self.poetry_base_dir, runtime='wsl' if GlobalState.python_use_wsl else 'cmd')

    def __refresh_poetry(self):
        if not self.filepath:
            return

        # Currently open file's path
        current_file_name = self.filepath.absolute()

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
        self.execute('powershell', runtime=None)

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
