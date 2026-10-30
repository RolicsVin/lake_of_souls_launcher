"""Лаунчер игры lake_of_souls (PyQt6, Windows 11)."""
import ctypes
import json
import logging
import os
import re
import sys
import threading
import shutil
import math
import random
from ctypes import wintypes

import requests
import win32api
from BlurWindow.blurWindow import blur
from PyQt6.QtCore import (QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread,
                          QTimer, QUrl, pyqtSignal, QElapsedTimer)
from PyQt6.QtGui import (QColor, QCursor, QDesktopServices, QFont,
                         QFontDatabase, QIcon, QImage, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QFileDialog,
                             QGraphicsBlurEffect, QGraphicsPixmapItem,
                             QGraphicsScene, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPushButton, QVBoxLayout, QWidget)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("launcher")

APP_ID = "lake_of_souls.launcher"

# --- пути и ресурсы ---------------------------------------------------------
if getattr(sys, "frozen", False):
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(sys.executable)
else:
    RES_DIR = APP_DIR = os.path.dirname(os.path.abspath(__file__))

SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
DEFAULT_GAME_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "lake_of_souls")


def resource(*parts: str) -> str:
    """Путь к ресурсу рядом со скриптом (или внутри exe)."""
    return os.path.join(RES_DIR, *parts)

# --- игра и ссылки ----------------------------------------------------------
VERSION_URL = "https://drive.google.com/file/d/1DPJs8r586U_GdCSt_m63cvZGm7Mu5mYj/view?usp=sharing"
EXE_URL = ("https://drive.google.com/file/d/"
           "1W7IyXL5zGzpnW-k6KM54nUHUV1uYwc5I/view?usp=drive_link")
PCK_URL = ("https://drive.google.com/file/d/"
           "1SvRGcOW3BH9yUePVzjLtRShAXuW1XF7g/view?usp=drive_link")
VK_LINK = "https://vk.ru/club239057834"
TG_LINK = "https://t.me/obrazec9"

EXE_FILE_NAME = "lake_of_souls.exe"
PCK_FILE_NAME = "lake_of_souls.pck"

# --- геометрия окна ---------------------------------------------------------
WINDOW_W, WINDOW_H = 1525 - 50, 800
CONTENT_X, CONTENT_W, CONTENT_H = 200, 1250, 750
ACTION_SIZE = (200, 80)
ACTION_POS = (1225, 670)

# --- параллакс лого ---------------------------------------------------------
LOGO_PARALLAX = 12       # максимальное смещение лого, px
LOGO_SMOOTHING = 0.1    # плавность: меньше = плавнее/медленнее

# --- DWM (Windows 11) -------------------------------------------------------
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2        # обычное скругление (~8 px)

GLASS_TINT = QColor(100, 80, 80)
GLASS_BORDER = QColor(100, 100, 100, 100)

FLAT_BUTTON_STYLE = """
    QPushButton {
        background-color: rgba(60, 60, 60, 40);
        border: 1px solid rgba(60, 60, 60, 90);
        border-radius: 14px;
        color: white;
        padding: 8px 20px;
    }
    QPushButton:hover   { background-color: rgba(100, 100, 100, 70); }
    QPushButton:pressed { background-color: rgba(100, 100, 100, 25); }
"""

# --- искры ------------------------------------------------------------------
SPARK_RATE = 3            # искр в секунду
SPARK_ANGLE = (28, 55)     # угол полёта над горизонталью, градусы
SPARK_SPEED = (160 // 4, 380 // 4)   # скорость, px/с
SPARK_LIFE = (7, 13)    # время жизни, с
SPARK_SIZE = (1.5, 3.5)    # радиус ядра, px


# --- вспомогательные функции ------------------------------------------------
def get_file_version(path: str) -> str:
    info = win32api.GetFileVersionInfo(path, "\\")
    ms, ls = info["FileVersionMS"], info["FileVersionLS"]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def load_font(path: str, size: int) -> QFont:
    """Загружает шрифт из файла; при неудаче возвращает Arial."""
    font_id = QFontDatabase.addApplicationFont(path)
    families = (QFontDatabase.applicationFontFamilies(font_id)
                if font_id != -1 else [])
    return QFont(families[0] if families else "Arial", size)


def round_window_corners(widget: QWidget, preference: int = DWMWCP_ROUND):
    """Просит DWM скруглить углы окна. Возвращает True при успехе."""
    if sys.platform != "win32":
        return False
    pref = ctypes.c_int(preference)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(int(widget.winId())),
        DWMWA_WINDOW_CORNER_PREFERENCE,
        ctypes.byref(pref),
        ctypes.sizeof(pref),
    )
    return result == 0      # S_OK


