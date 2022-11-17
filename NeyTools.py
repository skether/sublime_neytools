import sublime
import sublime_plugin
import os
from pathlib import Path
from shutil import which
import toml

#For Development Purposes
#Used to enable logging and development tools
NT_DEVMODE = False

#Used for disabling options when they are not available
NT_BASHAVAILABLE = False
NT_CMDAVAILABLE = False
NT_PSAVAILABLE = False

#Settings
NT_SETTINGS = None
NT_PYTHON_BASH = False

#Loading Settings
def plugin_loaded():
	global NT_BASHAVAILABLE, NT_CMDAVAILABLE, NT_PSAVAILABLE, NT_SETTINGS, NT_PYTHON_BASH
	NT_BASHAVAILABLE = which('bash') is not None
	NT_CMDAVAILABLE = which('cmd') is not None
	NT_PSAVAILABLE = which('powershell') is not None
	NT_SETTINGS = sublime.load_settings('NeyTools.sublime-settings')
	NT_PYTHON_BASH = NT_SETTINGS.get('python_use_bash', False) and NT_BASHAVAILABLE

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
			except KeyError:
				command_instance_vars = vars(self.command_instance)
				if key in command_instance_vars:
					return command_instance_vars[key]
				raise e
			


#Base Class for TextCommands
class _NT_Base(sublime_plugin.TextCommand):
	"""The base of all NeyTools Text commands."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.format_dict = FormatDict(command_instance=self)
		self._refresh_path_components()

	def execute(self, command):
		#If the current document is dirty then save it.
		if self.view.is_dirty():
			self.view.run_command('save')

		#Refresh the path
		self._refresh_path_components()

		os.system(self._formatCommand(command))

	def executeFrom(self, command, path):
		command = path.drive + ' & cd "' + str(path) + '" & ' + command
		self.execute(command)

	def executeFromHere(self, command):
		self.executeFrom(command, self.filepath.parent)

	def _refresh_path_components(self):
		self.filepath = Path(self.view.file_name())

	def _formatCommand(self, command):
		return command.format_map(self.format_dict)


#For Development Purposes
class NeyToolsDebugTriggerCommand(_NT_Base):
	"""Used for triggering the base class, while in developement."""

	def run(self, edit):
		print('NeyTools Debug')
		self.execute('exit')

	def is_visible(self):
		return NT_DEVMODE

	def is_enabled(self):
		return NT_DEVMODE


#SETTING COMMANDS
class NeyToolsSettingPythonEnvironmentCommand(sublime_plugin.ApplicationCommand):
	"""Used for selecting the Python environment."""

	def run(self, env):
		global NT_PYTHON_BASH
		NT_PYTHON_BASH = env
		NT_SETTINGS.set('python_use_bash', NT_PYTHON_BASH)

	def is_visible(self, env):
		return NT_BASHAVAILABLE or not env

	def is_enabled(self, env):
		return NT_BASHAVAILABLE or not env

	def is_checked(self, env):
		return NT_PYTHON_BASH == env


#COMMANDS
class NeyToolsRunCommand(_NT_Base):
	"""Used for intelligenly running the current document."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._syntaxHandlers = {}
		self._syntaxHandlers['Packages/Python/Python.sublime-syntax'] = self.hPython
		self._syntaxHandlers['Packages/PowerShell/Support/PowershellSyntax.tmLanguage'] = self.hPowerShell

	def run(self, edit):
		syntax = self.view.settings().get('syntax')
		handler = self._syntaxHandlers.get(syntax, None)
		if handler:
			handler()
		else:
			print("Handler for this systax is not available!", syntax)

	def hPython(self):
		if NT_PYTHON_BASH:
			self.executeFromHere('start bash -c "python3 {filename};echo \\\"---------------------\\\";read -n 1 -s -r -p \\\"Press any key to continue...\\\""')
		else:
			self.executeFromHere('start cmd /K "python3 {filename} & pause & exit"')

	def hPowerShell(self):
		self.executeFromHere('start cmd /K "powershell ./{filename} & pause & exit"')

	def is_visible(self):
		return self.view.settings().get('syntax') in self._syntaxHandlers

	def is_enabled(self):
		return self.view.settings().get('syntax') in self._syntaxHandlers

class NeyToolsRunPoetryCommand(_NT_Base):
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
				self.executeFrom('start bash -c "python3 -m poetry run python -m {poetry_project_name};echo \\\"---------------------\\\";read -n 1 -s -r -p \\\"Press any key to continue...\\\""', self.poetry_base_dir)
			else:
				self.executeFrom('start cmd /K "python3 -m poetry run python -m {poetry_project_name} & pause & exit"', self.poetry_base_dir)

	def _refresh_poetry(self):
		# Currently open file's path
		current_file_name = Path(self.view.file_name()).absolute()

		# Get currently open folders in this window
		open_folders = [Path(p).absolute() for p in self.view.window().folders()]

		# Find closest open parent folder in open folders
		best_relative_path = None
		best_relative_base_components_count = 0
		for base_folder in open_folders:
			relative_path = None
			try:
				relative_path = current_file_name.relative_to(base_folder)
			except ValueError as e:
				relative_path = None
			if relative_path is not None and best_relative_base_components_count < len(base_folder.parts):
				best_relative_base_component_count = len(base_folder.parts)
				best_relative_path = (base_folder, relative_path)

		# Recursively check for Poetry setup
		self.poetry_base_dir = None
		if best_relative_path is not None:
			for folder in (best_relative_path[0].joinpath(p) for p in best_relative_path[1].parents):
				lock_file = folder.joinpath('poetry.lock')
				pyproject_file = folder.joinpath('pyproject.toml')
				if lock_file.exists() and pyproject_file.exists():
					self.poetry_base_dir = folder
					break

		# Parse pyproject.toml to find package name
		self.poetry_project_name = None
		if self.poetry_base_dir:
			try:
				pyproject = toml.load(str(self.poetry_base_dir.joinpath('pyproject.toml')))
				self.poetry_project_name = pyproject['tool']['poetry']['name']
			except Exception as e:
				self.poetry_project_name = None
				print(e)

	def is_visible(self):
		return (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)

	def is_enabled(self):
		return (self.poetry_base_dir is not None) and (self.poetry_project_name is not None)

#Windows Tools (Windows Command Prompt)
class _NT_CMD_Base(_NT_Base):
	"""The base of all Windows Command Prompt commands."""

	def is_visible(self):
		return NT_CMDAVAILABLE

	def is_enabled(self):
		return NT_CMDAVAILABLE

class NeyToolsOpenCmdCommand(_NT_CMD_Base):
	"""Opens a new Windows Command Prompt in the current directory."""

	def run(self, edit):
		self.executeFromHere('start cmd')


#Windows Tools (PowerShell)
class _NT_PS_Base(_NT_Base):
	"""The base of all Windows PowerShell commands."""

	def is_visible(self):
		return NT_PSAVAILABLE

	def is_enabled(self):
		return NT_PSAVAILABLE

class NeyToolsOpenPowerShellCommand(_NT_PS_Base):
	"""Opens a new PowerShell terminal in the current directory."""

	def run(self, edit):
		self.executeFromHere('start powershell')


#Linux Tools (Bash - Windows Subsystem for Linux)
class _NT_Bash_Base(_NT_Base):
	"""The base of all Bash commands."""

	def is_visible(self):
		return NT_BASHAVAILABLE

	def is_enabled(self):
		return NT_BASHAVAILABLE

class NeyToolsOpenBashCommand(_NT_Bash_Base):
	"""Opens a new Bash terminal in the current directory."""

	def run(self, edit):
		self.executeFromHere('start bash')
