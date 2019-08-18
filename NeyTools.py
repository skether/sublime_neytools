import sublime_plugin
import os
from shutil import which

#For Development Purposes
#Used to enable logging and development tools
NT_DEVMODE = True

#Used for disabling the bash option when bash is not available
NT_BASHAVAILABLE = False
 
def plugin_loaded():
	global NT_BASHAVAILABLE
	NT_BASHAVAILABLE = which('bash') is not None

#Base Class
class NTBase(sublime_plugin.TextCommand):
	"""The base of all NeyTools commands."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	def runCommand(self, command):
		#If the current document is dirty then save it.
		if self.view.is_dirty():
			self.view.run_command('save')

		os.system(self.formatCommandWithPath(command))

	def _getPathComponents(self):
		path = self.view.file_name()
		return (os.path.splitdrive(path)[0], os.path.dirname(path), os.path.basename(path))

	def formatCommandWithPath(self, command):
		drive, directory, file = self._getPathComponents()
		return command.format(drive=drive, directory=directory, file=file)


#For Development Purposes
class NeyToolsDebugTriggerCommand(NTBase):
	"""Used for triggering the base class, while in developement."""

	def run(self, edit):
		#print(self.view.settings().get('syntax'))
		self.runCommand('exit')

	def is_visible(self):
		return NT_DEVMODE

	def is_enabled(self):
		return NT_DEVMODE


#Windows Tools (Windows Command Prompt)
class OpenCmdCommand(NTBase):
	"""Opens a new Windows Command Prompt in the current directory."""

	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd')

class RunPythonWinCommand(NTBase):
	"""Runs the current python document, using the currently installed windows version of python3."""

	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd /K "python3 {file} & pause & exit"')


#Windows Tools (PowerShell)
class OpenPowerShellCommand(NTBase):
	"""Opens a new PowerShell terminal in the current directory."""

	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start powershell')

class RunPowerShellCommand(NTBase):
	"""Runs the current PowerShell document."""
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd /K "powershell ./{file} & pause & exit"')


#Linux Tools (Bash - Windows Subsystem for Linux)
class OpenBashCommand(NTBase):
	"""Opens a new Bash terminal in the current directory."""

	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start bash')

class RunPythonBashCommand(NTBase):
	"""Runs the current python document, using the currently installed linux version of python3."""

	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start bash -c "python3 {file};echo \\\"---------------------\\\";read -n 1 -s -r -p \\\"Press any key to continue...\\\"\"')