def rounded_pixmap(source: QPixmap, radius: float) -> QPixmap:
    """Скругляет углы pixmap."""
    result = QPixmap(source.size())
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing
                           | QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(source.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return result


def open_link(url: str):
    """Открывает ссылку в браузере по умолчанию."""
    if not QDesktopServices.openUrl(QUrl(url)):
        log.warning("Не удалось открыть ссылку: %s", url)


def drive_direct_url(share_url: str) -> str:
    """Превращает ссылку .../file/d/<ID>/view в прямую ссылку на скачивание."""
    match = (re.search(r"/d/([\w-]+)", share_url)
             or re.search(r"[?&]id=([\w-]+)", share_url))
    if not match:
        raise ValueError(f"Не удалось найти ID файла в ссылке: {share_url}")
    return ("https://drive.usercontent.google.com/download"
            f"?id={match.group(1)}&export=download&confirm=t")


def _check_not_html(response: requests.Response):
    if "text/html" in response.headers.get("Content-Type", ""):
        raise RuntimeError("Google Drive вернул HTML: проверьте, что у файла "
                           "открыт доступ «Все, у кого есть ссылка»")


def fetch_remote_version() -> str:
    """Загружает версию игры с Google Drive."""
    response = requests.get(drive_direct_url(VERSION_URL), timeout=15)
    response.raise_for_status()
    _check_not_html(response)
    return response.text.strip()


def download_file(share_url: str, dest: str, on_progress=None,
                  should_stop=None):
    """Скачивает файл с Google Drive. Временный .part всегда удаляется."""
    tmp = dest + ".part"
    try:
        with requests.get(drive_direct_url(share_url), stream=True,
                          timeout=30) as response:
            response.raise_for_status()
            _check_not_html(response)

            total = int(response.headers.get("Content-Length", 0))
            done = 0
            with open(tmp, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if should_stop and should_stop():
                        return
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress and total:
                        on_progress(done / total)

        if total and done != total:
            raise RuntimeError("Файл скачан не полностью")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# --- потоки -----------------------------------------------------------------
class DownloadWorker(QThread):
    progress = pyqtSignal(int)   # общий прогресс 0..100
    done = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, game_path: str, files, parent=None):
        super().__init__(parent)
        self._game_path = game_path
        self._files = files      # [(url, имя_файла), ...]

    def run(self):
        try:
            os.makedirs(self._game_path, exist_ok=True)
            count = len(self._files)
            for i, (url, name) in enumerate(self._files):
                download_file(
                    url, os.path.join(self._game_path, name),
                    on_progress=lambda p, i=i: self.progress.emit(
                        int((i + p) / count * 100)),
                    should_stop=self.isInterruptionRequested,
                )
                if self.isInterruptionRequested():
                    return
            self.done.emit()
        except Exception as e:
            self.failed.emit(str(e))


# --- виджеты ----------------------------------------------------------------
class DragMixin:
    """Перетаскивание безрамочного окна за любое место."""
    drag_position = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = (event.globalPosition().toPoint()
                                  - self.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event):
        if (event.buttons() & Qt.MouseButton.LeftButton
                and self.drag_position is not None):
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None
        event.accept()


class GlassButton(QPushButton):
    """Кнопка с размытым фоном из общей картинки."""

    # Кэш размытых фонов: одна картинка с одним радиусом размывается один раз
    _blur_cache: dict = {}

    def __init__(self, text: str, bg: QPixmap, bg_origin: QPoint, radius=30,
                 blur_radius=25, tint=GLASS_TINT, border=GLASS_BORDER,
                 text_color=QColor(255, 255, 255), icon=None, icon_size=18,
                 icon_spacing=8, parent=None):
        super().__init__(text, parent)
        self._bg = self._get_blurred(bg, blur_radius)
        self._bg_origin = bg_origin
        self._radius = radius
        self._tint = tint
        self._border = border
        self._text_color = text_color
        self._icon_spacing = icon_spacing
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if icon is not None:    # QIcon / QPixmap / путь к файлу
            self.setIcon(icon if isinstance(icon, QIcon) else QIcon(icon))
        if icon_size is not None:
            self.setIconSize(icon_size if isinstance(icon_size, QSize)
                             else QSize(icon_size, icon_size))

    @classmethod
    def _get_blurred(cls, pix: QPixmap, radius: float) -> QPixmap:
        key = (pix.cacheKey(), radius)
        if key not in cls._blur_cache:
            cls._blur_cache[key] = cls._blur_pixmap(pix, radius)
        return cls._blur_cache[key]

    @staticmethod
    def _blur_pixmap(pix: QPixmap, radius: float) -> QPixmap:
        w, h = pix.width(), pix.height()
        pad = int(radius * 2)

        # увеличенный холст, края картинки растягиваем в поля
        big = QImage(w + 2 * pad, h + 2 * pad,
                     QImage.Format.Format_ARGB32_Premultiplied)
        big.fill(Qt.GlobalColor.transparent)
        p = QPainter(big)
        p.drawPixmap(pad, pad, pix)
        p.drawPixmap(QRect(0, pad, pad, h), pix, QRect(0, 0, 1, h))
        p.drawPixmap(QRect(pad + w, pad, pad, h), pix, QRect(w - 1, 0, 1, h))
        p.drawPixmap(QRect(pad, 0, w, pad), pix, QRect(0, 0, w, 1))
        p.drawPixmap(QRect(pad, pad + h, w, pad), pix, QRect(0, h - 1, w, 1))
        img = pix.toImage()
        for x, y, src_x, src_y in ((0, 0, 0, 0), (pad + w, 0, w - 1, 0),
                                   (0, pad + h, 0, h - 1),
                                   (pad + w, pad + h, w - 1, h - 1)):
            p.fillRect(QRect(x, y, pad, pad), img.pixelColor(src_x, src_y))
        p.end()

        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(QPixmap.fromImage(big))
        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(radius)
        effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
        item.setGraphicsEffect(effect)
        scene.addItem(item)

        out = QImage(big.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        scene.render(p, QRectF(out.rect()), QRectF(big.rect()))
        p.end()

        return QPixmap.fromImage(out).copy(pad, pad, w, h)  # обрезаем поля

    def set_colors(self, tint=None, border=None, text_color=None):
        """Меняет цвета на лету."""
        self._tint = tint if tint is not None else self._tint
        self._border = border if border is not None else self._border
        self._text_color = (text_color if text_color is not None
                            else self._text_color)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                            self._radius, self._radius)

        # размытый фон + полупрозрачная заливка
        p.save()
        p.setClipPath(path)
        src = self.geometry().translated(-self._bg_origin)
        p.drawPixmap(0, 0, self._bg, src.x(), src.y(),
                     src.width(), src.height())
        fill = QColor(self._tint)
        fill.setAlpha(25 if self.isDown() else (70 if self._hover else 45))
        p.fillPath(path, fill)
        p.restore()

        p.setPen(QPen(self._border, 1))
        p.drawPath(path)

        # иконка и текст центрируются как единый блок
        text = self.text()
        icon = self.icon()
        has_icon = not icon.isNull()
        icon_size = self.iconSize() if has_icon else QSize(0, 0)
        text_w = self.fontMetrics().horizontalAdvance(text) if text else 0
        gap = self._icon_spacing if (has_icon and text) else 0
        x = (self.width() - (icon_size.width() + gap + text_w)) // 2

        if has_icon:
            icon_rect = QRect(x, (self.height() - icon_size.height()) // 2,
                              icon_size.width(), icon_size.height())
            mode = (QIcon.Mode.Normal if self.isEnabled()
                    else QIcon.Mode.Disabled)
            icon.paint(p, icon_rect, Qt.AlignmentFlag.AlignCenter, mode)
            x += icon_size.width() + gap

        if text:
            p.setPen(self._text_color)
            p.drawText(QRect(x, 0, text_w, self.height()),
                       Qt.AlignmentFlag.AlignVCenter
                       | Qt.AlignmentFlag.AlignLeft, text)
        p.end()


class Spark:
    __slots__ = ("x", "y", "vx", "vy", "evx", "evy", "age", "life", "size",
                 "color", "phase", "flicker")


class SparksOverlay(QWidget):
    """Искры, летящие из левого нижнего угла в правый верхний."""

    def __init__(self, parent, radius: float = 16):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._radius = radius
        self._sparks: list[Spark] = []
        self._spawn_acc = 0.0

        # прогрев: чтобы при запуске искры уже были в полёте
        self._ready = False
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def setGeometry(self, *args):
        super().setGeometry(*args)
        if not self._ready and self.width() > 0:
            self._ready = True
            for _ in range(120):
                self._step(1 / 30)
            self._clock.start()

    def _spawn(self):
        w, h = self.width(), self.height()
        # точка на диагонали от (0, 70% высоты) до (30% ширины, низ)
        t = random.random()
        s = Spark()
        s.x = -10 + t * (w * 0.3 + 10)
        s.y = h * 0.7 + t * (h * 0.3 + 10)
        angle = math.radians(random.uniform(*SPARK_ANGLE))
        speed = random.uniform(*SPARK_SPEED)
        s.vx = math.cos(angle) * speed
        s.vy = -math.sin(angle) * speed
        s.evx, s.evy = s.vx, s.vy
        s.age = 0.0
        s.life = random.uniform(*SPARK_LIFE)
        s.size = random.uniform(*SPARK_SIZE)
        s.color = QColor(255, random.randint(110, 200), random.randint(30, 80))
        s.phase = random.uniform(0, math.tau)
        s.flicker = random.uniform(6, 14)
        self._sparks.append(s)

    def _step(self, dt: float):
        self._spawn_acc += SPARK_RATE * dt
        while self._spawn_acc >= 1:
            self._spawn_acc -= 1
            self._spawn()

        w, h = self.width(), self.height()
        alive = []
        for s in self._sparks:
            s.age += dt
            if s.age >= s.life:
                continue
            # лёгкое колебание поперёк траектории
            wobble = math.sin(s.age * 3 + s.phase) * 25
            s.evx = s.vx + wobble * 0.3
            s.evy = s.vy + wobble
            s.x += s.evx * dt
            s.y += s.evy * dt

            if -20 < s.x < w + 20 and -20 < s.y < h + 20:
                alive.append(s)
            
        self._sparks = alive

    def _tick(self):
        win = self.window()
        if not win.isVisible() or win.isMinimized():
            self._clock.restart()
            return
        dt = min(self._clock.restart() / 1000, 0.05)
        self._step(dt)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        p.setClipPath(clip)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        for s in self._sparks:
            k = s.age / s.life
            fade = math.sin(math.pi * k)                       # плавно появляется и гаснет
            flick = 0.7 + 0.3 * math.sin(s.age * s.flicker + s.phase)
            alpha = max(0.0, min(1.0, fade * flick))

            # направление считаем по фактической скорости
            speed = math.hypot(s.evx, s.evy) or 1.0
            ux, uy = s.evx / speed, s.evy / speed

            # хвост
            tail = s.size * 6
            tx = s.x - ux * tail
            ty = s.y - uy * tail
            c = QColor(s.color)
            c.setAlphaF(alpha * 0.5)
            p.setPen(QPen(c, s.size * 0.8, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(tx, ty), QPointF(s.x, s.y))

            # свечение (круглое, поворот не нужен)
            glow_r = s.size * 4
            grad = QRadialGradient(QPointF(s.x, s.y), glow_r)
            c = QColor(s.color)
            c.setAlphaF(alpha * 0.6)
            grad.setColorAt(0, c)
            c.setAlphaF(0)
            grad.setColorAt(1, c)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawEllipse(QPointF(s.x, s.y), glow_r, glow_r)

            # яркое ядро: эллипс, вытянутый вдоль направления полёта
            core = QColor(255, 240, 200)
            core.setAlphaF(alpha)
            p.setBrush(core)
            p.save()
            p.translate(s.x, s.y)
            p.rotate(math.degrees(math.atan2(s.evy, s.evx)))
            p.drawEllipse(QPointF(0, 0), s.size * 1.1, s.size * 0.5)
            p.restore()
        p.end()


class SettingsWindow(DragMixin, QWidget):
    def __init__(self, launcher):
        super().__init__(
            launcher, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.launcher: Launcher = launcher
        font = launcher.ui_font

        self.setWindowTitle("Настройки")
        self.resize(500, 400)

        layout = QVBoxLayout(self)

        title = QLabel("Настройки")
        title.setStyleSheet(
            "color: white; font-size: 40px; font-weight: bold;")
        title.setFont(font)
        layout.addWidget(title)
        layout.addSpacing(15)

        path_label = QLabel("Путь к игре:")
        path_label.setFont(font)
        layout.addWidget(path_label)

        path_row = QHBoxLayout()    # без parent: layout у окна уже есть
        layout.addLayout(path_row)

        select_btn = QPushButton()
        select_btn.setFont(font)
        select_btn.setIcon(QIcon(resource("icons", "open_folder.png")))
        select_btn.setIconSize(QSize(30, 30))
        select_btn.clicked.connect(self.select_path)
        path_row.addWidget(select_btn)

        self.entry = QLineEdit(launcher.game_path)
        self.entry.setFont(font)
        self.entry.setStyleSheet("font-size: 15px;")
        path_row.addWidget(self.entry)
        layout.addSpacing(15)

        self.close_on_play_check = QCheckBox(
            "Закрывать лаунчер при запуске игры")
        self.close_on_play_check.setFont(font)
        self.close_on_play_check.setStyleSheet(
            "color: white; font-size: 15px;")
        self.close_on_play_check.setChecked(launcher.close_on_play)
        layout.addWidget(self.close_on_play_check)
        layout.addSpacing(15)

        delete_game = QPushButton("Удалить игру")
        delete_game.setStyleSheet("color: red;")
        delete_game.setFont(font)
        delete_game.clicked.connect(launcher.delete_game)
        layout.addWidget(delete_game)

        layout.addStretch()

        save_btn = QPushButton("Сохранить")
        save_btn.setStyleSheet(FLAT_BUTTON_STYLE)
        save_btn.setFont(font)
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        p.end()

    def showEvent(self, event):
        super().showEvent(event)
        round_window_corners(self)

    def select_path(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с игрой", self.entry.text())
        if folder:
            self.entry.setText(folder)

    def save(self):
        launcher = self.launcher
        path = self.entry.text().strip()
        if path:    # путь применяется только по кнопке «Сохранить»
            launcher.game_path = os.path.normpath(path)
        launcher.close_on_play = self.close_on_play_check.isChecked()
        self.close()
        launcher.save_settings()
        launcher.update_button()


class Launcher(DragMixin, QMainWindow):
    # сигнал из фонового потока проверки версии
    remote_version_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        # Если blur не виден, раскомментируйте строку ниже:
        # self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            "Launcher { background-color: transparent; border: none; }")
        self.resize(WINDOW_W, WINDOW_H)

        self.game_path = DEFAULT_GAME_PATH
        self.close_on_play = False
        self.download_worker = None
        self.local_version = None
        self.settings_window = None
        self.ui_font = load_font(resource("Constantine.ttf"), 15)

        self.remote_version_ready.connect(self._on_remote_version)

        self.init_ui()

        self._logo_offset = QPointF(0, 0)
        self._parallax_timer = QTimer(self)
        self._parallax_timer.timeout.connect(self._update_logo_parallax)
        self._parallax_timer.start(16)     # ~60 FPS

        self.load_settings()
        self.update_button()
        self.show()

    # --- интерфейс ---
    def init_ui(self):
        # фон и логотип
        self._bg_pixmap = QPixmap(resource("bg1920x1080.png")).scaled(
            CONTENT_W, CONTENT_H)
        self.main_icon = QLabel(self)
        self.main_icon.setGeometry(CONTENT_X, 25, CONTENT_W, CONTENT_H)
        self.main_icon.setPixmap(rounded_pixmap(self._bg_pixmap, 16))

        logo_pixmap = QPixmap(resource("game_logo.png")).scaled(
            836, 836, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.logo = QLabel(self)
        self.logo.move(370, 0)
        self.logo.setPixmap(rounded_pixmap(logo_pixmap, 16))
        self._logo_base = self.logo.pos()
        self.logo.setGeometry(CONTENT_X + 170, 0,
                              logo_pixmap.width(), logo_pixmap.height())
        self.logo.setPixmap(rounded_pixmap(logo_pixmap, 16))

        # искры поверх фона и лого, под кнопками
        self.sparks = SparksOverlay(self)
        self.sparks.setGeometry(self.main_icon.geometry())

        # кнопки "Играть", "Установить", "Исправить" и мини-кнопка обновления
        self.play_button = self._glass_button(
            "Играть", ACTION_SIZE, ACTION_POS, handler=self.play_game)
        self.load_game = self._glass_button(
            "Установить", ACTION_SIZE, ACTION_POS, "download.png",
            handler=self.download_game)
        self.tool_button = self._glass_button(
            "Исправить", ACTION_SIZE, ACTION_POS, "tools.png",
            handler=self.download_game)
        self.mini_update_button = self._glass_button(
            "", (80, 80), (1135, 670), "download.png",
            handler=self.download_game)
        self._state_buttons = (self.play_button, self.load_game,
                               self.tool_button, self.mini_update_button)
        for button in self._state_buttons:
            button.hide()

        # ссылки на соцсети
        for icon, link, y in (("tg.webp", TG_LINK, 50),
                              ("vk.webp", VK_LINK, 175)):
            button = QPushButton(self)
            button.resize(100, 100)
            button.setIcon(QIcon(resource(icon)))
            button.setIconSize(QSize(70, 70))
            button.move(50, y)
            button.setStyleSheet(FLAT_BUTTON_STYLE)
            button.clicked.connect(lambda _=False, url=link: open_link(url))

        # "настройки", "свернуть", "закрыть"
        bold_font = QFont("arial", 15)
        bold_font.setBold(True)
        for text, icon, x, handler in (
                ("", "settings.png", 1270, self.open_settings),
                ("-", None, 1330, self.showMinimized),
                ("", "close.png", 1390, self.close)):
            self._glass_button(text, (50, 50), (x, 35), icon, 50,
                               bold_font, handler)

    def _update_logo_parallax(self):
        """Плавно сдвигает лого в сторону курсора."""
        if not self.isVisible() or self.isMinimized():
            return

        center = self.geometry().center()
        cursor = QCursor.pos()
        # положение курсора относительно центра окна, в диапазоне -1..1
        nx = max(-1.0, min(1.0, (cursor.x() - center.x()) / (self.width() / 2)))
        ny = max(-1.0, min(1.0, (cursor.y() - center.y()) / (self.height() / 2)))

        target = QPointF(nx * LOGO_PARALLAX, ny * LOGO_PARALLAX)
        # сглаживание: каждый кадр приближаемся к цели на часть расстояния
        self._logo_offset = (self._logo_offset
                             + (target - self._logo_offset) * LOGO_SMOOTHING)

        new_pos = self._logo_base + QPoint(round(self._logo_offset.x()),
                                           round(self._logo_offset.y()))
        if new_pos != self.logo.pos():
            self.logo.move(new_pos)

    def _glass_button(self, text, size, pos, icon=None, icon_size=35,
                      font=None, handler=None) -> GlassButton:
        """Создаёт стеклянную кнопку на общем размытом фоне."""
        button = GlassButton(
            text, self._bg_pixmap, self.main_icon.pos(), parent=self,
            icon=resource("icons", icon) if icon else None,
            icon_size=icon_size)
        button.resize(*size)
        button.move(*pos)
        button.setFont(font or self.ui_font)
        if handler:
            button.clicked.connect(handler)
        return button

    # --- состояние кнопок ---
    def update_button(self):
        """Показывает нужную кнопку: «Играть», «Установить» или «Исправить».

        Кнопка обновления появляется позже, после фоновой проверки версии.
        """
        for button in self._state_buttons:
            button.hide()

        exe_path = os.path.join(self.game_path, EXE_FILE_NAME)
        pck_path = os.path.join(self.game_path, PCK_FILE_NAME)

        # игры нет совсем: установка
        if not os.path.isfile(exe_path) and not os.path.isfile(pck_path):
            self.load_game.show()
            return

        # не хватает файла или он пустой: исправление
        if not all(os.path.isfile(p) and os.path.getsize(p) > 0
                   for p in (exe_path, pck_path)):
            self.tool_button.show()
            return

        # exe не читается (битый): исправление
        try:
            self.local_version = get_file_version(exe_path)
        except Exception as e:
            log.warning("Не удалось прочитать версию exe: %s", e)
            self.tool_button.show()
            return

        # играть можно сразу, проверка версии идёт в фоне
        self.play_button.show()
        self._check_remote_version()

    def _check_remote_version(self):
        """Запрашивает версию на сервере, не блокируя интерфейс."""
        def task():
            try:
                self.remote_version_ready.emit(fetch_remote_version())
            except Exception as e:   # офлайн: просто остаёмся без обновления
                log.warning("Не удалось получить версию: %s", e)

        threading.Thread(target=task, daemon=True).start()

    def _on_remote_version(self, remote_version: str):
        log.info("Версии: %s (локальная), %s (на сервере)",
                 self.local_version, remote_version)
        # пока идёт скачивание или состояние сменилось, кнопку не трогаем
        if (remote_version != self.local_version
                and self.download_worker is None
                and not self.play_button.isHidden()):
            self.mini_update_button.show()

    # --- действия ---
    def play_game(self):
        exe_path = os.path.join(self.game_path, EXE_FILE_NAME)
        try:
            os.startfile(exe_path)
        except OSError as e:
            log.error("Не удалось запустить игру: %s", e)
            return   # игра не запустилась: лаунчер не закрываем

        if self.close_on_play:
            self.close()

    def download_game(self):
        """Скачивает (или обновляет) игру в фоне."""
        if self.download_worker is not None:
            return

        for button in self._state_buttons:
            button.hide()
        self.load_game.setEnabled(False)
        self.load_game.setText("Скачиваем 0%")
        self.load_game.show()

        worker = DownloadWorker(
            self.game_path,
            [(EXE_URL, EXE_FILE_NAME), (PCK_URL, PCK_FILE_NAME)],
            parent=self)    # parent держит поток живым до завершения
        worker.progress.connect(
            lambda percent: self.load_game.setText(f"Скачиваем {percent}%"))
        worker.done.connect(self._on_download_done)
        worker.failed.connect(self._on_download_failed)
        worker.finished.connect(worker.deleteLater)
        self.download_worker = worker
        worker.start()

    def _on_download_done(self):
        log.info("Установка завершена")
        self._finish_download()

    def _on_download_failed(self, message: str):
        log.error("Ошибка скачивания: %s", message)
        self._finish_download()

    def _finish_download(self):
        self.download_worker = None
        self.load_game.setText("Установить")
        self.load_game.setEnabled(True)
        self.update_button()

    def delete_game(self):
        try:
            shutil.rmtree(self.game_path)
            print('Игра удалена')
        except Exception as e:
            print(f'Не удалось удалить игру; {e}')

    # --- настройки ---
    def save_settings(self):
        data = {"game_path": self.game_path,
                "close_on_play": self.close_on_play}
        with open(SETTINGS_PATH, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load_settings(self):
        try:
            with open(SETTINGS_PATH, encoding="utf8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:   # нет файла или он повреждён
            log.info("Настройки по умолчанию (%s)", e)
            self.save_settings()
            return
        self.game_path = data.get("game_path", self.game_path)
        self.close_on_play = data.get("close_on_play", False)

    def open_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self)

        # синхронизируем виджеты с актуальными настройками
        self.settings_window.close_on_play_check.setChecked(self.close_on_play)
        self.settings_window.entry.setText(self.game_path)

        # центрируем относительно лаунчера
        center = self.geometry().center()
        settings = self.settings_window
        settings.move(center - settings.rect().center())
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    # --- события окна ---
    def paintEvent(self, event):
        # боковое меню
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(25, 25, 150, 750), 16, 16)
        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        blur(int(self.winId()))
        round_window_corners(self)

    def closeEvent(self, event):
        # не оставляем поток скачивания работать после закрытия окна
        if self.download_worker is not None:
            self.download_worker.requestInterruption()
            self.download_worker.wait(3000)
        super().closeEvent(event)


if __name__ == "__main__":
    # Свой AppUserModelID: без него при запуске из VS Code Windows
    # показывает иконку python.exe и группирует окно с ним
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource("icons", "app.ico")))
    window = Launcher()
    sys.exit(app.exec())