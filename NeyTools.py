import sublime_plugin
import os

class NeyToolsBase(sublime_plugin.TextCommand):
	def runCommand(self, command):
		os.system(self.formatCommandWithPath(command))

	def getPathComponents(self):
		path = self.view.file_name()
		return (os.path.splitdrive(path)[0], os.path.dirname(path), os.path.basename(path))

	def formatCommandWithPath(self, command):
		drive, directory, file = self.getPathComponents()
		return command.format(drive=drive, directory=directory, file=file)

	@staticmethod
	def log(obj):
		os.system('echo "{}" & pause'.format(obj))


class OpenbashCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start bash')

class OpencmdCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd')

class OpenpowershellCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start powershell')

class RunpythonbashCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start bash -c "python3 {file};echo \\\"---------------------\\\";read -n 1 -s -r -p \\\"Press any key to continue...\\\"\"')

class RunpythonwinCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd /K "python3 {file} & pause & exit"')

class RunpowershellCommand(NeyToolsBase):
	def run(self, edit):
		self.runCommand('{drive} & cd "{directory}" & start cmd /K "powershell ./{file} & pause & exit"')