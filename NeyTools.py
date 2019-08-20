import sublime
import sublime_plugin
import os
from shutil import which

#For Development Purposes
#Used to enable logging and development tools
NT_DEVMODE = True

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

#Base Class
class _NT_Base(sublime_plugin.TextCommand):
	"""The base of all NeyTools Text commands."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._getPathComponents()

	def execute(self, command=None):
		#If the current document is dirty then save it.
		if self.view.is_dirty():
			self.view.run_command('save')

		if command:
			self.command = command

		os.system(self._formatCommand(self.command))

	def executeFromHere(self, command=None):
		if command:
			self.command = command
		self.command = '{drive} & cd "{directory}" & ' + self.command
		self.execute()

	def _getPathComponents(self):
		self.path = self.view.file_name()
		self.drive = os.path.splitdrive(self.path)[0]
		self.directory = os.path.dirname(self.path)
		self.file = os.path.basename(self.path)

	def _formatCommand(self, command):
		return command.format_map(self.__dict__)


#For Development Purposes
class NeyToolsDebugTriggerCommand(_NT_Base):
	"""Used for triggering the base class, while in developement."""

	def run(self, edit):
		print(self.view.settings().get('syntax'))
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
			self.executeFromHere('start bash -c "python3 {file};echo \\\"---------------------\\\";read -n 1 -s -r -p \\\"Press any key to continue...\\\"\"')
		else:
			self.executeFromHere('start cmd /K "python3 {file} & pause & exit"')

	def hPowerShell(self):
		self.executeFromHere('start cmd /K "powershell ./{file} & pause & exit"')

	def is_visible(self):
		return self.view.settings().get('syntax') in self._syntaxHandlers

	def is_enabled(self):
		return self.view.settings().get('syntax') in self._syntaxHandlers

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
