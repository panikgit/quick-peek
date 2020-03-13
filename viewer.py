"""Window with single large image"""

from PyQt5 import QtWidgets, QtCore

class Viewer(QtWidgets.QWidget):
    """
    Window with large image of height at most fill_height_factor of available
    desktop height.
    May be closed by pressing ESC.
    Center of window is set to coincide with center of the main window if possible.

    Note: Window is modal with fixed size equal to scaled image size.

    Args:
        parent (QtWidgets.QtWidget).

    Attributes:
        view_label (QtWidgets.QLabel): contains image or message "No image".

        available_desktop (QtCore.QRect): shape of available desktop space.

        fill_height_factor (float): maximum fraction of available desktop height
        allowed to be filled by window.

        margin (int): minimum window margin from borders of available desktop.
    """
    def __init__(self, parent=None):
        super(QtWidgets.QWidget, self).__init__(parent)
        self.view_label = QtWidgets.QLabel(self)
        self.view_label.setAlignment(QtCore.Qt.AlignCenter)

        self.setWindowModality(QtCore.Qt.ApplicationModal)

        self.view_label.setText("No image")
        self.view_label.setGeometry(0, 0, 100, 100)
        self.setFixedSize(self.view_label.size())
        self.available_desktop = QtWidgets.qApp.desktop().availableGeometry()
        self.move(self.available_desktop.center() - self.frameGeometry().center())

        self.fill_height_factor = 0.8
        self.margin = 20

    @QtCore.pyqtSlot(QtCore.QEvent)
    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            event.accept()
            self.close()

    def set_viewer(self, source_image, framed_mainwindow_center):
        """
        Called in method of main window class to prepare view window.
        Image view window is placed in such a way that it's center coincides with
        the center of main window if possible.
        Margin from borders of available desktop space is taken into account.

        Args:
            source_image (QtGui.QPixmap): original non scaled image to show.

            framed_mainwindow_center (QtCore.QPoint): center of main window
            used to align image view window.
        """
        display_image = source_image.scaledToHeight(
            min(source_image.size().height(),
                int(self.available_desktop.height()
                    * self.fill_height_factor)
                )
        )
        self.view_label.setPixmap(display_image)
        self.view_label.setGeometry(0, 0,
                                    display_image.size().width(),
                                    display_image.size().height()
                                   )
        self.setFixedSize(self.view_label.size())
        pos = (framed_mainwindow_center - self.frameGeometry().center()
               + self.frameGeometry().topLeft())
        pos.setX(min(max(self.margin, pos.x()),
                         (self.available_desktop.width()
                          - self.margin - self.frameSize().width())
                    )
                )
        pos.setY(min(max(self.margin, pos.y()),
                         (self.available_desktop.height() - self.margin
                          - self.frameSize().height())
                    )
                )
        self.move(pos)
