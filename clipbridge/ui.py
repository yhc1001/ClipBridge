from __future__ import annotations

import dataclasses
import concurrent.futures
import copy
import secrets
import sys
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                             QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from .config import ConfigStore, set_autostart
from . import __version__
from .clipboard import ClipboardWorker
from .files import TransferStore
from .model import FORMATS, MAX_CLIP, MAX_TOTAL, Ledger, private_address
from .network import NetworkEngine
from .security import fingerprint, pairing_token, parse_pairing, protect, unprotect
from .input_engine import InputManager
from .input_setup import InputSetup


class Events(QObject):
    notification = Signal(str, object)
    approval = Signal(str, object, object)
    paired = Signal(str)


def app_icon(connected=False, paused=False):
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1769c2"))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
    painter.setPen(QColor("white"))
    painter.drawRoundedRect(14, 19, 26, 32, 3, 3)
    painter.drawRoundedRect(23, 12, 26, 32, 3, 3)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#f3b51c" if paused else "#24b568" if connected else "#9aa6b6"))
    painter.drawEllipse(44, 44, 18, 18)
    painter.end()
    return QIcon(pixmap)


class Window(QMainWindow):
    def __init__(self, store: ConfigStore, config):
        super().__init__()
        self.store, self.config = store, config
        self.events = Events()
        self.events.notification.connect(self.notification)
        self.events.approval.connect(self.approval)
        self.events.paired.connect(self.paired)
        self.ledger = Ledger(config.device_id)
        self.transfers = TransferStore(store.directory)
        self.network = None
        self.connected = False
        self.online_devices = set()
        self.closing = False
        self.boxes = []
        self.input_setup_status = "Main 연결 준비 중…"
        self.input_manager = InputManager(config, store.directory, self.events.notification.emit, self)
        self.input_setup = InputSetup(config, self.queue_input_settings, self.events.notification.emit, self.events.approval.emit)
        self.setWindowTitle(f"ClipBridge {__version__} · PC 연결")
        self.setWindowIcon(app_icon())
        self.resize(700, 740)
        self.clipboard = ClipboardWorker(config, self.ledger, self.local_copy, self.applied,
                                         lambda value: self.events.notification.emit("status", value))
        self.build_ui()
        self.build_tray()
        self.clipboard.start()
        self.input_setup.start()
        QTimer.singleShot(0, self.reconnect)
        QTimer.singleShot(0, self.input_manager.start)

    def build_ui(self):
        # Legacy connection controls stay out of the product flow. Their values
        # are retained for existing configuration/advanced-save compatibility.
        self.role = QComboBox(self)
        self.role.addItem("연결받는 PC", "main")
        self.role.addItem("연결하는 PC", "server")
        self.role.setCurrentIndex(0 if self.config.role == "main" else 1)
        self.peer, self.bind = QLineEdit(self.config.peer_ip, self), QLineEdit(self.config.bind_ip, self)
        self.port = QSpinBox(self)
        self.port.setRange(1024, 65535)
        self.port.setValue(self.config.port)
        self.pair_state = QLabel(self)
        self.devices_group = QGroupBox(self)
        self.devices = QListWidget(self.devices_group)
        for control in (self.role, self.peer, self.bind, self.port, self.pair_state, self.devices_group):
            control.hide()
        self.update_pair_state()
        self.refresh_devices()

        self.advanced_dialog = QDialog(self)
        self.advanced_dialog.setWindowTitle("ClipBridge · 고급 설정")
        self.advanced_dialog.resize(490, 470)
        advanced_layout = QVBoxLayout(self.advanced_dialog)
        advanced_scroll = QScrollArea()
        advanced_scroll.setWidgetResizable(True)
        fields = QWidget()
        form = QFormLayout(fields)
        self.text, self.images, self.files = QCheckBox("텍스트와 서식"), QCheckBox("이미지"), QCheckBox("파일·폴더")
        self.autostart = QCheckBox("로그인하면 자동 실행")
        for control, key in ((self.text, "text"), (self.images, "images"), (self.files, "files"), (self.autostart, "autostart")):
            control.setChecked(getattr(self.config, key))
            form.addRow(control)
        self.direction = QComboBox(self)
        self.direction.addItem("양방향", "both")
        self.direction.addItem("연결받는 PC → 다른 PC", "main_to_server")
        self.direction.setCurrentIndex(0 if self.config.direction == "both" else 1)
        self.direction.hide()
        self.file_policy = QComboBox()
        for label, value in (("자동으로 수신", "allow"), ("전송마다 확인", "ask"), ("파일 공유 차단", "block")):
            self.file_policy.addItem(label, value)
        self.file_policy.setCurrentIndex(self.file_policy.findData(self.config.file_policy))
        self.clip_limit, self.file_limit = QSpinBox(), QSpinBox()
        self.clip_limit.setRange(1, MAX_CLIP // 1024**2)
        self.file_limit.setRange(1, MAX_TOTAL // 1024**2)
        self.clip_limit.setValue(self.config.clip_limit_mb)
        self.file_limit.setValue(self.config.file_limit_mb)
        form.addRow("파일 수신", self.file_policy)
        form.addRow("클립보드 용량 (MiB)", self.clip_limit)
        form.addRow("파일 용량 (MiB)", self.file_limit)
        self.pause = QPushButton("재개" if self.config.paused else "일시 중지")
        self.pause.clicked.connect(self.toggle_pause)
        form.addRow("클립보드 동기화", self.pause)
        reconnect = QPushButton("연결 다시 시도")
        reconnect.clicked.connect(self.reconnect_all)
        form.addRow(reconnect)
        advanced_scroll.setWidget(fields)
        advanced_layout.addWidget(advanced_scroll)
        advanced_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        advanced_buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        advanced_buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        advanced_buttons.accepted.connect(self.save_advanced)
        advanced_buttons.rejected.connect(self.advanced_dialog.reject)
        self.advanced_dialog.rejected.connect(self.load_advanced)
        advanced_layout.addWidget(advanced_buttons)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("ClipBridge")
        title.setStyleSheet("font-size: 25px; font-weight: 600; color: #1769c2;")
        layout.addWidget(title)
        self.connection = QLabel("연결 요청 대기 중")
        layout.addWidget(self.connection)
        self.status = QLabel("IP 입력 → 상대 PC에서 승인하면 클립보드와 화면이 함께 연결됩니다.")
        self.status.setWordWrap(True)
        self.last = QLabel("마지막 복사: 없음")
        self.input_status = QLabel("마우스·키보드: 연결 대기 중")
        self.input_status.setWordWrap(True)
        from .input_ui import InputDialog
        self.input_dialog = InputDialog(self, embedded=True)
        layout.addWidget(self.input_dialog, 1)
        self.mouse_toggle = QCheckBox("마우스·키보드 공유")
        self.mouse_toggle.setChecked(self.config.mouse_enabled)
        self.mouse_toggle.toggled.connect(self.toggle_mouse)
        layout.addWidget(self.mouse_toggle)
        layout.addWidget(self.input_status)
        layout.addWidget(self.last)
        layout.addWidget(self.status)
        bottom = QHBoxLayout()
        advanced = QPushButton("고급 설정…")
        advanced.clicked.connect(self.show_advanced)
        bottom.addWidget(advanced)
        layout.addLayout(bottom)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.setCentralWidget(scroll)

    def toggle_mouse(self, enabled):
        from .input_engine import defaults
        self.config.mouse_enabled = enabled
        value = {**defaults(), **self.config.input_settings}
        trusted = value["trusted_servers"] if value["mode"] == "client" else value["trusted_clients"]
        value["enabled"] = bool(enabled and trusted)
        self.apply_input_settings(value)
        try:
            self.input_setup.publish()
        except ValueError:
            pass

    def reconnect_all(self):
        self.reconnect()
        value = self.config.input_settings
        if value.get("easy_controller"):
            try:
                self.input_setup.connect_to(value["server_ip"], value.get("easy_setup_port", 24802))
            except ValueError as error:
                self.status.setText(str(error))
        self.input_manager.stop()
        self.input_manager.start()

    def load_advanced(self):
        for control, key in ((self.text, "text"), (self.images, "images"), (self.files, "files"), (self.autostart, "autostart")):
            control.setChecked(getattr(self.config, key))
        self.port.setValue(self.config.port)
        self.bind.setText(self.config.bind_ip)
        self.direction.setCurrentIndex(self.direction.findData(self.config.direction))
        self.file_policy.setCurrentIndex(self.file_policy.findData(self.config.file_policy))
        self.clip_limit.setValue(self.config.clip_limit_mb)
        self.file_limit.setValue(self.config.file_limit_mb)

    def show_advanced(self):
        self.load_advanced()
        self.advanced_dialog.show()
        self.advanced_dialog.raise_()
        self.advanced_dialog.activateWindow()

    def save_advanced(self):
        if self.save_settings():
            self.advanced_dialog.accept()

    def role_view(self):
        hub = self.role.currentData() == "main"
        self.peer.setEnabled(not hub)
        self.peer.setPlaceholderText("허브에서는 입력하지 않아도 됩니다" if hub else "허브(newserver)의 LAN 또는 Tailscale IP")
        self.devices_group.setVisible(hub)

    def show_input_settings(self):
        from .input_ui import InputDialog
        if not getattr(self, "input_dialog", None):
            self.input_dialog = InputDialog(self)
        else:
            self.input_dialog.data = {**self.input_dialog.data, **self.config.input_settings}
            self.input_dialog.load()
        if not self.input_dialog.isWindow():
            self.show_settings()
            return
        self.input_dialog.show()
        self.input_dialog.raise_()
        self.input_dialog.activateWindow()

    def queue_input_settings(self, settings, show=False, clipboard=None):
        future = concurrent.futures.Future()
        self.events.notification.emit("input_configure", {"settings": settings, "show": show, "clipboard": clipboard, "future": future})
        return future

    def apply_input_settings(self, settings, show=False, clipboard=None):
        from .input_engine import defaults, validate
        from .service_policy import public_settings
        validate(settings)
        previous = self.config.input_settings
        old_config = dataclasses.asdict(self.config)
        before, after = public_settings({**defaults(), **previous}), public_settings(settings)
        if before["mode"] == after["mode"] == "client":
            before.pop("screens")
            after.pop("screens")
        self.config.input_settings = copy.deepcopy(settings)
        try:
            for key, value in (clipboard or {}).items():
                if key not in {"role", "peer_ip", "peer_id", "peer_pin", "port", "protected_secret", "trusted_peers"}:
                    raise ValueError("Invalid connection configuration")
                setattr(self.config, key, copy.deepcopy(value))
            self.store.save(self.config)
        except Exception:
            for key, value in old_config.items():
                setattr(self.config, key, value)
            raise
        endpoint = ("role", "peer_ip", "peer_id", "peer_pin", "port")
        changed = any(getattr(self.config, key) != old_config[key] for key in endpoint)
        if self.config.role == "server" and "protected_secret" in (clipboard or {}):
            changed |= self.config.secret != unprotect(old_config["protected_secret"])
        changed |= bool(set(old_config["trusted_peers"]) - set(self.config.trusted_peers))
        self.role.setCurrentIndex(0 if self.config.role == "main" else 1)
        self.peer.setText(self.config.peer_ip)
        self.port.setValue(self.config.port)
        self.refresh_devices()
        self.update_pair_state()
        if changed:
            self.reconnect()
        if before != after:
            self.input_manager.stop()
            self.input_manager.start()
        if not settings["enabled"]:
            self.input_status.setText("마우스·키보드 공유: 꺼짐")
        if getattr(self, "input_dialog", None):
            self.input_dialog.data = copy.deepcopy(settings)
            self.input_dialog.load()
        if show:
            self.show_input_settings()

    def refresh_devices(self):
        self.devices.clear()
        for device, record in self.config.trusted_peers.copy().items():
            state = "연결됨" if device in self.online_devices else "연결 끊김"
            self.devices.addItem(f"{record.get('name', '컴퓨터')} · {device[:8]} · {state}")
            self.devices.item(self.devices.count() - 1).setData(Qt.ItemDataRole.UserRole, device)

    def remove_device(self):
        item = self.devices.currentItem()
        if not item:
            return
        device = item.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.question(self, "장치 연결 해제", "이 컴퓨터의 접속 권한을 없앨까요? 다시 연결하려면 새 연결 코드와 승인이 필요합니다.") != QMessageBox.StandardButton.Yes:
            return
        self.stop_network()
        self.config.trusted_peers.pop(device, None)
        self.config.file_allow_ids = [value for value in self.config.file_allow_ids if value != device]
        self.store.save(self.config)
        self.update_pair_state()
        self.refresh_devices()
        self.reconnect()

    def build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        menu.addAction("ClipBridge 설정", self.show_settings)
        self.pause_action = menu.addAction("재개" if self.config.paused else "일시 중지", self.toggle_pause)
        menu.addAction("재연결", self.reconnect_all)
        menu.addSeparator()
        menu.addAction("종료", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_settings() if reason in (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger) else None)
        self.tray.setToolTip("ClipBridge · 연결 끊김")
        self.tray.show()

    def show_settings(self):
        self.show()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def device_addresses():
        addresses = []
        for address in QNetworkInterface.allAddresses():
            if address.isLoopback():
                continue
            try:
                value = private_address(address.toString())
                if value not in addresses:
                    addresses.append(value)
            except ValueError:
                pass
        return addresses

    def show_addresses(self):
        addresses = self.device_addresses()
        QMessageBox.information(self, "이 PC의 IP 주소", "다른 PC에서 아래 주소를 입력하고 연결 요청을 보내세요.\n이 PC에서 한 번 승인하면 연결됩니다.\n\n" + ("\n".join(addresses) or "LAN 또는 Tailscale에 연결한 뒤 다시 확인하세요."))

    def update_pair_state(self):
        self.pair_state.setText(f"참여 컴퓨터 {len(self.config.trusted_peers)}대 등록" if self.config.role == "main" else "허브 등록됨" if self.config.peer_id else "허브의 연결 코드를 붙여넣으세요")

    def save_settings(self):
        candidate = dataclasses.replace(self.config, role=self.role.currentData(), peer_ip=self.peer.text().strip(), bind_ip=self.bind.text().strip(), port=self.port.value(),
                                        text=self.text.isChecked(), images=self.images.isChecked(), files=self.files.isChecked(), autostart=self.autostart.isChecked(),
                                        direction=self.direction.currentData(), file_policy=self.file_policy.currentData(), clip_limit_mb=self.clip_limit.value(), file_limit_mb=self.file_limit.value())
        try:
            if candidate.role == "main" and self.config.role != "main":
                candidate.peer_id = candidate.peer_pin = ""
                candidate.trusted_peers = {}
                candidate.file_allow_ids = []
                candidate.protected_secret = protect(secrets.token_bytes(32))
            candidate.validate()
            set_autostart(candidate.autostart)
            self.stop_network()
            for field in dataclasses.fields(candidate):
                setattr(self.config, field.name, getattr(candidate, field.name))
            self.store.save(self.config)
            self.update_pair_state()
            self.refresh_devices()
            self.reconnect()
            return True
        except Exception as error:
            QMessageBox.warning(self, "설정 확인", str(error) if isinstance(error, ValueError) else "설정을 저장하지 못했습니다. 사용자 권한과 AppData를 확인하세요.")
            return False

    def copy_code(self):
        if self.config.role != "main":
            QMessageBox.information(self, "역할 확인", "허브 컴퓨터에서 코드를 복사하세요. 역할을 바꿨다면 먼저 저장 및 연결을 누르세요.")
            return
        self.clipboard.copy_private_text(pairing_token(self.config))
        self.status.setText("코드를 복사했습니다. 참여 컴퓨터 1대에 붙여넣고, 이 허브에서 연결을 승인하세요.")

    def import_code(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("연결 코드 붙여넣기")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("허브(newserver)에서 새로 복사한 연결 코드를 붙여넣으세요."))
        code = QLineEdit()
        code.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(code)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            peer_id, pin, secret = parse_pairing(code.text().strip())
            if peer_id == self.config.device_id:
                raise ValueError("다른 PC에 설치된 허브의 연결 코드가 필요합니다.")
            self.stop_network()
            self.config.peer_id, self.config.peer_pin, self.config.protected_secret = peer_id, pin, protect(secret)
            self.config.role = "server"
            self.config.trusted_peers = {}
            self.config.file_allow_ids = []
            self.role.setCurrentIndex(1)
            self.store.save(self.config)
            self.update_pair_state()
            self.role_view()
            self.status.setText("준비됐습니다. 허브 IP를 넣고 저장 및 연결을 누르세요.")
        except Exception:
            QMessageBox.warning(self, "코드 확인", "연결 코드를 확인하세요. 서로 다른 PC의 코드가 필요합니다.")

    def reset_pair(self):
        answer = QMessageBox.question(self, "신뢰 초기화", "현재 연결을 끊고 모든 등록 장치와 연결 코드를 폐기할까요? 각 컴퓨터를 다시 연결해야 합니다.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.stop_network()
        self.config.peer_id = self.config.peer_pin = ""
        self.config.trusted_peers = {}
        self.config.file_allow_ids = []
        self.config.protected_secret = protect(secrets.token_bytes(32))
        self.config.file_policy = "allow"
        self.file_policy.setCurrentIndex(self.file_policy.findData("allow"))
        self.store.save(self.config)
        self.update_pair_state()
        self.refresh_devices()
        self.status.setText("신뢰를 초기화했습니다. 허브에서 새 연결 코드를 복사하세요.")

    def stop_network(self):
        if self.network:
            self.network.stop()
            self.network = None

    def reconnect(self):
        self.stop_network()
        try:
            self.config.validate()
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.network = NetworkEngine(self.config, self.ledger, self.transfers, self.clipboard.apply,
                                     self.events.notification.emit, self.events.approval.emit, self.events.paired.emit, self.store.save)
        self.network.start()

    def local_copy(self, snapshot):
        if self.network:
            self.network.submit(snapshot)

    def applied(self, snapshot):
        self.events.notification.emit("received", ["파일"] if snapshot.paths else list(snapshot.formats))

    def paired(self, peer_id):
        self.update_pair_state()
        self.refresh_devices()

    def notification(self, kind, info):
        if self.closing:
            if kind == "input_configure" and not info["future"].done():
                info["future"].set_exception(RuntimeError("Application is closing"))
            return
        if kind == "input_configure":
            future = info["future"]
            if future.done():
                return
            try:
                self.apply_input_settings(info["settings"], info["show"], info.get("clipboard"))
                future.set_result(True)
            except Exception as error:
                if not future.done():
                    future.set_exception(error)
            return
        if kind == "input_setup_status":
            self.input_setup_status = str(info)
            if getattr(self, "input_dialog", None):
                self.input_dialog.status.setText(str(info))
                self.input_dialog.connect_button.setEnabled(not str(info).startswith(("Main 연결 중", "Main에서 승인을")))
            return
        if kind == "input_setup_devices":
            return
        if kind == "input_status":
            self.input_status.setText(str(info))
            return
        if kind == "connected":
            self.connected = int(info)
            self.update_connection()
        elif kind == "devices":
            self.online_devices = set(info)
            self.refresh_devices()
        elif kind == "status":
            self.status.setText(str(info))
        elif kind in ("sent", "received"):
            formats = [name for name in info if name in FORMATS or name == "파일"] if isinstance(info, list) else []
            time = datetime.now().strftime("%H:%M:%S")
            self.last.setText(f"마지막 동기화: {time} · {'송신 완료' if kind == 'sent' else '수신 완료'} · {', '.join(formats)}")
            self.status.setText("참여 컴퓨터에 적용 완료 · 각 컴퓨터에서 수신 상태를 확인할 수 있습니다." if kind == "sent" and self.config.role == "main" else "허브에 적용 완료 · 다른 참여 컴퓨터로 전달 중" if kind == "sent" else "이 PC에서 바로 붙여넣을 수 있습니다.")

    def update_connection(self):
        label = "일시 중지" if self.config.paused else f"연결됨 · {self.connected}대" if self.connected else "연결 끊김"
        self.connection.setText(label)
        self.tray.setIcon(app_icon(self.connected, self.config.paused))
        self.tray.setToolTip("ClipBridge · " + label)

    def toggle_pause(self):
        self.config.paused = not self.config.paused
        self.store.save(self.config)
        self.pause.setText("재개" if self.config.paused else "일시 중지")
        self.pause_action.setText(self.pause.text())
        self.update_connection()

    def approval(self, kind, info, future):
        if future.done() or self.closing:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if kind == "input_pair":
            box.setWindowTitle("PC 연결 승인")
            box.setText(f"{info['name']} ({info['ip']})에서 연결을 요청했습니다.\n\n확인 번호: {info['code']}\n상대 PC에 표시된 번호와 같은지 확인하세요.\n\n허용하면 클립보드·파일·화면 배치가 함께 연결됩니다. 마우스 공유는 ON/OFF로 바꿀 수 있습니다.")
            box.button(QMessageBox.StandardButton.Yes).setText("연결 허용")
            box.button(QMessageBox.StandardButton.No).setText("거절")
        elif kind == "pair":
            box.setWindowTitle("새 장치 연결 승인")
            box.setText(f"{info.get('name', '컴퓨터')} ({info['ip']})에서 접속했습니다.\n장치 ID: {info['device']}\n이 컴퓨터를 계속 신뢰할까요?")
        else:
            box.setWindowTitle("파일 수신 승인")
            box.setText(f"장치 {info['device'][:8]}에서 파일/폴더 {info['count']}개를 전송합니다.\n합계: {info['total'] / 1024**2:.2f} MiB\n수신하여 클립보드에 등록할까요?")
            remember = QCheckBox("이 장치의 다음 파일도 항상 허용")
            box.setCheckBox(remember)
        self.boxes.append(box)
        def completed(result):
            if box in self.boxes:
                self.boxes.remove(box)
            if not future.done():
                approved = result == QMessageBox.StandardButton.Yes
                if kind == "files" and approved and box.checkBox().isChecked():
                    self.config.file_allow_ids = list(dict.fromkeys(self.config.file_allow_ids + [info["device"]]))[-32:]
                    self.store.save(self.config)
                future.set_result(approved)
        box.finished.connect(completed)
        timer = QTimer(box)
        timer.timeout.connect(lambda: box.reject() if future.done() else None)
        timer.start(250)
        box.open()
        self.tray.showMessage("ClipBridge 승인 필요", "설정 창에서 " + ("마우스·키보드 연결" if kind == "input_pair" else "장치 연결" if kind == "pair" else "파일 수신") + "을 승인하세요.")

    def closeEvent(self, event):
        if not self.closing and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.accept()

    def quit(self):
        if self.closing:
            return
        self.closing = True
        self.input_setup.stop()
        self.input_manager.stop()
        for box in list(self.boxes):
            box.reject()
        self.stop_network()
        self.clipboard.stop()
        self.transfers.close()
        self.tray.hide()
        QApplication.instance().quit()
