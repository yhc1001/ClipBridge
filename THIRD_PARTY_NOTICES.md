# Third-party components

ClipBridge uses Python, PySide6/Qt/Shiboken, pywin32, Pillow, cryptography and the PyInstaller bootloader. The portable distribution includes the license files installed with those packages in `licenses/`. `licenses/components.json` records the exact versions. PyInstaller and pytest also appear in the source/development environment.

Qt/PySide6 are dynamically loaded libraries. The ClipBridge source and build scripts are supplied to let the user rebuild the executable with modified compatible Qt/PySide6 libraries. PyInstaller's `--onedir` mode can be used in `tools/build_exe.py` instead of `--onefile` when a separate replaceable DLL directory is preferred.

Upstream sources:

- Python: https://www.python.org/downloads/source/
- PySide6/Shiboken: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt: https://code.qt.io/cgit/qt/
- pywin32: https://github.com/mhammond/pywin32
- Pillow: https://github.com/python-pillow/Pillow
- cryptography: https://github.com/pyca/cryptography
- PyInstaller: https://github.com/pyinstaller/pyinstaller

The individual third-party licenses apply to their respective components.
