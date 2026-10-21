"""Build the optional Windows service edition and its MSI in a clean checkout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clipbridge import __version__
from prepare_input_bundle import prepare

os.chdir(ROOT)
DESTINATION = ROOT / "dist" / ("v" + __version__)
PAYLOAD = ROOT / "dist/uac-payload"
component = prepare()
system = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), sys.base_prefix, str(system / "System32"), str(system), os.environ["PATH"]])


def freeze(entry, name, destination, extra=()):
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed", "--name", name,
        "--distpath", str(destination), "--workpath", str(ROOT / "build" / (name + "-installed")),
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtPdf", "--exclude-module", "tkinter", *extra, entry], check=True)


def identifier(path):
    return "f" + hashlib.sha256(path.encode()).hexdigest()[:30]


def installer():
    namespace = "http://wixtoolset.org/schemas/v4/wxs"
    ET.register_namespace("", namespace)
    def element(parent, tag, **attributes):
        return ET.SubElement(parent, "{" + namespace + "}" + tag, attributes)
    document = ET.Element("{" + namespace + "}Wix")
    package = element(document, "Package", Name="ClipBridge (UAC)", Manufacturer="ClipBridge", Version=__version__,
        UpgradeCode="4736D2D4-116F-4E35-A379-BA46B8442C34", Scope="perMachine", InstallerVersion="500", Language="1042")
    element(package, "MajorUpgrade", DowngradeErrorMessage="더 최신 ClipBridge UAC 버전이 설치되어 있습니다.")
    element(package, "MediaTemplate", EmbedCab="yes", CompressionLevel="high")
    directory = element(element(package, "StandardDirectory", Id="ProgramFiles64Folder"), "Directory", Id="INSTALLFOLDER", Name="ClipBridge")
    directories = {Path("."): directory}
    feature = element(package, "Feature", Id="Complete", Title="ClipBridge", Level="1")
    service_id = None
    for path in sorted(PAYLOAD.rglob("*")):
        relative = path.relative_to(PAYLOAD)
        if path.is_dir():
            directories[relative] = element(directories[relative.parent], "Directory", Id="d" + identifier(relative.as_posix()), Name=path.name)
            continue
        file_id = identifier(relative.as_posix())
        component_id = "c" + file_id
        group = element(directories[relative.parent], "Component", Id=component_id,
            Guid=str(uuid.uuid5(uuid.NAMESPACE_URL, "https://clipbridge.local/installed/" + relative.as_posix())))
        element(group, "File", Id=file_id, Source=str(path), KeyPath="yes")
        element(feature, "ComponentRef", Id=component_id)
        if relative.as_posix() == "InputService/ClipBridgeInputService.exe":
            service_id = file_id
            element(group, "ServiceInstall", Id="InputServiceInstall", Name="ClipBridgeInput", DisplayName="ClipBridge Input (UAC)",
                Description="ClipBridge 마우스·키보드 보안 화면 지원", Type="ownProcess", Start="auto", ErrorControl="normal", Account="LocalSystem", Vital="yes")
            element(group, "ServiceControl", Id="InputServiceControl", Name="ClipBridgeInput", Start="install", Stop="both", Remove="uninstall", Wait="yes")
    if not service_id:
        raise RuntimeError("Installed service executable missing")
    registration = element(directory, "Component", Id="ServiceRegistration", Guid="486DBCA4-BA92-48A0-9852-A3F5AF1E241B")
    element(registration, "RegistryValue", Root="HKLM", Key=r"SOFTWARE\ClipBridge\InputService", Name="OwnerSid", Value="[UserSID]", Type="string", KeyPath="yes")
    element(registration, "RegistryValue", Root="HKLM", Key=r"SOFTWARE\ClipBridge\InputService", Name="Executable", Value="[#" + service_id + "]", Type="string")
    element(feature, "ComponentRef", Id="ServiceRegistration")
    menu = element(element(package, "StandardDirectory", Id="ProgramMenuFolder"), "Directory", Id="ProgramMenuClipBridge", Name="ClipBridge")
    shortcut = element(menu, "Component", Id="MenuShortcut", Guid="0A2AE69C-6C37-4DD4-A810-08FD9FB661C2")
    element(shortcut, "Shortcut", Id="StartMenuShortcut", Name="ClipBridge", Target="[INSTALLFOLDER]ClipBridge.exe", WorkingDirectory="INSTALLFOLDER")
    element(shortcut, "RemoveFolder", Id="RemoveProgramMenu", On="uninstall")
    element(shortcut, "RegistryValue", Root="HKLM", Key=r"SOFTWARE\ClipBridge\InputService", Name="MenuInstalled", Type="integer", Value="1", KeyPath="yes")
    element(feature, "ComponentRef", Id="MenuShortcut")
    source = ROOT / "build/windows-uac.wxs"
    source.write_bytes(ET.tostring(document, encoding="utf-8", xml_declaration=True))
    DESTINATION.mkdir(parents=True, exist_ok=True)
    wix = ROOT / "build/wix-tool/wix.exe"
    if not wix.is_file():
        subprocess.run(["dotnet", "tool", "install", "wix", "--version", "4.0.6", "--tool-path", str(wix.parent)], check=True)
    target = DESTINATION / "ClipBridge-UAC-setup-x64.msi"
    subprocess.run([str(wix), "build", "-arch", "x64", str(source), "-o", str(target)], check=True,
                   env=dict(os.environ, DOTNET_ROLL_FORWARD="Major"))
    print("UAC installer built: " + str(target), flush=True)


if __name__ == "__main__":
    freeze("bootstrap.py", "ClipBridge", ROOT / "dist/uac-gui", ("--icon", "assets/clipbridge.ico", "--version-file", "assets/version_info.txt"))
    if PAYLOAD.exists():
        raise RuntimeError("Use a fresh build checkout for installed payload")
    shutil.copytree(ROOT / "dist/uac-gui/ClipBridge", PAYLOAD)
    shutil.copytree(component, PAYLOAD / "_internal/input-engine")
    freeze("service_bootstrap.py", "ClipBridgeInputService", ROOT / "dist/uac-service", ("--hidden-import", "win32timezone"))
    service = PAYLOAD / "InputService"
    shutil.copytree(ROOT / "dist/uac-service/ClipBridgeInputService", service)
    native = service / "_internal/input-engine"
    shutil.copytree(component, native)
    (native / "settings").mkdir()
    (native / "settings/Deskflow.conf").write_text("; ClipBridge installed input portable marker\n", encoding="utf-8")
    manifest = json.loads((native / "bundle.json").read_text())
    manifest["hashes"]["settings/Deskflow.conf"] = hashlib.sha256((native / "settings/Deskflow.conf").read_bytes()).hexdigest()
    (native / "bundle.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for folder in ("docs", "licenses"):
        shutil.copytree(ROOT / folder, PAYLOAD / folder)
    shutil.copyfile(ROOT / "THIRD_PARTY_NOTICES.md", PAYLOAD / "THIRD_PARTY_NOTICES.md")
    installer()
