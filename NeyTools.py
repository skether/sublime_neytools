import os
from pathlib import Path
from shutil import which

import sublime

import sublime_plugin

import toml

# For Development Purposes
# Used to enable logging and development tools
NT_DEVMODE = False

# Used for disabling options when they are not available
NT_BASHAVAILABLE = False
NT_CMDAVAILABLE = False
NT_PSAVAILABLE = False

# Settings
NT_SETTINGS = None
NT_PYTHON_BASH = False


# Loading Settings
def plugin_loaded():
    global NT_BASHAVAILABLE, NT_CMDAVAILABLE, NT_PSAVAILABLE, NT_SETTINGS, NT_PYTHON_BASH
    NT_BASHAVAILABLE = which("bash") is not None
    NT_CMDAVAILABLE = which("cmd") is not None
    NT_PSAVAILABLE = which("powershell") is not None
    NT_SETTINGS = sublime.load_settings("NeyTools.sublime-settings")
    NT_PYTHON_BASH = NT_SETTINGS.get("python_use_bash", False) and NT_BASHAVAILABLE


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


# Base Class for TextCommands
class _NT_CommandBase(sublime_plugin.TextCommand):
    """The base of all NeyTools Text commands."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.format_dict = FormatDict(command_instance=self)
        self._refresh_path_components()

    def execute(self, command):
        # If the current document is dirty then save it.
        if self.view.is_dirty():
            self.view.run_command("save")

        # Refresh the path
        self._refresh_path_components()

        os.system(self._format_command(command))

    def execute_from(self, command, path):
        command = path.drive + ' & cd "' + str(path) + '" & ' + command
        self.execute(command)

    def execute_from_here(self, command):
        self.execute_from(command, self.filepath.parent)

    def is_ready(self):
        return not not self.filepath

    def _refresh_path_components(self):
        file_name = self.view.file_name()
        self.filepath = Path(file_name) if file_name else None

    def _format_command(self, command):
        return command.format_map(self.format_dict)


# For Development Purposes
class NeyToolsDebugTriggerCommand(_NT_CommandBase):
    """Used for triggering the base class, while in developement."""

    def run(self, edit):
        print("NeyTools Debug")
        self.execute("exit")

    def is_visible(self):
        return NT_DEVMODE

    def is_enabled(self):
        return NT_DEVMODE


# SETTING COMMANDS
class NeyToolsSettingPythonEnvironmentCommand(sublime_plugin.ApplicationCommand):
    """Used for selecting the Python environment."""

    def run(self, env):
        global NT_PYTHON_BASH
        NT_PYTHON_BASH = env
        NT_SETTINGS.set("python_use_bash", NT_PYTHON_BASH)

    def is_visible(self, env):
        return NT_BASHAVAILABLE or not env

    def is_enabled(self, env):
        return NT_BASHAVAILABLE or not env

    def is_checked(self, env):
        return NT_PYTHON_BASH == env


# COMMANDS
class NeyToolsRunCommand(_NT_CommandBase):
    """Used for intelligenly running the current document."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._syntaxHandlers = {}
        self._syntaxHandlers["Packages/Python/Python.sublime-syntax"] = self.h_python
        self._syntaxHandlers["Packages/PowerShell/Support/PowershellSyntax.tmLanguage"] = self.h_powershell

    def run(self, edit):
        syntax = self.view.settings().get("syntax")
        handler = self._syntaxHandlers.get(syntax, None)
        if handler:
            handler()
        else:
            print("Handler for this systax is not available!", syntax)

    def h_python(self):
        if NT_PYTHON_BASH:
            self.execute_from_here('start bash -c "python3 {filename};echo \\"---------------------\\";read -n 1 -s -r -p \\"Press any key to continue...\\""')
        else:
            self.execute_from_here('start cmd /K "python3 {filename} & pause & exit"')

    def h_powershell(self):
        self.execute_from_here('start cmd /K "powershell ./{filename} & pause & exit"')

    def is_visible(self):
        return self.view.settings().get("syntax") in self._syntaxHandlers and self.is_ready()

    def is_enabled(self):
        return self.view.settings().get("syntax") in self._syntaxHandlers and self.is_ready()


class NeyToolsRunPoetryCommand(_NT_CommandBase):
    """Used for running the current Poetry Project"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.poetry_base_dir = None
        self.poetry_project_name = None
        self._refresh_poetry()

    def run(self, edit):
        self._refresh_poetry()
        if (self.poetry_base_dir is not None) and (self.poetry_project_name is not None):
            if NT_PYTHON_BASH:
                self.execute_from('start bash -c "python3 -m poetry run python -m {poetry_project_name};echo \\"---------------------\\";read -n 1 -s -r -p \\"Press any key to continue...\\""', self.poetry_base_dir)
            else:
                self.execute_from('start cmd /K "python3 -m poetry run python -m {poetry_project_name} & pause & exit"', self.poetry_base_dir)

    def _refresh_poetry(self):
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


# Windows Tools (Windows Command Prompt)
class _NTWindowsCommandPromptBase(_NT_CommandBase):
    """The base of all Windows Command Prompt commands."""

    def is_visible(self):
        return NT_CMDAVAILABLE

    def is_enabled(self):
        return NT_CMDAVAILABLE and self.is_ready()


class NeyToolsOpenCmdCommand(_NTWindowsCommandPromptBase):
    """Opens a new Windows Command Prompt in the current directory."""

    def run(self, edit):
        self.execute_from_here("start cmd")


# Windows Tools (PowerShell)
class _NTPowerShellBase(_NT_CommandBase):
    """The base of all Windows PowerShell commands."""

    def is_visible(self):
        return NT_PSAVAILABLE

    def is_enabled(self):
        return NT_PSAVAILABLE and self.is_ready()


class NeyToolsOpenPowerShellCommand(_NTPowerShellBase):
    """Opens a new PowerShell terminal in the current directory."""

    def run(self, edit):
        self.execute_from_here("start powershell")


# Linux Tools (Bash - Windows Subsystem for Linux)
class _NTBashBase(_NT_CommandBase):
    """The base of all Bash commands."""

    def is_visible(self):
        return NT_BASHAVAILABLE

    def is_enabled(self):
        return NT_BASHAVAILABLE and self.is_ready()


class NeyToolsOpenBashCommand(_NTBashBase):
    """Opens a new Bash terminal in the current directory."""

    def run(self, edit):
        self.execute_from_here("start bash")
