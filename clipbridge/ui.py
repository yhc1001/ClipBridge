from __future__ import annotations

import dataclasses
import secrets
import sys
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkInterface
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
                             QPushButton, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from .config import ConfigStore, set_autostart
from . import __version__
from .clipboard import ClipboardWorker
from .files import TransferStore
from .model import FORMATS, Ledger, private_address
from .network import NetworkEngine
from .security import fingerprint, pairing_token, parse_pairing, protect


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
        self.setWindowTitle(f"ClipBridge {__version__} · 클립보드 연결")
        self.setWindowIcon(app_icon())
        self.resize(520, 450)
        self.clipboard = ClipboardWorker(config, self.ledger, self.local_copy, self.applied,
                                         lambda value: self.events.notification.emit("status", value))
        self.build_ui()
        self.build_tray()
        self.clipboard.start()
        QTimer.singleShot(0, self.reconnect)

    def build_ui(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel("ClipBridge")
        title.setStyleSheet("font-size: 25px; font-weight: 600; color: #1769c2;")
        layout.addWidget(title)
        self.connection = QLabel("연결 끊김")
        self.status = QLabel("최초 연결 설정을 완료하세요.")
        self.status.setWordWrap(True)
        self.last = QLabel("마지막 동기화: 없음")
        layout.addWidget(self.connection)
        layout.addWidget(self.status)
        layout.addWidget(self.last)
        group = QGroupBox("처음 한 번만 연결하세요")
        form = QFormLayout(group)
        self.role = QComboBox()
        self.role.addItem("허브 · 항상 켜 두는 newserver", "main")
        self.role.addItem("참여 컴퓨터 · Main / Mac 등", "server")
        self.role.setCurrentIndex(0 if self.config.role == "main" else 1)
        self.peer = QLineEdit(self.config.peer_ip)
        self.peer.setPlaceholderText("허브(newserver)의 LAN 또는 Tailscale IP")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.config.port)
        self.bind = QLineEdit(self.config.bind_ip)
        self.pair_state = QLabel()
        self.update_pair_state()
        form.addRow("1. 이 컴퓨터", self.role)
        form.addRow("2. 허브 IP 주소", self.peer)
        own_ip = QPushButton("내 IP 주소 확인")
        own_ip.clicked.connect(self.show_addresses)
        form.addRow(own_ip)
        form.addRow("인증", self.pair_state)
        buttons = QHBoxLayout()
        for text, function in (("연결 코드 복사", self.copy_code), ("연결 코드 붙여넣기", self.import_code)):
            button = QPushButton(text)
            button.clicked.connect(function)
            buttons.addWidget(button)
        form.addRow("3. 연결 코드", buttons)
        layout.addWidget(group)
        self.devices_group = QGroupBox("등록한 컴퓨터 · 허브 1대 + 참여 컴퓨터 최대 16대")
        devices_layout = QVBoxLayout(self.devices_group)
        self.devices = QListWidget()
        self.devices.setMaximumHeight(100)
        devices_layout.addWidget(self.devices)
        remove = QPushButton("선택한 컴퓨터 연결 해제")
        remove.clicked.connect(self.remove_device)
        devices_layout.addWidget(remove)
        layout.addWidget(self.devices_group)
        self.refresh_devices()
        options = QGroupBox("자동으로 공유할 내용")
        form = QFormLayout(options)
        self.text, self.images, self.files, self.autostart = QCheckBox("글자와 서식"), QCheckBox("이미지"), QCheckBox("파일 · 연결된 컴퓨터끼리 자동 공유"), QCheckBox("로그인하면 자동으로 켜기")
        for checkbox, key in ((self.text, "text"), (self.images, "images"), (self.files, "files"), (self.autostart, "autostart")):
            checkbox.setChecked(getattr(self.config, key))
            form.addRow(checkbox)
        self.direction = QComboBox()
        self.direction.addItem("양방향", "both")
        self.direction.addItem("허브 → 참여 컴퓨터만", "main_to_server")
        self.direction.setCurrentIndex(0 if self.config.direction == "both" else 1)
        self.file_policy = QComboBox()
        for label, value in (("확인 없이 자동 수신 (기본)", "allow"), ("전송마다 확인 (선택)", "ask"), ("파일 수신·전송 차단", "block")):
            self.file_policy.addItem(label, value)
        self.file_policy.setCurrentIndex(self.file_policy.findData(self.config.file_policy))
        self.clip_limit, self.file_limit = QSpinBox(), QSpinBox()
        self.clip_limit.setRange(1, 128)
        self.file_limit.setRange(1, 1024)
        self.clip_limit.setValue(self.config.clip_limit_mb)
        self.file_limit.setValue(self.config.file_limit_mb)
        layout.addWidget(options)
        advanced_toggle = QPushButton("고급 설정 보기")
        advanced_toggle.setCheckable(True)
        advanced = QGroupBox("고급 설정")
        advanced_form = QFormLayout(advanced)
        advanced_form.addRow("연결 포트 (양쪽 동일)", self.port)
        advanced_form.addRow("허브 수신 IP", self.bind)
        advanced_form.addRow("공유 방향", self.direction)
        advanced_form.addRow("파일 수신 방식", self.file_policy)
        advanced_form.addRow("클립보드 제한 (MiB)", self.clip_limit)
        advanced_form.addRow("파일 합계 제한 (MiB)", self.file_limit)
        reset = QPushButton("등록한 컴퓨터 연결 초기화")
        reset.clicked.connect(self.reset_pair)
        advanced_form.addRow(reset)
        advanced.hide()
        advanced_toggle.toggled.connect(advanced.setVisible)
        advanced_toggle.toggled.connect(lambda checked: advanced_toggle.setText("고급 설정 접기" if checked else "고급 설정 보기"))
        layout.addWidget(advanced_toggle)
        layout.addWidget(advanced)
        actions = QHBoxLayout()
        save, reconnect, self.pause = QPushButton("저장 및 연결"), QPushButton("재연결"), QPushButton("재개" if self.config.paused else "일시 중지")
        save.clicked.connect(self.save_settings)
        reconnect.clicked.connect(self.reconnect)
        self.pause.clicked.connect(self.toggle_pause)
        for button in (save, reconnect, self.pause):
            actions.addWidget(button)
        layout.addLayout(actions)
        note = QLabel("연결되면 평소처럼 복사하고 붙여넣으세요.\n창을 닫아도 " + ("메뉴 막대" if sys.platform == "darwin" else "트레이") + "에서 계속 실행됩니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.setCentralWidget(widget)
        self.role.currentIndexChanged.connect(self.role_view)
        self.role_view()

    def role_view(self):
        hub = self.role.currentData() == "main"
        self.peer.setEnabled(not hub)
        self.peer.setPlaceholderText("허브에서는 입력하지 않아도 됩니다" if hub else "허브(newserver)의 LAN 또는 Tailscale IP")
        self.devices_group.setVisible(hub)

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
        menu.addAction("재연결", self.reconnect)
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

    def show_addresses(self):
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
        QMessageBox.information(self, "내 IP 주소", "허브에서 확인한 주소를 참여 컴퓨터의 ‘허브 IP 주소’에 넣으세요.\n\n" + ("\n".join(addresses) or "LAN 또는 Tailscale에 연결한 뒤 다시 확인하세요."))

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
        except Exception as error:
            QMessageBox.warning(self, "설정 확인", str(error) if isinstance(error, ValueError) else "설정을 저장하지 못했습니다. 사용자 권한과 AppData를 확인하세요.")

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
        if kind == "pair":
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
        self.tray.showMessage("ClipBridge 승인 필요", "설정 창에서 " + ("장치 연결" if kind == "pair" else "파일 수신") + "을 승인하세요.")

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
        for box in list(self.boxes):
            box.reject()
        self.stop_network()
        self.clipboard.stop()
        self.transfers.close()
        self.tray.hide()
        QApplication.instance().quit()
