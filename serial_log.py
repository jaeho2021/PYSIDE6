import os
import sys
import serial
import threading
import time
import re
import queue
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QLineEdit, QVBoxLayout, QWidget, QTabWidget, QPushButton, QMenu, QDialog,
    QFormLayout, QComboBox, QDialogButtonBox, QLabel, QCompleter , QMessageBox, QHBoxLayout, QFileDialog, QInputDialog )
from PySide6.QtCore import Signal, QObject, Qt
from PySide6.QtGui import QAction, QShortcut, QKeySequence, QTextCursor, QTextCharFormat, QColor, QTextDocument


class SearchDialog(QDialog):
    next_signal = Signal()
    prev_signal = Signal()
    text_changed_signal = Signal(str)  # 텍스트 변경 시그널 추가

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find Text")
        self.setWindowModality(Qt.ApplicationModal)

        # 레이아웃 설정
        self.layout = QVBoxLayout()
        self.layout.setSpacing(5)

        # 라벨
        self.label = QLabel("Enter text to find:")
        self.layout.addWidget(self.label)

        # 검색 입력란
        self.search_input = QLineEdit()
        self.search_input.textChanged.connect(self.on_text_changed)  # 텍스트 변경 시 시그널 발생
        self.layout.addWidget(self.search_input)

        # Next and Previous buttons for searching
        self.next_button = QPushButton("Next")
        self.prev_button = QPushButton("Previous")
        self.next_button.clicked.connect(self.next_clicked)
        self.prev_button.clicked.connect(self.prev_clicked)

        # 버튼 레이아웃
        self.button_layout = QHBoxLayout()
        self.button_layout.addWidget(self.prev_button)
        self.button_layout.addWidget(self.next_button)
        self.layout.addLayout(self.button_layout)

        self.setLayout(self.layout)

        # 다이얼로그의 테두리 없애기
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)  # 테두리 없는 창
        self.setAttribute(Qt.WA_TranslucentBackground)  # 배경을 투명하게 설정 (선택 사항)

    def next_clicked(self):
        """Emits signal for the next search direction."""
        self.next_signal.emit()

    def prev_clicked(self):
        """Emits signal for the previous search direction."""
        self.prev_signal.emit()

    def on_text_changed(self, text):
        """Emits signal when text is changed to update search text in MainWindow."""
        self.text_changed_signal.emit(text)

    def get_search_text(self):
        return self.search_input.text()

class SerialRXThread(threading.Thread):
    def __init__(self, serial_connection, data_received_signal):
        super().__init__(daemon=True)
        self.serial = serial_connection
        self.data_received_signal = data_received_signal

    def run(self):
        while True:
            try:
                if self.serial and self.serial.is_open and self.serial.in_waiting > 0:
                    data = self.serial.readline().decode().strip()
                    # 시그널이 여전히 유효한지 확인한 후 emit
                    if self.data_received_signal and hasattr(self.data_received_signal, 'emit'):
                        self.data_received_signal.emit(data)
                time.sleep(0.01)
            except serial.SerialException as e:
                # 예외 처리 후 시그널이 유효한지 확인
                if self.data_received_signal and hasattr(self.data_received_signal, 'emit'):
                    self.data_received_signal.emit(f"Error reading data: {e}")
            except Exception as e:
                # 기타 오류 처리
                if self.data_received_signal and hasattr(self.data_received_signal, 'emit'):
                    self.data_received_signal.emit(f"Error reading data: {e}")
                time.sleep(0.1)  # 재시도 전 대기

class SerialTXThread(threading.Thread):
    def __init__(self, serial_connection, data_to_send_signal):
        super().__init__(daemon=True)
        self.serial = serial_connection
        self.data_to_send_signal = data_to_send_signal
        self.send_queue = queue.Queue()  # Create a queue for transmitting data

        # Connect the signal to the queue
        self.data_to_send_signal.connect(self.add_data_to_queue)

    def run(self):
        while True:
            try:
                data = self.send_queue.get()  # Get data from the queue
                if data:
                    self.serial.write(data.encode())
            except Exception as e:
                print(f"Error sending data: {e}")
            time.sleep(0.01)

    def add_data_to_queue(self, data):
        """Add data to the queue for sending."""
        self.send_queue.put(data)


