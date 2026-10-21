"""Korean Deskflow setup in its own scrollable dialog."""
from pathlib import Path

from PySide6.QtCore import Qt, QSignalBlocker, QTimer
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .input_engine import connection_code, default_profile, defaults, import_profile, parse_code, validate


class ComputerTile(QGraphicsRectItem):
    def __init__(self, owner, row, name, x, y):
        super().__init__(0, 0, 112, 65)
        self.owner, self.row = owner, row
        self.setBrush(QBrush(QColor("#eaf3ff")))
        self.setPen(QPen(QColor("#1769c2"), 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        label = QGraphicsSimpleTextItem(name[:16], self)
        label.setPos(8, 23)
        self.setPos(x * 132, y * 85)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        x, y = max(0, min(8, round(self.x() / 132))), max(0, min(8, round(self.y() / 85)))
        self.owner.move_screen(self.row, x, y)


class InputDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("ClipBridge · 마우스·키보드 / 화면 배치")
        self.resize(660, 660)
        self.data = {**defaults(), **owner.config.input_settings}
        if not owner.config.input_settings and default_profile().is_file():
            try:
                self.data = import_profile(default_profile())
            except (ValueError, OSError):
                pass
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        note = QLabel("마우스를 화면 가장자리로 옮겨 다른 컴퓨터로 넘어갑니다.\nClipBridge에 마우스·키보드 엔진이 들어 있어 별도 설치가 필요 없습니다.\n기존 Deskflow를 사용 중이면 정지한 뒤 켜세요. 없는 컴퓨터는 바로 설정하면 됩니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.enabled = QCheckBox("ClipBridge에서 마우스·키보드도 공유")
        self.mode = QComboBox()
        self.mode.addItem("이 컴퓨터의 마우스·키보드 사용 (서버)", "server")
        self.mode.addItem("다른 컴퓨터의 마우스·키보드 받기 (클라이언트)", "client")
        self.name, self.address = QLineEdit(), QLineEdit()
        self.address.setPlaceholderText("마우스가 연결된 컴퓨터의 LAN / Tailscale IP")
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
        form.addRow("마우스·키보드 엔진", QLabel("내장 · 별도 설치 필요 없음"))
        form.addRow("이 컴퓨터 역할", self.mode)
        form.addRow("이 컴퓨터 이름", self.name)
        form.addRow("마우스 서버 IP", self.address)
        form.addRow("마우스 포트", self.port)
        form.addRow("화면 전환 지연", self.delay)
        form.addRow("스크롤 배율", self.scale)
        form.addRow(self.invert)
        form.addRow(self.relative)
        layout.addLayout(form)
        imported = QPushButton("기존 Deskflow 설정·화면 배치 가져오기")
        imported.clicked.connect(self.import_existing)
        layout.addWidget(imported)
        layout.addWidget(QLabel("화면 카드를 드래그하여 배치하세요. 맞닿은 화면으로 마우스가 넘어갑니다. (서버 설정)"))
        self.scene = QGraphicsScene(self)
        self.preview = QGraphicsView(self.scene)
        self.preview.setMinimumHeight(215)
        layout.addWidget(self.preview)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["컴퓨터 이름", "X (가로)", "Y (세로)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(160)
        self.table.cellChanged.connect(lambda row, column: self.refresh_preview())
        layout.addWidget(self.table)
        rows = QHBoxLayout()
        add, remove = QPushButton("화면 추가"), QPushButton("선택 화면 제거")
        add.clicked.connect(lambda: self.add_screen("Computer", *self.next_position()))
        remove.clicked.connect(self.remove_screen)
        rows.addWidget(add)
        rows.addWidget(remove)
        layout.addLayout(rows)
        codes = QHBoxLayout()
        copy, paste = QPushButton("이 컴퓨터 마우스 연결 코드 복사"), QPushButton("상대 마우스 연결 코드 추가")
        copy.clicked.connect(self.copy_code)
        paste.clicked.connect(self.add_code)
        codes.addWidget(copy)
        codes.addWidget(paste)
        layout.addLayout(codes)
        self.trust = QLabel()
        layout.addWidget(self.trust)
        layout.addWidget(QLabel("Scroll Lock: 화면 이동 잠금/해제. macOS/Wayland는 OS의 입력 권한 승인이 필요할 수 있습니다."))
        scroll.setWidget(widget)
        outer.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장 및 적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.load()

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

    def import_existing(self):
        path = default_profile()
        if not path.is_file():
            selected, _ = QFileDialog.getOpenFileName(self, "Deskflow.conf 선택", str(path.parent), "Deskflow 설정 (*.conf);;모든 파일 (*)")
            if not selected:
                return
            path = Path(selected)
        try:
            self.data = import_profile(path)
            self.load()
        except Exception as error:
            QMessageBox.warning(self, "설정 가져오기", str(error) if isinstance(error, ValueError) else "Deskflow 설정 파일을 읽지 못했습니다.")

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
            validate(settings)
            self.owner.input_manager.stop()
            self.owner.config.input_settings = settings
            self.owner.store.save(self.owner.config)
            self.owner.input_manager.start()
            if not settings["enabled"]:
                self.owner.input_status.setText("마우스·키보드 공유: 꺼짐")
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, "마우스 설정", str(error) if isinstance(error, ValueError) else "마우스 설정을 저장하지 못했습니다.")
