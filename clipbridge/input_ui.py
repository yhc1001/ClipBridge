"""ClipBridge input setup in its own scrollable dialog."""
import sys

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QBrush, QColor, QPen, QFontMetrics
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .input_engine import connection_code, defaults, parse_code, validate


class ComputerTile(QGraphicsRectItem):
    def __init__(self, owner, row, name, x, y):
        super().__init__(0, 0, 112, 65)
        self.owner, self.row = owner, row
        self.setBrush(QBrush(QColor("#eaf3ff")))
        self.setPen(QPen(QColor("#1769c2"), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        label = QGraphicsSimpleTextItem("", self)
        text = name + (" · 이 PC" if name == owner.data["name"] else "")
        label.setText(QFontMetrics(label.font()).elidedText(text, Qt.TextElideMode.ElideRight, 96))
        self.setToolTip(text)
        label.setPos(8, 23)
        self.setPos(x * 132, y * 85)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        x, y = max(0, min(8, round(self.x() / 132))), max(0, min(8, round(self.y() / 85)))
        self.owner.move_screen(self.row, x, y)


class InputDialog(QDialog):
    def __init__(self, owner, embedded=False):
        super().__init__(owner)
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.owner = owner
        self.setWindowTitle("ClipBridge · 마우스·키보드 / 화면 배치")
        self.resize(680, 510)
        self.data = {**defaults(), **owner.config.input_settings}
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        note = QLabel("한 PC는 ClipBridge를 켜 두세요. 다른 PC에서 그 IP를 입력하세요.\n한 번 승인하면 클립보드·파일·화면 배치가 함께 연결됩니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.advanced_dialog = QDialog(self)
        self.advanced_dialog.setWindowTitle("마우스·키보드 · 고급 설정")
        self.advanced_dialog.resize(540, 460)
        advanced_layout = QVBoxLayout(self.advanced_dialog)
        form = QFormLayout()
        self.enabled = QCheckBox("ClipBridge에서 마우스·키보드도 공유")
        self.mode = QComboBox()
        self.mode.addItem("이 컴퓨터의 마우스·키보드 사용 (서버)", "server")
        self.mode.addItem("다른 컴퓨터의 마우스·키보드 받기 (클라이언트)", "client")
        self.name, self.address = QLineEdit(), QLineEdit()
        self.address.setPlaceholderText("Main PC의 LAN / Tailscale IP 입력")
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.delay = QSpinBox()
        self.delay.setRange(0, 5000)
        self.delay.setSuffix(" ms")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(.1, 10)
        self.scale.setSingleStep(.1)
        self.invert = QCheckBox("스크롤 방향 반대로")
        self.relative = QCheckBox("상대 좌표 마우스 이동")
        form.addRow(self.enabled)
        edition = "내장 · 별도 설치 필요 없음"
        if sys.platform == "win32":
            from .windows_service_client import installation
            edition = "UAC 지원 · Windows 서비스" if installation() else "일반 포터블 · UAC 입력은 설치형에서 지원"
        form.addRow("마우스·키보드 엔진", QLabel(edition))
        form.addRow("이 컴퓨터 역할", self.mode)
        form.addRow("이 컴퓨터 이름", self.name)
        form.addRow("마우스 포트", self.port)
        form.addRow("화면 전환 지연", self.delay)
        form.addRow("스크롤 배율", self.scale)
        form.addRow(self.invert)
        form.addRow(self.relative)
        advanced_layout.addLayout(form)
        advanced_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        advanced_buttons.button(QDialogButtonBox.StandardButton.Save).setText("설정 저장")
        advanced_buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        advanced_buttons.accepted.connect(self.save_advanced)
        advanced_buttons.rejected.connect(self.advanced_dialog.reject)
        advanced_layout.addWidget(advanced_buttons)
        address_row = QHBoxLayout()
        address_row.addWidget(self.address, 1)
        self.connect_button = QPushButton("연결 요청")
        self.connect_button.clicked.connect(self.request_connection)
        address_row.addWidget(self.connect_button)
        layout.addLayout(address_row)
        addresses = owner.device_addresses()
        ipv4 = [address for address in addresses if ":" not in address]
        own_ip = QLabel("이 PC 주소: " + (" / ".join((ipv4 or addresses)[:2]) or "LAN 또는 Tailscale 연결을 확인하세요"))
        own_ip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        own_ip.setWordWrap(True)
        layout.addWidget(own_ip)
        self.status = QLabel(getattr(owner, "input_setup_status", "Main에 승인 요청을 보내면 화면이 자동 등록됩니다."))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("연결된 화면 · 양쪽 PC에서 카드를 옮기면 배치가 함께 바뀝니다."))
        self.scene = QGraphicsScene(self)
        self.preview = QGraphicsView(self.scene)
        self.preview.setMinimumHeight(250)
        layout.addWidget(self.preview)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["컴퓨터 이름", "X (가로)", "Y (세로)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        self.table.cellChanged.connect(lambda row, column: self.refresh_preview())
        self.table.setParent(widget)
        self.table.hide()  # model for the cards; coordinates are never a user form
        self.trust = QLabel()
        advanced_layout.insertWidget(1, self.trust)
        if not embedded:
            tip = QLabel("Scroll Lock: 화면 이동 잠금/해제. Mac은 입력 권한 허용이 필요할 수 있습니다. Linux는 X11에서 사용하세요.")
            tip.setWordWrap(True)
            layout.addWidget(tip)
        scroll.setWidget(widget)
        outer.addWidget(scroll)
        bottom = QHBoxLayout()
        advanced = QPushButton("고급 설정…")
        advanced.clicked.connect(self.advanced_dialog.show)
        if not embedded:
            bottom.addWidget(advanced)
        self.disconnect_button = QPushButton("선택 PC 연결 해제")
        self.disconnect_button.clicked.connect(self.disconnect_selected)
        bottom.addWidget(self.disconnect_button)
        outer.addLayout(bottom)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("배치 적용")
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("닫기")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        if embedded:
            buttons.button(QDialogButtonBox.StandardButton.Close).hide()
        if not embedded:
            outer.addWidget(buttons)
        self.load()

    def watch(self, future, enable=True):
        timer = QTimer(self)
        def done():
            if not future.done():
                return
            timer.stop()
            timer.deleteLater()
            if enable:
                self.connect_button.setEnabled(True)
            try:
                future.result()
            except Exception as error:
                self.status.setText(str(error) if isinstance(error, ValueError) else "연결 설정을 적용하지 못했습니다.")
        timer.timeout.connect(done)
        timer.start(100)

    def request_connection(self):
        try:
            self.connect_button.setEnabled(False)
            self.watch(self.owner.input_setup.connect_to(self.address.text().strip()), enable=False)
            self.status.setText("Main에 연결 요청 중…")
        except Exception as error:
            self.connect_button.setEnabled(True)
            self.status.setText(str(error))

    def disconnect_selected(self):
        selected = self.scene.selectedItems()
        name = None
        for item in selected:
            if isinstance(item, ComputerTile):
                name = self.table.item(item.row, 0).text()
                break
        if self.data.get("easy_controller"):
            name = self.data["name"]
        if not name:
            self.status.setText("연결을 해제할 화면 카드를 먼저 선택하세요.")
            return
        if QMessageBox.question(self, "연결 해제", "선택 PC의 마우스·키보드 연결을 해제할까요?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.watch(self.owner.input_setup.disconnect(name))
        except Exception as error:
            self.status.setText(str(error))

    def save_advanced(self):
        try:
            value = self.collect()
            if value.get("easy_controller"):
                value["easy_paused"] = not value["enabled"]
            validate(value)
            self.owner.apply_input_settings(value, False)
            self.owner.input_setup.publish()
            self.advanced_dialog.accept()
        except Exception as error:
            QMessageBox.warning(self, "마우스 설정", str(error))

    def add_screen(self, name, x, y):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((name, x, y)):
            self.table.setItem(row, column, QTableWidgetItem(str(value)))

    def remove_screen(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.refresh_preview()

    def next_position(self):
        occupied = set()
        for row in range(self.table.rowCount()):
            try:
                occupied.add((int(self.table.item(row, 1).text()), int(self.table.item(row, 2).text())))
            except (AttributeError, ValueError):
                pass
        for y in range(9):
            for x in range(9):
                if (x, y) not in occupied and any(abs(x - a) + abs(y - b) == 1 for a, b in occupied):
                    return x, y
        return 0, 0

    def load(self):
        self.enabled.setChecked(self.data["enabled"])
        self.mode.setCurrentIndex(self.mode.findData(self.data["mode"]))
        self.name.setText(self.data["name"])
        self.address.setText(self.data["server_ip"])
        self.port.setValue(self.data["port"])
        self.delay.setValue(self.data["switch_delay"])
        self.scale.setValue(self.data["scroll_scale"])
        self.invert.setChecked(self.data["invert_scroll"])
        self.relative.setChecked(self.data["relative_mouse"])
        automatic = bool(self.data.get("easy_controller") or self.data.get("easy_peers"))
        self.mode.setEnabled(not automatic)
        self.name.setReadOnly(automatic)
        self.port.setEnabled(not self.data.get("easy_controller"))
        with QSignalBlocker(self.table):
            self.table.setRowCount(0)
            for screen in self.data["screens"]:
                self.add_screen(screen["name"], screen["x"], screen["y"])
        self.trust.setText(f"인증서 등록: 서버 {len(self.data['trusted_servers'])}대 / 클라이언트 {len(self.data['trusted_clients'])}대")
        self.refresh_preview()

    def refresh_preview(self):
        self.scene.clear()
        max_x, max_y = 4, 2
        for row in range(self.table.rowCount()):
            try:
                name = self.table.item(row, 0).text()
                x, y = int(self.table.item(row, 1).text()), int(self.table.item(row, 2).text())
                if not 0 <= x <= 8 or not 0 <= y <= 8:
                    continue
                max_x, max_y = max(max_x, x), max(max_y, y)
                self.scene.addItem(ComputerTile(self, row, name, x, y))
            except (AttributeError, ValueError):
                pass
        self.scene.setSceneRect(-10, -10, (max_x + 1) * 132, (max_y + 1) * 85)
        self.preview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def move_screen(self, row, x, y):
        with QSignalBlocker(self.table):
            occupied = set()
            for other in range(self.table.rowCount()):
                if other == row:
                    continue
                try:
                    occupied.add((int(self.table.item(other, 1).text()), int(self.table.item(other, 2).text())))
                except (AttributeError, ValueError):
                    pass
            if (x, y) not in occupied:
                self.table.item(row, 1).setText(str(x))
                self.table.item(row, 2).setText(str(y))
        QTimer.singleShot(0, self.refresh_preview)
        if self.data.get("easy_controller") or self.data.get("easy_peers"):
            QTimer.singleShot(0, self.save)

    def collect(self):
        value = {**self.data, "enabled": self.enabled.isChecked(), "engine": defaults()["engine"],
            "mode": self.mode.currentData(), "name": self.name.text().strip(), "server_ip": self.address.text().strip(),
            "port": self.port.value(), "switch_delay": self.delay.value(), "scroll_scale": self.scale.value(),
            "invert_scroll": self.invert.isChecked(), "relative_mouse": self.relative.isChecked()}
        value["screens"] = [{"name": self.table.item(row, 0).text().strip(), "x": int(self.table.item(row, 1).text()),
            "y": int(self.table.item(row, 2).text())} for row in range(self.table.rowCount())]
        previous = {screen["name"].casefold(): screen.get("options", {}) for screen in self.data["screens"]}
        for screen in value["screens"]:
            if previous.get(screen["name"].casefold()):
                screen["options"] = previous[screen["name"].casefold()]
        return value

    def copy_code(self):
        try:
            self.owner.clipboard.copy_private_text(connection_code(self.owner.config, self.collect()))
        except Exception:
            QMessageBox.warning(self, "마우스 연결 코드", "컴퓨터 이름과 인증서 설정을 확인하세요.")

    def add_code(self):
        text, ok = QInputDialog.getText(self, "마우스 연결 코드", "상대 컴퓨터에서 복사한 CBI1- 코드를 붙여넣으세요.")
        if not ok:
            return
        try:
            peer = parse_code(text.strip())
            self.data = self.collect()
            key = "trusted_clients" if self.mode.currentData() == "server" else "trusted_servers"
            self.data[key] = list(dict.fromkeys(self.data[key] + [peer["pin"]]))
            if key == "trusted_clients" and peer["name"] not in [item["name"] for item in self.data["screens"]]:
                position = self.next_position()
                self.data["screens"].append({"name": peer["name"], "x": position[0], "y": position[1]})
            self.load()
        except Exception:
            QMessageBox.warning(self, "연결 코드 확인", "올바른 상대 마우스 연결 코드를 입력하세요.")

    def save(self):
        try:
            settings = self.collect()
            from .input_setup import layout_settings
            layout_settings(settings, [{key: item[key] for key in ("name", "x", "y")} for item in settings["screens"]])
            screens = [{key: item[key] for key in ("name", "x", "y")} for item in settings["screens"]]
            self.watch(self.owner.input_setup.change_layout(screens, self.data.get("easy_revision", 0)))
        except Exception as error:
            self.status.setText(str(error) if isinstance(error, ValueError) else "화면 배치를 적용하지 못했습니다.")
            self.data = {**defaults(), **self.owner.config.input_settings}
            self.load()
