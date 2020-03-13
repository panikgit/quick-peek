"""Window containing VLC player instance"""

import pathlib

from PyQt5 import QtCore, QtGui, QtWidgets, uic
import vlc

import resources

class Player(QtWidgets.QWidget):
    """Separate window with video player

    Has QFrame with VLC player screen and control panel with Qt control elements:
    button play/pause and timeline, volume, rate (x1, x1.5, x2) sliders.
    Uses internal timer to update UI.
    Window may be closed by pressing ESC.
    Center of window is set to coincide with center of the main window if possible.

    Note: Window is modal.

    Args:
        parent (QtWidgets.QtWidget).

    Attributes:
        Window elements:
            frame_video (QtWidgets.QFrame): contains player screen.

            button_play (QtWidgets.QPushButton).

            icon_play (QtGui.QIcon).

            icon_pause (QtGui.QIcon).

            combobox_rate (QtWidgets.QComboBox): combobox with playing rates.

            label_rate (QtWidgets.QLabel): contains icon of speedometer.

            slider_timeline (QtWidgets.QSlider).

            slider_volume (QtWidgets.QSlider).

            label_volume (QtWidgets.QLabel): contains icon of volume.

            layout_panel (QtWidgets.QHBoxLayout): contains control panel.

            layout_global (QtWidgets.QVBoxLayout): contains screen frame and
            horizontal control panel layout.

        play_rates (tuple): (1, 1.5, 2).

        vlc (vlc.Instance): instance of VLC.

        player (vlc.MediaPlayer): instance of VLC player.

        update_timer (QtCore.QTimer): timer is used to synchronize UI with playback.

        media (vlc.Media): URL-based instance of media.

        available_desktop (QtCore.QRect): shape of available desktop space.

        margin (int): minimum window margin from borders of available desktop.
    """
    def __init__(self, parent=None):
        super(QtWidgets.QWidget, self).__init__(parent)
        uic.loadUi(str(pathlib.Path(__file__).parent.absolute()) + "/player.ui", self)
        palette = self.frame_video.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0))
        self.frame_video.setPalette(palette)
        self.frame_video.setAutoFillBackground(True)

        self.icon_play = QtGui.QIcon()
        self.icon_play.addPixmap(QtGui.QPixmap(":play16"))
        self.button_play.setIcon(self.icon_play)
        self.icon_pause = QtGui.QIcon()
        self.icon_pause.addPixmap(QtGui.QPixmap(":pause16"))
        self.play_rates = (1, 1.5, 2)
        self.combobox_rate.addItems(map(str, self.play_rates))
        self.layout_global = QtWidgets.QVBoxLayout(self)
        self.layout_panel = QtWidgets.QHBoxLayout()
        self.setup_layout()

        self.setWindowModality(QtCore.Qt.ApplicationModal)
        self.available_desktop = QtWidgets.qApp.desktop().availableGeometry()
        self.move(self.available_desktop.center() - self.frameGeometry().center())

        self.margin = 20

        self.update_timer = QtCore.QTimer(self)
        self.update_timer.setInterval(200)

        self.vlc = vlc.Instance()
        self.player = self.vlc.media_player_new()
        self.player.set_xwindow(int(self.frame_video.winId()))
        self.media = None
        self.init_volume()

        self.assign_signals()

    def setup_layout(self):
        self.layout_panel.addWidget(self.button_play)
        self.layout_panel.addWidget(self.slider_timeline)
        self.layout_panel.setStretchFactor(self.slider_timeline, 10)
        self.layout_panel.addWidget(self.label_volume)
        self.layout_panel.addWidget(self.slider_volume)
        self.layout_panel.setStretchFactor(self.slider_volume, 1)
        self.layout_panel.addWidget(self.label_rate)
        self.layout_panel.addWidget(self.combobox_rate)
        self.layout_global.addWidget(self.frame_video)
        self.layout_global.addLayout(self.layout_panel)
        self.setLayout(self.layout_global)

    def assign_signals(self):
        self.update_timer.timeout.connect(self.update_ui)
        self.button_play.clicked.connect(self.play_pause)
        self.slider_volume.valueChanged.connect(self.set_volume)
        self.slider_timeline.sliderMoved.connect(self.set_timeline_pos)
        self.combobox_rate.currentIndexChanged.connect(self.set_rate)

    @QtCore.pyqtSlot(QtCore.QEvent)
    def closeEvent(self, event):
        self.player.stop()
        event.accept()

    @QtCore.pyqtSlot(QtCore.QEvent)
    def keyPressEvent(self, event):
        """
        Close on button ESC pressed.

        Args:
            event (QtCore.QEvent).
        """
        if event.key() == QtCore.Qt.Key_Escape:
            event.accept()
            self.close()

    @QtCore.pyqtSlot()
    def play_pause(self):
        """
        Pause/continue playback, change play and pause icons accordingly,
        manage UI timer.
        """
        if self.player.is_playing():
            self.player.pause()
            self.button_play.setIcon(self.icon_play)
            self.update_timer.stop()
        else:
            self.button_play.setIcon(self.icon_pause)
            self.player.play()
            self.update_timer.start()

    @QtCore.pyqtSlot(int)
    def set_rate(self, rate_idx):
        """
        Playing rate is a value from self.rates set by means of the combobox.
        In case of failure playing rate is equal to 1.

        Args:
            rate_idx (int): index of chosen playing rate in self.rates.
        """
        if -1 == self.player.set_rate(self.play_rates[rate_idx]):
            self.player.set_rate(1)
            self.combobox_rate.setItemData(self.play_rates.index(1))

    def init_volume(self, volume=50):
        """
        By default volume value is half of nominal.

        Args:
            volume (int).
        """
        self.player.audio_set_volume(volume)
        self.slider_volume.setValue(volume)

    @QtCore.pyqtSlot(int)
    def set_volume(self, volume):
        self.player.audio_set_volume(volume)

    @QtCore.pyqtSlot()
    def set_timeline_pos(self):
        """Update UI timeline according to playback time"""
        self.update_timer.stop()
        self.player.set_position(
            self.slider_timeline.value() / self.slider_timeline.maximum())
        self.update_timer.start()

    @QtCore.pyqtSlot()
    def update_ui(self):
        if self.player.is_playing():
            self.slider_timeline.setValue(int(self.player.get_position()
                                              * self.slider_timeline.maximum()))
        else:
            if not self.player.will_play():
                self.update_timer.stop()
                self.button_play.setIcon(self.icon_play)
                self.slider_timeline.setValue(self.slider_timeline.minimum())
                self.player.stop()

    def set_player(self, url, framed_mainwindow_center):
        """
        Called in method of main window class to prepare player window
        and playback.
        Player window is placed in such a way that it's center coincides with
        the center of main window if possible.
        Margin from borders of available desktop space is taken into account.

        Args:
            url (str): direct URL of submitted video file.

            framed_mainwindow_center (QtCore.QPoint): center of main window
            used to align player window.
        """
        self.media = self.vlc.media_new(url)
        self.player.set_media(self.media)
        self.init_volume()
        pos = (framed_mainwindow_center - self.frameGeometry().center()
               + self.frameGeometry().topLeft())
        pos.setX(min(max(self.margin, pos.x()),
                         (self.available_desktop.width() - self.margin
                          - self.frameSize().width())
                    )
                )
        pos.setY(min(max(self.margin, pos.y()),
                         (self.available_desktop.height() - self.margin
                          - self.frameSize().height())
                    )
                )
        self.move(pos)
