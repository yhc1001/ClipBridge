"""Entry point for the installed, non-interactive Windows service executable."""
import servicemanager
from PySide6.QtCore import QCoreApplication
from clipbridge.windows_input_service import ClipBridgeInputService

application = QCoreApplication([])
servicemanager.Initialize()
servicemanager.PrepareToHostSingle(ClipBridgeInputService)
servicemanager.StartServiceCtrlDispatcher()
