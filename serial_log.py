import os
import sys
import serial
import threading
import time
import re
import queue
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QLineEdit, QVBoxLayout, QWidget, QTabWidget, QPushButton, QMenu, QDialog,
    QFormLayout, QComboBox, QDialogButtonBox, QLabel, QCompleter )
from PySide6.QtCore import Signal, QObject, Qt
from PySide6.QtGui import QAction, QShortcut, QKeySequence, QTextCursor, QTextCharFormat, QColor


class SearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find Text")
        self.setWindowModality(Qt.ApplicationModal)
        self.setFixedSize(300, 100)

        self.layout = QVBoxLayout()
        self.label = QLabel("Enter text to find:")
        self.layout.addWidget(self.label)

        self.search_input = QLineEdit()
        self.layout.addWidget(self.search_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

        self.setLayout(self.layout)

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
        """Returns the serial port and baud rate selected by the user."""
        port = self.port_input.text()
        baudrate = int(self.baudrate_input.currentText())
        window.setWindowTitle(f"Serial Logger - {port} @ {baudrate} baud")
        return port, baudrate


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.send_data_history = []
        # 데이터 파일 경로
        self.data_file = ".send_data_history.txt"
        # 데이터 로드
        self.load_send_data_history()

        self.setWindowTitle("Serial Logger with Keyword Filter")

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
        settings_menu = menubar.addMenu('Settings')
        # Create an action for 'Settings'
        settings_action = QAction('Settings', self)
        settings_action.triggered.connect(self.show_settings)
        # Add the 'Settings' action to the menu
        settings_menu.addAction(settings_action)

    def show_search_dialog(self):
        dialog = SearchDialog(self)
        if dialog.exec() == QDialog.Accepted:
            search_text = dialog.get_search_text()
            if search_text:
                self.find_and_highlight_text(search_text)

    def find_and_highlight_text(self, search_text):
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.log_output.setTextCursor(cursor)

        # 기존 하이라이트 제거
        extra_selections = []
        self.log_output.setExtraSelections(extra_selections)

        if not search_text:
            return

        # 새로운 하이라이트 적용
        color = QColor(Qt.yellow)
        while self.log_output.find(search_text):
            selection = QTextEdit.ExtraSelection()
            selection.cursor = self.log_output.textCursor()
            selection.format.setBackground(color)
            extra_selections.append(selection)

        self.log_output.setExtraSelections(extra_selections)

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(900, 1300)
    window.show()
    sys.exit(app.exec())
