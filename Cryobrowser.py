from bs4 import BeautifulSoup
from pathlib import Path
from platform import system
from PySide6.QtCore import (
    Qt,
    QDate,
    QObject,
    QSize,
    QThread,
    QUrl,
    Signal
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QIcon,
    QImageReader,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut
)
from PySide6.QtWidgets import (
    QApplication,
    QCalendarWidget,
    QCheckBox,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget
)
from requests import get
from urllib.parse import urljoin

class Fetcher(QObject):
    chart_ready = Signal(str)
    progress = Signal(int, int, str)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, date: QDate, sources: set):
        super().__init__()
        self.date = date
        self.sources = sources

    def run(self):
        urls = list()

        if 'cryo.met.no' in self.sources:
            base_url = 'https://cryo.met.no/archive/ice-service/icecharts/quicklooks/{}/'.format(self.date.toString('yyyy/yyyyMMdd'))
            response = get(base_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            urls += ['{}{}'.format(base_url, a['href']) for a in soup.find_all('a', href=True) if a['href'].endswith('.png')]

        if 'ice.aari.aq' in self.sources:
            base_url = 'http://ice.aari.aq/antice/{}_nic/'.format(self.date.toString('yyyy/MM/yyyyMMdd'))
            response = get(base_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            urls += ['{}{}'.format(base_url, a['href']) for a in soup.find_all('a', href=True) if a['href'].endswith('_ct.png') or a['href'].endswith('_sd.png')]
            base_url = 'http://ice.aari.aq/antice/{}_aari/'.format(self.date.toString('yyyy/MM/yyyyMMdd'))
            response = get(base_url)
            soup = BeautifulSoup(response.content, 'html.parser')
            urls += ['{}{}'.format(base_url, a['href']) for a in soup.find_all('a', href=True) if a['href'].endswith('_ct.png') or a['href'].endswith('_sd.png')]

        if 'noaadata.apps.nsidc.org' in self.sources:
            for hemisphere in ['north', 'south']:
                base_url = 'https://noaadata.apps.nsidc.org/NOAA/G02135/{}/daily/images/{}/'.format(hemisphere, self.date.toString('yyyy/MM_MMM'))
                response = get(base_url)
                soup = BeautifulSoup(response.content, 'html.parser')
                urls += ['{}{}'.format(base_url, a['href']) for a in soup.find_all('a', href=True) if a['href'][2:10] == self.date.toString('yyyyMMdd') and a['href'].endswith('conc_hires_v4.0.png')]
                urls += ['{}{}'.format(base_url, a['href']) for a in soup.find_all('a', href=True) if a['href'][2:10] == self.date.toString('yyyyMMdd') and a['href'].endswith('extn_hires_v4.0.png')]

        for i, url in enumerate(urls, 1):
            if QThread.currentThread().isInterruptionRequested(): break
            name = url.rsplit('/', 1)[-1]
            path = cache_folder / name
            self.progress.emit(i, len(urls), name)
            if not path.exists():
                response = get(url)
                path.write_bytes(response.content)
            self.chart_ready.emit(str(path))
        self.finished.emit()

class ImageView(QGraphicsView):
    zoom_changed = Signal(float)
    min_scale, max_scale = 0.1, 2
    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene()
        self.setScene(self._scene)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._scene.addItem(self._item)
        self._fit = True

        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHints(QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)

    def set_image(self, path: str | None) -> bool:
        pix = QPixmap(path) if path else QPixmap()
        self._item.setPixmap(pix)
        self._scene.setSceneRect(self._item.boundingRect())
        self.fit()

    def fit(self):
        self._fit = True
        self.resetTransform()
        self.fitInView(self._item, Qt.KeepAspectRatio)
        if self.transform().m11() > 1.0:
            self.resetTransform()
        self._scale_changed()

    def actual_size(self):
        self._fit = False
        self.resetTransform()
        self._scale_changed()

    def zoom_by(self, factor: float, under_mouse: bool = False):
        cur = self.transform().m11()
        new = min(max(cur * factor, self.min_scale), self.max_scale)
        if new == cur:
            return
        self.setTransformationAnchor(
            QGraphicsView.AnchorUnderMouse if under_mouse else QGraphicsView.AnchorViewCenter)
        self.scale(new / cur, new / cur)
        self._fit = False
        self._scale_changed()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self.fit()

    def mouseDoubleClickEvent(self, e):
        self.actual_size() if self._fit else self.fit()

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy:
            self.zoom_by(1.25 ** (dy / 120), under_mouse=True)
        e.accept()

    def _scale_changed(self):
        scale = self.transform().m11()
        self._item.setTransformationMode(Qt.FastTransformation if scale >= 2 else Qt.SmoothTransformation)
        self.zoom_changed.emit(scale * 100)

class Settings(QWidget):
    def __init__(self):
        super().__init__()

        clear_cache = QPushButton('Clear Cache')
        clear_cache.clicked.connect(self.clear_cache)

        layout = QVBoxLayout()
        layout.addWidget(clear_cache)

        self.resize(640, 480)
        self.setLayout(layout)
        self.setWindowTitle('Settings')

    def clear_cache(self):
        for p in cache_folder.iterdir():
            if p.is_file() or p.is_symlink():
                p.unlink()

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread = None
        self.statusBar().showMessage('Pick a date to fetch charts')

        self.calendar = QCalendarWidget()
        self.calendar.clicked.connect(self.refresh)
        self.calendar.setMaximumDate(QDate.currentDate())

        self.cryo_met_no = QCheckBox('cryo.met.no')
        self.cryo_met_no.clicked.connect(self.refresh)
        self.cryo_met_no.setChecked(True)

        self.ice_aari_aq = QCheckBox('ice.aari.aq')
        self.ice_aari_aq.clicked.connect(self.refresh)
        self.ice_aari_aq.setChecked(True)

        self.noaadata_apps_nsidc_org = QCheckBox('noaadata.apps.nsidc.org')
        self.noaadata_apps_nsidc_org.clicked.connect(self.refresh)
        self.noaadata_apps_nsidc_org.setChecked(True)

        sources = QGroupBox()
        sources_layout = QVBoxLayout()
        sources_layout.addWidget(self.cryo_met_no)
        sources_layout.addWidget(self.ice_aari_aq)
        sources_layout.addWidget(self.noaadata_apps_nsidc_org)
        sources.setLayout(sources_layout)

        self.thumbnails = QListWidget()
        self.thumbnails.setViewMode(QListWidget.IconMode)
        self.thumbnails.setIconSize(QSize(192, 192))
        self.thumbnails.setResizeMode(QListWidget.Adjust)
        self.thumbnails.setMovement(QListWidget.Static)
        self.thumbnails.setWordWrap(True)
        self.thumbnails.itemClicked.connect(self.on_select)

        sidebar_layout = QVBoxLayout()
        sidebar_layout.addWidget(self.calendar)
        sidebar_layout.addWidget(sources)
        sidebar_layout.addWidget(self.thumbnails, stretch=1)

        self.image_view = ImageView()
        self.info = QLabel()
        self.zoom_label = QLabel('100%')
        self.zoom_label.setMinimumWidth(56)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.image_view.zoom_changed.connect(lambda p: self.zoom_label.setText(f'{p:.0f}%'))

        def tool(text, tip, slot):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(48)
            b.clicked.connect(slot)
            return b

        modifier = 'Ctrl'
        if system() == 'Darwin': modifier = '⌘'

        zoom_bar = QHBoxLayout()
        zoom_bar.addWidget(tool('\u2212', f'Zoom out ({modifier} -)', lambda: self.image_view.zoom_by(1 / 1.25)))
        zoom_bar.addWidget(self.zoom_label)
        zoom_bar.addWidget(tool('+', f'Zoom in ({modifier} =)', lambda: self.image_view.zoom_by(1.25)))
        zoom_bar.addWidget(tool('Fit', f'Fit to window ({modifier} 0)', self.image_view.fit))
        zoom_bar.addWidget(tool('1:1', f'Actual size ({modifier} 1)', self.image_view.actual_size))
        zoom_bar.addStretch(1)
        # zoom_bar.addWidget(QLabel('wheel = zoom   |   drag = pan   |   double-click = fit/1:1'))

        for keys, fn in (
            (('Ctrl+=', 'Ctrl++'), lambda: self.image_view.zoom_by(1.25)),
            (('Ctrl+-',), lambda: self.image_view.zoom_by(1 / 1.25)),
            (('Ctrl+0',), self.image_view.fit),
            (('Ctrl+1',), self.image_view.actual_size)
        ):
            for k in keys:
                QShortcut(QKeySequence(k), self, activated=fn)

        browser_layout = QVBoxLayout()
        browser_layout.addLayout(zoom_bar)
        browser_layout.addWidget(self.image_view)
        browser_layout.addWidget(self.info)

        layout = QHBoxLayout()
        layout.addLayout(sidebar_layout)
        layout.addLayout(browser_layout, stretch=1)

        widget = QWidget()
        widget.setLayout(layout)

        cache_folder_action = QAction('Open Cache Folder…', self)
        cache_folder_action.triggered.connect(self.open_cache_folder)

        file_menu = self.menuBar().addMenu('File')
        file_menu.addAction(cache_folder_action)

        settings_action = QAction('Settings…', self)
        settings_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        settings_action.setShortcut(QKeySequence.StandardKey.Preferences)
        settings_action.triggered.connect(self.open_settings)

        if system() != 'Darwin':
            edit_menu = self.menuBar().addMenu('Edit')
            edit_menu.addAction(settings_action)
        else:
            file_menu.addAction(settings_action)

        self.resize(1280, 800)
        self.setCentralWidget(widget)
        self.setWindowTitle('Cryobrowser')

    def open_cache_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(cache_folder))

    def open_settings(self):
        self.settings = Settings()
        self.settings.show()

    def refresh(self):
        self.interrupt()
        self.thumbnails.clear()
        sources = set()
        if self.cryo_met_no.isChecked(): sources.add('cryo.met.no')
        if self.ice_aari_aq.isChecked(): sources.add('ice.aari.aq')
        if self.noaadata_apps_nsidc_org.isChecked(): sources.add('noaadata.apps.nsidc.org')
        self.thread = QThread(self)
        self.fetcher = Fetcher(self.calendar.selectedDate(), sources)
        self.fetcher.moveToThread(self.thread)
        self.thread.started.connect(self.fetcher.run)
        self.fetcher.chart_ready.connect(self.add_thumbnail)
        self.fetcher.progress.connect(self.update_progress)
        self.fetcher.failed.connect(self.fetcher_failed)
        self.fetcher.finished.connect(self.fetcher_finished)
        self.thread.start()

    def add_thumbnail(self, path: str):
        pixmap = QPixmap(path)
        item = QListWidgetItem(QIcon(pixmap), Path(path).name)
        self.thumbnails.addItem(item)

    def on_select(self, cur: QListWidgetItem):
        path = cache_folder / cur.text()
        self.image_view.set_image(path)
        r = QImageReader(str(path))
        sz = r.size()
        self.info.setText(f'{path}   |   {sz.width()}x{sz.height()}   |   {path.stat().st_size / 1024:.1f} KB')

    def update_progress(self, done: int, total: int, name: str):
        self.statusBar().showMessage(f'Fetching {name} ({done} of {total})')

    def fetcher_failed(self, e):
        self.statusBar().showMessage(e)
        self.thread.quit

    def fetcher_finished(self):
        self.statusBar().showMessage('Fetcher finished', 3000)
        self.thread.quit

    def interrupt(self):
        if self.thread:
            self.thread.requestInterruption()
            self.thread.quit()
            self.thread.wait()

if __name__ == '__main__':
    home = Path.home()
    match system():
        case 'Darwin': cache_folder = home / 'Library/Caches/Cryobrowser/'
        case 'Windows': cache_folder = home / 'AppData/Local/Temp/Cryobrowser/'
    if not cache_folder.exists(): cache_folder.mkdir(exist_ok=True, parents=True)

    app = QApplication([])

    main = Main()
    main.show()

    app.aboutToQuit.connect(main.interrupt)
    app.exec()