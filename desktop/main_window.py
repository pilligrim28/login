import sys
import os
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QCheckBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QComboBox, QGroupBox, QFormLayout,
    QProgressBar, QMessageBox, QHeaderView, QFileDialog
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor, QTextCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import Config
from core.logger import log
from core.database import Database
from core.sms import SMSActivate
from workers.worker import Worker


class WorkerThread(QThread):
    """Поток для запуска воркера."""
    progress = Signal(int, int, int, int)  # done, total, success, failed
    log_message = Signal(str)
    finished_signal = Signal()

    def __init__(self, worker: Worker):
        super().__init__()
        self.worker = worker
        self.worker.on_progress = lambda d, t, s, f: self.progress.emit(d, t, s, f)
        self.worker.on_log = lambda msg: self.log_message.emit(msg)
        self.worker.on_finished = lambda: self.finished_signal.emit()

    def run(self):
        self.worker.run()


class MainWindow(QMainWindow):
    """Главное окно десктопной версии."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MassReg Desktop — Массовая регистрация")
        self.setGeometry(100, 100, 1000, 750)

        self.config = self._load_config()
        self.db = Database(self.config)
        self.worker_thread = None
        self.worker = None

        self._init_ui()
        self._load_config_to_ui()
        self._refresh_accounts()
        self._refresh_stats()

        # Таймер обновления статистики
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._refresh_stats)
        self.stats_timer.start(3000)  # каждые 3 сек

    def _load_config(self) -> Config:
        try:
            return Config("config.yaml")
        except FileNotFoundError:
            # Создаём дефолтный
            default = {
                "sms": {"api_key": "", "service_code": "op", "country": 0, "max_sms_wait": 300},
                "proxy": {"enabled": False, "type": "http", "proxies": [], "rotation_url": ""},
                "worker": {"threads": 5, "total_registrations": 50, "headless": True, "retry_count": 3},
                "database": {"type": "sqlite", "sqlite_path": "accounts.db", "postgres_url": ""}
            }
            import yaml
            with open("config.yaml", "w", encoding="utf-8") as f:
                yaml.dump(default, f, default_flow_style=False, allow_unicode=True)
            return Config("config.yaml")

    def _init_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # Вкладки
        self.dashboard_tab = QWidget()
        self.accounts_tab = QWidget()
        self.settings_tab = QWidget()
        self.logs_tab = QWidget()

        self._init_dashboard()
        self._init_accounts_tab()
        self._init_settings_tab()
        self._init_logs_tab()

        self.tabs.addTab(self.dashboard_tab, "🚀 Дашборд")
        self.tabs.addTab(self.accounts_tab, "📦 Аккаунты")
        self.tabs.addTab(self.settings_tab, "⚙️ Настройки")
        self.tabs.addTab(self.logs_tab, "📋 Логи")

    def _init_dashboard(self):
        layout = QVBoxLayout()

        # Заголовок
        title = QLabel("MassReg — Панель управления")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Статистика
        stats_group = QGroupBox("Статистика")
        stats_layout = QHBoxLayout()

        self.stat_total = QLabel("Всего: 0")
        self.stat_success = QLabel("Успешно: 0")
        self.stat_failed = QLabel("Неудачно: 0")
        self.stat_success_rate = QLabel("Процент: 0%")

        for lbl in [self.stat_total, self.stat_success, self.stat_failed, self.stat_success_rate]:
            lbl.setFont(QFont("Arial", 14))
            stats_layout.addWidget(lbl)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Настройки запуска
        run_group = QGroupBox("Параметры запуска")
        run_layout = QFormLayout()

        self.total_spin = QSpinBox()
        self.total_spin.setRange(1, 100000)
        self.total_spin.setValue(self.config.get("worker.total_registrations", 50))
        run_layout.addRow("Количество:", self.total_spin)

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 50)
        self.threads_spin.setValue(self.config.get("worker.threads", 5))
        run_layout.addRow("Потоков:", self.threads_spin)

        self.headless_check = QCheckBox("Headless (без окна браузера)")
        self.headless_check.setChecked(self.config.get("worker.headless", True))
        run_layout.addRow("", self.headless_check)

        run_group.setLayout(run_layout)
        layout.addWidget(run_group)

        # Кнопки
        btn_layout = QHBoxLayout()

        self.start_btn = QPushButton("🚀 Запустить")
        self.start_btn.setMinimumHeight(45)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                font-size: 15px; font-weight: bold; border-radius: 8px;
                padding: 10px 30px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.start_btn.clicked.connect(self._start_worker)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹ Остановить")
        self.stop_btn.setMinimumHeight(45)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                font-size: 15px; font-weight: bold; border-radius: 8px;
                padding: 10px 30px;
            }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self.stop_btn.clicked.connect(self._stop_worker)
        btn_layout.addWidget(self.stop_btn)

        layout.addLayout(btn_layout)

        # Прогресс
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
        layout.addWidget(self.progress_bar)

        layout.addStretch()
        self.dashboard_tab.setLayout(layout)

    def _init_accounts_tab(self):
        layout = QVBoxLayout()

        # Таблица
        self.accounts_table = QTableWidget()
        self.accounts_table.setColumnCount(6)
        self.accounts_table.setHorizontalHeaderLabels([
            "ID", "Email", "Пароль", "Телефон", "Статус", "Дата"
        ])
        header = self.accounts_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.accounts_table.setAlternatingRowColors(True)
        layout.addWidget(self.accounts_table)

        # Кнопки
        btn_layout = QHBoxLayout()

        refresh_btn = QPushButton("🔄 Обновить")
        refresh_btn.clicked.connect(self._refresh_accounts)
        btn_layout.addWidget(refresh_btn)

        export_btn = QPushButton("📤 Экспорт CSV")
        export_btn.clicked.connect(self._export_csv)
        btn_layout.addWidget(export_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.accounts_tab.setLayout(layout)

    def _init_settings_tab(self):
        layout = QVBoxLayout()

        # SMS
        sms_group = QGroupBox("SMS-сервис (SMS-Activate)")
        sms_layout = QFormLayout()

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("API-ключ")
        sms_layout.addRow("API-ключ:", self.api_key_input)

        self.service_combo = QComboBox()
        self.service_combo.addItems(["Microsoft (op)", "Snapchat (sc)", "Apple (ap)"])
        sms_layout.addRow("Сервис:", self.service_combo)

        balance_btn = QPushButton("💳 Проверить баланс")
        balance_btn.clicked.connect(self._check_balance)
        sms_layout.addRow("", balance_btn)

        self.balance_label = QLabel("Баланс: —")
        sms_layout.addRow("", self.balance_label)

        sms_group.setLayout(sms_layout)
        layout.addWidget(sms_group)

        # Прокси
        proxy_group = QGroupBox("Прокси")
        proxy_layout = QVBoxLayout()

        self.proxy_enabled = QCheckBox("Использовать прокси")
        proxy_layout.addWidget(self.proxy_enabled)

        proxy_form = QFormLayout()
        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["http", "socks5"])
        proxy_form.addRow("Тип:", self.proxy_type_combo)

        self.proxy_list_input = QTextEdit()
        self.proxy_list_input.setPlaceholderText(
            "Прокси (по одному на строку):\nhost:port:username:password\n"
            "или один rotation URL"
        )
        self.proxy_list_input.setMaximumHeight(120)
        proxy_form.addRow("Список:", self.proxy_list_input)

        proxy_layout.addLayout(proxy_form)
        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)

        # Кнопка сохранения
        save_btn = QPushButton("💾 Сохранить настройки")
        save_btn.setMinimumHeight(40)
        save_btn.clicked.connect(self._save_settings)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.settings_tab.setLayout(layout)

    def _init_logs_tab(self):
        layout = QVBoxLayout()

        self.logs_text = QTextEdit()
        self.logs_text.setReadOnly(True)
        self.logs_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.logs_text)

        clear_btn = QPushButton("🗑️ Очистить")
        clear_btn.clicked.connect(self.logs_text.clear)
        layout.addWidget(clear_btn)

        self.logs_tab.setLayout(layout)

    def _load_config_to_ui(self):
        """Загрузить конфиг в UI."""
        self.api_key_input.setText(self.config.get("sms.api_key", ""))

        proxies = self.config.get("proxy.proxies", [])
        rotation_url = self.config.get("proxy.rotation_url", "")
        proxy_lines = list(proxies)
        if rotation_url:
            proxy_lines.append(rotation_url)
        self.proxy_list_input.setPlainText("\n".join(proxy_lines))

        self.proxy_enabled.setChecked(
            self.config.get("proxy.enabled", False) or bool(proxy_lines)
        )

        self.total_spin.setValue(self.config.get("worker.total_registrations", 50))
        self.threads_spin.setValue(self.config.get("worker.threads", 5))
        self.headless_check.setChecked(self.config.get("worker.headless", True))

    def _save_settings(self):
        """Сохранить настройки."""
        api_key = self.api_key_input.text().strip()
        self.config.set("sms.api_key", api_key)

        # Прокси
        proxy_lines = self.proxy_list_input.toPlainText().strip().split("\n")
        proxy_lines = [p.strip() for p in proxy_lines if p.strip()]

        rotation_url = ""
        proxies = []
        for line in proxy_lines:
            if line.startswith("http://") or line.startswith("socks5://"):
                rotation_url = line
            else:
                proxies.append(line)

        self.config.set("proxy.proxies", proxies)
        self.config.set("proxy.rotation_url", rotation_url)
        self.config.set("proxy.enabled", self.proxy_enabled.isChecked())
        self.config.set("proxy.type", self.proxy_type_combo.currentText())

        # Воркер
        self.config.set("worker.total_registrations", self.total_spin.value())
        self.config.set("worker.threads", self.threads_spin.value())
        self.config.set("worker.headless", self.headless_check.isChecked())

        self.config.save()
        QMessageBox.information(self, "Успех", "Настройки сохранены!")
        log.info("Настройки сохранены")

    def _check_balance(self):
        """Проверить баланс."""
        api_key = self.api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Ошибка", "Введите API-ключ!")
            return

        sms = SMSActivate(api_key)
        balance = sms.get_balance()
        if balance is not None:
            self.balance_label.setText(f"Баланс: {balance:.2f} ₽")
            QMessageBox.information(self, "Баланс", f"Баланс: {balance:.2f} ₽")
        else:
            self.balance_label.setText("Баланс: ошибка")
            QMessageBox.warning(self, "Ошибка", "Не удалось получить баланс")

    def _start_worker(self):
        """Запустить воркер."""
        if not self.api_key_input.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите API-ключ в настройках!")
            self.tabs.setCurrentIndex(2)  # Переключить на настройки
            return

        # Сохраняем настройки
        self._save_settings()

        # Перезагружаем конфиг
        self.config = self._load_config()

        # Создаём воркер
        self.worker = Worker(self.config)

        # Создаём поток
        self.worker_thread = WorkerThread(self.worker)
        self.worker_thread.progress.connect(self._on_progress)
        self.worker_thread.log_message.connect(self._on_log)
        self.worker_thread.finished_signal.connect(self._on_finished)

        # UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setMaximum(self.total_spin.value())
        self.progress_bar.setValue(0)

        # Запускаем
        self.worker_thread.start()
        self._append_log("🚀 Регистрация запущена...")

    def _stop_worker(self):
        """Остановить воркер."""
        if self.worker:
            self.worker.stop()
            self.stop_btn.setEnabled(False)
            self._append_log("⏹ Остановка...")

    def _on_progress(self, done, total, success, failed):
        """Обновить прогресс."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self._refresh_stats()

    def _on_log(self, message):
        """Добавить лог."""
        self._append_log(message)

    def _on_finished(self):
        """По завершении."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._refresh_accounts()
        self._refresh_stats()
        self._append_log("✅ Регистрация завершена")
        QMessageBox.information(self, "Готово", "Регистрация завершена!")

    def _append_log(self, message):
        """Добавить строку в лог."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs_text.append(f"[{timestamp}] {message}")
        # Автопрокрутка
        cursor = self.logs_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.logs_text.setTextCursor(cursor)

    def _refresh_accounts(self):
        """Обновить таблицу аккаунтов."""
        accounts = self.db.get_all_accounts()
        self.accounts_table.setRowCount(len(accounts))

        for row, acc in enumerate(accounts):
            self.accounts_table.setItem(row, 0, QTableWidgetItem(str(acc.get("id", ""))))
            self.accounts_table.setItem(row, 1, QTableWidgetItem(acc.get("email", "")))
            self.accounts_table.setItem(row, 2, QTableWidgetItem(acc.get("password", "")))
            self.accounts_table.setItem(row, 3, QTableWidgetItem(acc.get("phone", "")))

            status_item = QTableWidgetItem(acc.get("status", ""))
            status = acc.get("status", "")
            if status == "success":
                status_item.setForeground(QColor("#4CAF50"))
            elif status in ["failed", "error"]:
                status_item.setForeground(QColor("#f44336"))
            else:
                status_item.setForeground(QColor("#FF9800"))
            self.accounts_table.setItem(row, 4, status_item)

            self.accounts_table.setItem(row, 5, QTableWidgetItem(
                str(acc.get("created_at", ""))
            ))

    def _refresh_stats(self):
        """Обновить статистику."""
        stats = self.db.get_stats()
        total = stats.get("total", 0)
        success = stats.get("success", 0)
        failed = stats.get("failed", 0) + stats.get("errors", 0)

        self.stat_total.setText(f"Всего: {total}")
        self.stat_success.setText(f"✅ Успешно: {success}")
        self.stat_failed.setText(f"❌ Неудачно: {failed}")

        rate = (success / total * 100) if total > 0 else 0
        self.stat_success_rate.setText(f"📊 Процент: {rate:.1f}%")

    def _export_csv(self):
        """Экспорт в CSV."""
        accounts = self.db.get_all_accounts()
        if not accounts:
            QMessageBox.warning(self, "Пусто", "Нет аккаунтов")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить CSV", "accounts.csv", "CSV (*.csv)"
        )
        if not file_path:
            return

        import csv
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "password", "phone", "status", "created_at"])
            for acc in accounts:
                writer.writerow([
                    acc.get("email", ""),
                    acc.get("password", ""),
                    acc.get("phone", ""),
                    acc.get("status", ""),
                    acc.get("created_at", "")
                ])

        QMessageBox.information(self, "Успех", f"Экспортировано: {len(accounts)}")