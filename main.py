import sys
import os
import socket
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QWidget, QFileDialog,
    QMessageBox, QAction, QSystemTrayIcon, QMenu, QLineEdit
)
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QLinearGradient, QPainter
from PyQt5.QtCore import Qt
import configparser
import appdirs
from pathlib import Path
import atexit

class GradientWidget(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(30, 30, 30))
        gradient.setColorAt(1.0, QColor(50, 50, 50))
        painter.fillRect(event.rect(), gradient)

class SingleInstanceChecker:
    def __init__(self, port=54321):
        self.port = port
        self.socket = None
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.bind(("127.0.0.1", self.port))
        except socket.error:
            self.is_already_running = True
        else:
            self.is_already_running = False

    def cleanup(self):
        if self.socket:
            self.socket.close()

def get_unique_filename(save_path):
    base, ext = os.path.splitext(save_path)
    counter = 1
    while os.path.exists(save_path):
        save_path = f"{base}({counter}){ext}"
        counter += 1
    return save_path

class P2PNode:
    def __init__(self, host, port, save_directory=None):
        self.host = host
        self.port = port
        self.server_socket = None
        self.save_directory = save_directory or os.getcwd()

    def start_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        threading.Thread(target=self.accept_connections, daemon=True).start()

    def accept_connections(self):
        while True:
            try:
                client, address = self.server_socket.accept()
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
                client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536 * 4)
                threading.Thread(target=self.handle_client, args=(client,), daemon=True).start()
            except Exception as e:
                break

    def handle_client(self, client_socket):
        try:
            while True:
                header = b""
                while b"\n" not in header:
                    part = client_socket.recv(1)
                    if not part:
                        return
                    header += part
                header = header.decode('utf-8').strip()
                if not header:
                    break
                file_name, file_size = header.split('|')
                file_size = int(file_size)
                
                # Генерация уникального имени файла
                initial_save_path = os.path.join(self.save_directory, file_name)
                save_path = get_unique_filename(initial_save_path)
                
                with open(save_path, 'wb') as f:
                    remaining = file_size
                    while remaining > 0:
                        data = client_socket.recv(min(65536 * 4, remaining))
                        if not data:
                            break
                        f.write(data)
                        remaining -= len(data)        
        finally:
            client_socket.close()

    def send_file(self, file_name, peer_host, peer_port):
        if not os.path.isfile(file_name):
            return
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            client_socket.connect((peer_host, peer_port))
            client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
            client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536 * 4)
            file_size = os.path.getsize(file_name)
            header = f"{os.path.basename(file_name)}|{file_size}\n"
            client_socket.sendall(header.encode('utf-8', errors='ignore'))
            with open(file_name, 'rb') as f:
                while chunk := f.read(65536 * 4):
                    client_socket.sendall(chunk)
        finally:
            client_socket.close()

    def set_save_directory(self, path):
        if os.path.isdir(path):
            self.save_directory = path