class SerialThread(QObject):
    data_received = Signal(str)
    data_to_send_signal = Signal(str)

    def __init__(self, port, baudrate):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self.running = False
        self.rx_thread = None
        self.tx_thread = None

    def start(self):
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1)
            if not self.serial.is_open:
                self.serial.open()  # 시리얼 포트가 열려 있지 않으면 열기
            self.running = True
            self.rx_thread = SerialRXThread(self.serial, self.data_received)
            self.tx_thread = SerialTXThread(self.serial, self.data_to_send_signal)
            self.rx_thread.start()
            self.tx_thread.start()
        except serial.SerialException as e:
            self.data_received.emit(f"Error: {e}")

    def stop(self):
        self.running = False
        if self.serial and self.serial.is_open:
            self.serial.close()  # 시리얼 연결 종료

    def send_data(self, data):
        if self.serial and self.serial.is_open:
            try:
                self.serial.write((data + '\n').encode('utf-8'))  # Add newline character
                self.serial.flush()  # Ensure data is sent immediately
            except serial.SerialException as e:
                self.data_to_send_signal.emit(data)


class SerialSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Communication Settings")

        # Form layout for serial communication settings
        self.layout = QFormLayout()

        # Serial Port
        self.port_input = QLineEdit()
        self.layout.addRow("Serial Port (e.g., /dev/ttyUSB0):", self.port_input)

        # Baud Rate
        self.baudrate_input = QComboBox()
        self.baudrate_input.addItems(["115200", "9600", "57600", "19200", "38400"])
        self.layout.addRow("Baud Rate:", self.baudrate_input)

        # Dialog buttons (OK and Cancel)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        self.setLayout(self.layout)

    def get_settings(self):
        """Returns the serial port, baud rate, and output file name selected by the user."""
        port = self.port_input.text()
        baudrate = int(self.baudrate_input.currentText())
        return port, baudrate


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.max_log_lines = 10000

        self.output_file = "output_log.txt"

        self.last_cursor_position = None
        self.search_text = None

        self.search_text = ""  # Add search_text as an instance variable
        self.current_match_index = -1  # Track the current match index

        self.send_data_history = []
        # 데이터 파일 경로
        self.data_file = ".send_data_history.txt"
        # 데이터 로드
        self.load_send_data_history()

        self.setWindowTitle("Serial Logger V0.2")

        # Menu Bar Setup
        self.create_menu()

        # Tab Widget
        self.tab_widget = QTabWidget()

        # Tab 1: Serial Logger
        self.log_tab = QWidget()
        self.setup_log_tab()
        self.tab_widget.addTab(self.log_tab, "Logger")

        # Tab 2: Placeholder for additional functionality
        self.extra_tab = QWidget()
        self.setup_extra_tab()
        self.tab_widget.addTab(self.extra_tab, "Extra")

        # Set central widget
        self.setCentralWidget(self.tab_widget)

        # Initial Serial Thread (default settings)
        self.serial_thread = SerialThread(port="/dev/ttyV1", baudrate=115200)
        self.serial_thread.data_received.connect(self.update_log)
        self.serial_thread.start()

        # Store the original log text for restoring
        self.original_log = []

        # Ctrl + F 단축키 설정
        self.shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.shortcut.activated.connect(self.show_search_dialog)

        #self.update_window_title()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F1:  # F1 키 확인 (통신 연결)
            self.start_serial_connection()  # 통신 연결 시작
            self.update_window_title()
        elif event.key() == Qt.Key_F2:  # F2 키 확인 (통신 해지)
            self.stop_serial_connection()  # 통신 연결 해지
            self.setWindowTitle(f"Serial Logger - Disconnected")
        elif event.key() == Qt.Key_F5:  # F5 키 확인 (로그 클리어)
            self.log_output.clear()  # 로그 클리어
        else:
            super().keyPressEvent(event)  # 다른 키는 기본 동작 수행

    def start_serial_connection(self):
        """Start serial connection using the current serial settings."""
        if not self.serial_thread.running:
            self.serial_thread.start()
            self.update_log("Serial connection established.")
        else:
            self.update_log("Serial connection already active.")

    def stop_serial_connection(self):
        """Stop the serial connection."""
        if self.serial_thread.running:
            self.serial_thread.stop()
            self.update_log("Serial connection stopped.")
        else:
            self.update_log("No active serial connection to stop.")

    def load_send_data_history(self):
        """파일에서 send_data_history를 로드합니다."""
        if os.path.exists(self.data_file):
            with open(self.data_file, "r", encoding="utf-8") as file:
                self.send_data_history = [line.strip() for line in file.readlines()]
        else:
            self.send_data_history = []

    def save_send_data_history(self):
        """send_data_history를 파일에 저장합니다."""
        with open(self.data_file, "w", encoding="utf-8") as file:
            for data in self.send_data_history:
                file.write(f"{data}\n")

    def update_window_title(self):
        """Updates the window title with the current serial port and baud rate."""
        serial_port = self.serial_thread.port
        baud_rate = self.serial_thread.baudrate
        self.setWindowTitle(f"Serial Logger - {serial_port} @ {baud_rate} baud")

    def create_menu(self):
        """Create the menu bar with a 'Settings' menu."""
        menubar = self.menuBar()
        # Create the 'Settings' menu
        file_menu = menubar.addMenu('File')
        # Save Log Action
        save_log_action = QAction('Save Log', self)
        save_log_action.triggered.connect(self.save_log_to_file)
        file_menu.addAction(save_log_action)

        set_max_lines_action = QAction("Set Max Log Lines", self)
        set_max_lines_action.triggered.connect(self.set_max_log_lines)
        file_menu.addAction(set_max_lines_action)

        configure_menu = menubar.addMenu('Configuration')
        # Create an action for 'Settings'
        settings_action = QAction('Port', self)
        settings_action.triggered.connect(self.show_settings)
        # Add the 'Settings' action to the menu
        configure_menu.addAction(settings_action)

    def show_search_dialog(self):
        self.dialog = SearchDialog(self)
        self.dialog.next_signal.connect(self.find_next)
        self.dialog.prev_signal.connect(self.find_previous)
        self.dialog.text_changed_signal.connect(self.update_search_text)
        self.dialog.exec()

    def update_search_text(self, text):
        """Search text를 자동으로 업데이트."""
        self.search_text = text
        self.current_match_index = -1  # 새로운 검색을 시작할 때마다 인덱스 리셋
        #self.find_next()  # 텍스트가 변경될 때마다 자동으로 next 검색

    def find_next(self):
        search_text = self.dialog.search_input.text().strip()
        if not self.search_text:
            return

        cursor = self.log_output.textCursor()
        document = self.log_output.document()

        # 현재 커서 위치에서 검색 시작
        start_pos = cursor.position()
        cursor = document.find(search_text, start_pos)

        if cursor.isNull():
            # 처음부터 다시 검색
            cursor = document.find(search_text, 0)

        if not cursor.isNull():
            self.log_output.setTextCursor(cursor)
            self.log_output.ensureCursorVisible()
        else:
            QMessageBox.information(self, "Search", "No matches found.")

    def find_previous(self):
        search_text = self.dialog.search_input.text()

        # 처음 검색이거나 검색 텍스트가 변경된 경우
        if search_text != self.search_text:
            self.search_text = search_text
        self.last_cursor_position = len(self.log_output.toPlainText())  # 새 검색은 텍스트의 끝에서 시작

        print(self.last_cursor_position)
        if search_text:
            cursor = self.log_output.textCursor()
            cursor.setPosition(self.last_cursor_position)  # 마지막 검색 위치에서 시작

            # 역방향으로 텍스트 찾기
            found = self.log_output.find(search_text, QTextDocument.FindBackward)

            if found:
                self.last_cursor_position = cursor.position()  # 찾은 위치 저장
                print(f"Found '{search_text}' at position {self.last_cursor_position}")
            else:
                # 더 이상 찾을 수 없으면 텍스트 끝에서 다시 시작
                print("No more occurrences found. Searching from the end again.")
                # 텍스트 끝에서 검색을 시작하도록 커서 위치를 초기화
                self.last_cursor_position = len(self.log_output.toPlainText())  # 텍스트 끝에서 다시 시작
                cursor.setPosition(self.last_cursor_position)
                self.log_output.setTextCursor(cursor)
                self.find_previous()

    def show_settings(self):
        """Show the serial settings dialog when the user clicks 'Settings'."""
        settings_dialog = SerialSettingsDialog(self)
        # If the dialog is accepted, update serial settings
        if settings_dialog.exec() == QDialog.Accepted:
            port, baudrate = settings_dialog.get_settings()
            self.update_serial_settings(port, baudrate)

    def update_serial_settings(self, port, baudrate):
        """Update the serial connection settings and restart the serial thread."""
        self.serial_thread.stop()  # Stop the old thread
        self.serial_thread = SerialThread(port, baudrate)
        self.serial_thread.data_received.connect(self.update_log)
        self.serial_thread.start()  # Restart the serial thread with new settings
        self.update_log(f"Serial settings updated: Port = {port}, Baudrate = {baudrate}")

    def setup_log_tab(self):
        # Create the keyword filter input field
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("Enter keyword to filter...")

        # Create the QTextEdit for log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: black; color: gray;")

        # Create the QLineEdit for data input
        completer = QCompleter(self.send_data_history)
        completer.setCaseSensitivity(Qt.CaseInsensitive)

        self.data_input = QLineEdit()
        self.data_input.setPlaceholderText("Enter data to send...")
        self.data_input.setCompleter(completer)
        self.data_input.returnPressed.connect(self.send_data)

        # Connect the keyword input to filter updates
        self.keyword_input.textChanged.connect(self.filter_log)

        # Layout setup
        layout = QVBoxLayout()
        layout.addWidget(self.keyword_input)
        layout.addWidget(self.log_output)
        layout.addWidget(self.data_input)

        self.log_tab.setLayout(layout)

    def setup_extra_tab(self):
        layout = QVBoxLayout()
        placeholder = QTextEdit()
        placeholder.setReadOnly(True)
        placeholder.setText("This tab can be used for additional functionality.")
        layout.addWidget(placeholder)
        self.extra_tab.setLayout(layout)

    def send_data(self):
        data = self.data_input.text()
        if data:
            self.serial_thread.send_data(data)
            self.update_log(f"Sent: {data}")
            self.data_input.clear()

            # Add the data to the send_data_history
            if data not in self.send_data_history:
                self.send_data_history.append(data)
                # Update the completer's model to include the new data
                completer = self.data_input.completer()
                completer.model().setStringList(self.send_data_history)

            # Save the updated send_data_history to the file
            self.save_send_data_history()

    def update_log(self, message):
        """Appends message to the log output area."""
        self.original_log.append({'text': message})  # Just store the text without the 'marked' key
        self.log_output.append(message)  # Display the log in QTextEdit

    def filter_log(self):
        """Filters the log output based on the regular expression entered in QLineEdit."""
        keyword = self.keyword_input.text()  # Get the keyword entered by the user
        self.log_output.clear()  # Clear the existing output

        if keyword:  # If a keyword is entered, apply regex filter
            try:
                # Compile the regex pattern (with case insensitivity by default)
                pattern = re.compile(keyword, re.IGNORECASE)
                # Filter the logs based on the compiled regex
                filtered_text = [
                    line for line in self.original_log if pattern.search(line['text'])
                ]
                # Display each filtered line
                for line in filtered_text:
                    self.display_line(line)

            except re.error:  # Catch invalid regex patterns
                self.log_output.append("Invalid regex pattern.")
        else:  # No keyword entered, display all logs
            for line in self.original_log:
                self.display_line(line)


    def display_line(self, line):
        """Display a single line."""
        text = line['text']
        self.log_output.append(text)  # Display each line in QTextEdit

    def save_log_to_file(self):
        """log_output의 내용을 사용자가 선택한 파일에 저장"""
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog  # 플랫폼 기본 대화 상자를 사용하지 않음 (선택 사항)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Log File",  # 대화 상자 제목
            "",  # 기본 경로 (빈 문자열이면 현재 경로)
            "Text Files (*.txt);;All Files (*)",  # 파일 필터
            options=options
        )

        # 사용자가 파일 저장 취소 시 처리
        if not file_path:
            return  # 아무 동작도 하지 않음

        try:
            # log_output의 내용을 선택한 파일에 저장
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(self.log_output.toPlainText())
            QMessageBox.information(self, "Success", f"Log saved to {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save log: {e}")

    def set_max_log_lines(self):
        max_lines, ok = QInputDialog.getInt(
            self,
            "Set Max Log Lines",
            "Enter maximum log lines:",
            value=self.max_log_lines,
            minValue=1,
            maxValue=1000000,
            step=1,
        )
        if ok:
            self.max_log_lines = max_lines
            print(f"Max log lines set to: {self.max_log_lines}")

    # 로그 추가 메서드 (최대 라인 제한 적용)
    def append_log(self, text):
        current_logs = self.log_output.toPlainText().split("\n")
        current_logs.append(text)

        # 최대 라인 제한에 맞게 리스트를 자릅니다.
        if len(current_logs) > self.max_log_lines:
            current_logs = current_logs[-self.max_log_lines :]

        # 텍스트 업데이트
        self.log_output.setPlainText("\n".join(current_logs))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(900, 1300)
    window.show()
    sys.exit(app.exec())