class P2PGUI(QMainWindow):
    def __init__(self, node):
        super().__init__()
        self.node = node
        self.config = configparser.ConfigParser()
        
        config_dir = appdirs.user_data_dir('P2PFileSharing', 'MemeBlox')
        os.makedirs(config_dir, exist_ok=True)
        self.config_file = os.path.join(config_dir, 'config.ini')
        
        self.load_config()
        self.init_ui()

    def load_config(self):
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
            self.ip = self.config.get("Settings", "ip", fallback="127.0.0.1")
            self.port = self.config.getint("Settings", "port", fallback=12345)
            self.save_directory = self.config.get("Settings", "save_directory", fallback=os.getcwd())
        else:
            self.ip = "127.0.0.1"
            self.port = 12345
            self.save_directory = os.getcwd()
        
        self.node.set_save_directory(self.save_directory)

    def save_config(self):
        self.config["Settings"] = {
            "ip": self.ip_input.text().strip(),
            "port": self.port_input.text().strip(),
            "save_directory": self.dir_label.text().split(": ")[1]
        }
        with open(self.config_file, "w") as configfile:
            self.config.write(configfile)

    def init_ui(self):
        if getattr(sys, 'frozen', False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path('.')
        
        tray_icon_path = str(base_path / 'tray_icon.ico')
        screen_geometry = QApplication.desktop().screenGeometry()

        screen_width = screen_geometry.width()
        screen_height = screen_geometry.height()

        label_font_size = int(screen_height * 0.02)  
        push_button_font_size = int(screen_height * 0.012)  
        dir_label_font_size = int(screen_height * 0.01)  
        drop_label_font_size = int(screen_height * 0.0125)  
        dnd_obvod = int(screen_height * 0.002)
        window_width = int(screen_width * 0.32)
        window_height = int(screen_height * 0.42)
        ip_port_font_size = int(screen_height * 0.01)  
        drop_label_height = int(screen_height * 0.1042)

        self.setWindowTitle("P2P File Sharing")
        # self.setGeometry(100, 100, 800, 600)
        self.setGeometry(100, 100, window_width, window_height)

        self.setMinimumSize(600, 400)

        x = (screen_width - self.width()) // 2
        y = (screen_height - self.height()) // 2
        self.move(x, y)

        central_widget = GradientWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        
        mb_title = screen_height * 0.0208
        title = QLabel("P2P File Sharing")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            QLabel {{
                color: #4A90E2;
                font-size: {label_font_size}px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 2px;
                margin-bottom: {mb_title}px;
            }}
        """)
        layout.addWidget(title)
        pd_dir = screen_height * 0.0104
        self.select_dir_button = QPushButton("Выбрать директорию")
        self.select_dir_button.setStyleSheet(f"""
            QPushButton {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4A90E2, stop:1 #6A1B9A);
                color: white;
                border-radius: 15px;
                padding: {pd_dir}px;
                font-size: {push_button_font_size}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6A1B9A, stop:1 #4A90E2);
            }}
            QPushButton:pressed {{
                background-color: #303F9F;
            }}
        """)
        self.select_dir_button.clicked.connect(self.select_directory)
        layout.addWidget(self.select_dir_button)
        pd_dir_l = screen_height * 0.0079
        self.dir_label = QLabel(f"Сохранять файлы в: {self.save_directory}")
        self.dir_label.setStyleSheet(f"""
            QLabel {{
                color: #BDBDBD;
                font-size: {dir_label_font_size}px;
                padding: {pd_dir_l}px;
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 10px;
            }}
        """)
        layout.addWidget(self.dir_label)
        m_label = screen_height * 0.0138

        self.drop_label = QLabel("Перетащите файлы сюда")
        self.drop_label.setAlignment(Qt.AlignCenter)
        self.drop_label.setStyleSheet(f"""
            QLabel {{
                border: {dnd_obvod}px dashed #4A90E2;
                border-radius: 20px;
                color: #BDBDBD;
                font-size: {drop_label_font_size}px;
                background-color: rgba(255, 255, 255, 0.05);
                margin: {m_label}px 0;
            }}
            QLabel:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                border-color: #6A1B9A;
            }}
        """)
        self.drop_label.setFixedHeight(drop_label_height)
        layout.addWidget(self.drop_label)
        pd_drop = screen_height * 0.0085

        input_style = f"""
            QLineEdit {{
                background-color: rgba(255, 255, 255, 0.1);
                border: {dnd_obvod}px solid #4A90E2;
                border-radius: 10px;
                color: #E0E0E0;
                padding: {pd_drop}px;
                font-size: {ip_port_font_size}px;
            }}
            QLineEdit:hover {{
                border-color: #6A1B9A;
                background-color: rgba(255, 255, 255, 0.15);
            }}
           
        """

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("IP-адрес (например: 192.168.1.100)")
        self.ip_input.setText(self.ip)
        self.ip_input.setStyleSheet(input_style)
        layout.addWidget(self.ip_input)

        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("Порт (например: 12345)")
        self.port_input.setText(str(self.port))
        self.port_input.setStyleSheet(input_style)
        layout.addWidget(self.port_input)

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(tray_icon_path))
        self.tray_icon.setVisible(True)

        tray_menu = QMenu()
        restore_action = QAction("Открыть", self)
        restore_action.triggered.connect(self.restore_window)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(restore_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)

        self.setWindowFlags(Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

        self.drop_label.setAcceptDrops(True)
        self.drop_label.dragEnterEvent = self.drag_enter_event
        self.drop_label.dropEvent = self.drop_event

    def drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def drop_event(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls()]
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip()

        if not ip or not port:
            QMessageBox.warning(self, "Ошибка", "Пожалуйста, укажите IP-адрес и порт.")
            return

        try:
            port = int(port)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Порт должен быть числом.")
            return 

        for file in files:
            threading.Thread(
                target=self.node.send_file,
                args=(file, ip, port),
                daemon=True
            ).start()

    def select_directory(self):
        new_dir = QFileDialog.getExistingDirectory(self, "Выберите директорию")
        if new_dir:
            self.node.set_save_directory(new_dir)
            self.dir_label.setText(f"Сохранять файлы в: {new_dir}")

    def restore_window(self):
        self.showNormal()

    def quit_app(self):
        self.save_config()
        self.tray_icon.hide()
        QApplication.quit()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.restore_window()

    def closeEvent(self, event):
        self.save_config()
        self.hide()
        self.tray_icon.showMessage("P2P File Sharing", "Приложение свернуто в трей.", QSystemTrayIcon.Information, 3000)
        event.ignore()

if __name__ == "__main__":
    HOST = "0.0.0.0"
    PORT = 12345

    app = QApplication(sys.argv)
    
    single_instance_checker = SingleInstanceChecker()

    if single_instance_checker.is_already_running:
        QMessageBox.critical(None, "Ошибка", "Приложение уже запущено!")
        sys.exit(1)

    atexit.register(single_instance_checker.cleanup)

    config_dir = appdirs.user_data_dir('P2PFileSharing', 'YourCompany')
    os.makedirs(config_dir, exist_ok=True)
    config_file = os.path.join(config_dir, 'config.ini')
    
    config = configparser.ConfigParser()
    if os.path.exists(config_file):
        config.read(config_file)
        default_save_directory = config.get("Settings", "save_directory", fallback=os.getcwd())
    else:
        default_save_directory = os.getcwd()

    node = P2PNode(HOST, PORT, save_directory=default_save_directory)
    node.start_server()
    gui = P2PGUI(node) 
    gui.show()
    sys.exit(app.exec_())