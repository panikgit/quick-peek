#!/usr/bin/python3
"""Minimal working example of native GUI application that allows to view
images and play videos submitted in hot sections of media-based subreddits

Application relies on non-API access to web resources.
Scrapes direct URLs of media files and URLs of external resources
(gfycat.com, imgur.com) from subreddit feed.
URLs of external resources are resolved to direct URLs of media files.
Images are downloaded and shown by Qt tools, videos are streamed
through libvlc-based player.

Note:
    Not all submitted media files are shown like those of type gif or gifv.
    Direct URLs are expected to specify following file extensions:
        jpeg, jpg, png (images),
        mp4, webm (videos).
"""

import queue
import collections
import time
import pathlib
from urllib.parse import urlparse

import requests

from PyQt5 import QtWidgets, QtCore, QtGui, uic

from viewer import Viewer
from player import Player

from adapters import (
    BROWSER_HEADERS,
    SubredditIterator,
    SubmissionResolver,
    GfycatResolver,
    ImgurResolver,
    DirectURLResolver
)


Media = collections.namedtuple("Media", ("type", "content", "preview"))
""" Submitted media

Attributes:
    type (str): "image", "video" -- type of submitted media.

    content (str or bytes): URL of video file for video type or
    bytes of original image for image type.

    preview (bytes or None): for video type bytes of preview image if any.
"""


class QuickPeek(QtWidgets.QWidget):
    """Main window

    Reads subreddit name and provides UI for iterating
    over hot section of given subreddit internally by means of
    MediaProvider class.
    Allows to enlarge image or play video in separate window.

    Note: Main window has fixed size.

    Args:
        parent (QtWidgets.QWidget): parent widget.

    Attributes:
        Window elements:
            button_start (QtWidgets.QPushButton): read given
            subreddit name, reset MediaIterator and load first
            submitted media file if any.

            button_next (QtWidgets.QPushButton): load and show
            next submitted media file if any.

            button_enlarge (QtWidgets.QPushButton): open new
            window with large image or video player.

            label_image (QtWidgets.QLabel): shows preview image.

            thumbnail_play (QtGui.QPixmap): icon showed for videos
            lacking of preview image.

        media (Media): submitted media.

        media_image (QtGui.QPixmap): original image to show --
        source image or preview for video.

        media_provider (MediaProvider): asynchronously delivers next submitted media.
        It is executed in separate thread. The main purpose of usage is to keep network
        related logic implementing blocking waits in another thread to prevent UI freezes.

        viewer (viewer.Viewer): window with large image, opened on demand.

        player (player.Player): window with video player, opened on demand.
    """

    def __init__(self, parent=None):
        super(QtWidgets.QWidget, self).__init__(parent)
        uic.loadUi(str(pathlib.Path(__file__).parent.absolute()) + "/quick_peek.ui", self)
        self.thumbnail_play = QtGui.QPixmap(":play80")
        self.setFixedSize(self.size())
        self.move(QtWidgets.qApp.desktop().availableGeometry().center() -
                  self.frameGeometry().center())

        self.button_next.setDisabled(True)
        self.button_enlarge.setDisabled(True)

        self.button_start.clicked.connect(self.browse_subreddit)
        self.button_next.clicked.connect(self.request_next)
        self.button_enlarge.clicked.connect(self.show_media)

        self.media_provider = MediaProvider()
        self.media_provider.sig_provided.connect(self.update)

        self.media = None
        self.media_image = QtGui.QPixmap()
        self.viewer = None
        self.player = None

    @QtCore.pyqtSlot()
    def browse_subreddit(self):
        """
        Read given subreddit name and use it to update internal state of
        MediaProvider.
        """
        self.button_next.setDisabled(True)
        subreddit_name = self.line_subreddit.text()
        self.media_provider.sig_reset.emit(subreddit_name)

    @QtCore.pyqtSlot()
    def request_next(self):
        self.button_next.setDisabled(True)
        self.media_provider.sig_request_next.emit()

    @QtCore.pyqtSlot(Media)
    def update(self, media):
        """
        Called on next submitted media delivery.
        Informs user if nothing to show next. Loads preview and unblocks
        UI buttons otherwise.

        Args:
            media (Media): submitted media.
        """
        self.media = media

        if media.type is None:
            self.label_image.setText("No media available")
            self.button_enlarge.setDisabled(True)
            return

        if media.type == "image":
            self.media_image.loadFromData(self.media.content)
            self.button_enlarge.setText("Enlarge")
        elif media.type == "video":
            self.button_enlarge.setText("Play")
            if media.preview is None:
                self.media_image = self.thumbnail_play
            else:
                self.media_image.loadFromData(media.preview)

        self.label_image.setPixmap(
            self.media_image.scaledToHeight(self.label_image.size().height())
        )
        self.button_next.setDisabled(False)
        self.button_enlarge.setDisabled(False)

    @QtCore.pyqtSlot()
    def show_media(self):
        """
        Prepare and open window with large image or video player.
        """
        if self.media.type == "image":
            if self.viewer is None:
                self.viewer = Viewer()
            self.viewer.set_viewer(self.media_image,
                                   self.frameGeometry().center())
            self.viewer.show()
        elif self.media.type == "video":
            if self.player is None:
                self.player = Player()
            self.player.set_player(self.media.content,
                                   self.frameGeometry().center())
            self.player.show()
        else:
            self.button_enlarge.setDisabled(True)

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

    @QtCore.pyqtSlot(QtGui.QCloseEvent)
    def closeEvent(self, event):
        self.hide()
        self.media_provider.sig_stop.emit()
        self.media_provider.main_thread.wait()
        event.accept()


class MediaProvider(QtCore.QObject):
    """Asynchronous adapter to MediaIterator

        Asynchronously delivers submitted media.
        Creates and is executed in separate thread.
        Encapsulates blocking access to web resources.
        In background caches more media for better UI responsiveness.

        Args:
            parent (QtCore.QObject).

        Attributes:
            media_iterator (MediaIterator): iterates over subreddit submissions.

            max_cache_size (int).

            cache (queue.Queue).

            main_thread (QtCore.QThread): separate thread with QEventLoop.

            Flags:
                is_stopped (bool): stop to perform requests to current subreddit.
                Depends on state of MediaIterator.

                is_reseted (bool): subreddit was changed, cache was emptied.

                is_filling_cache (bool): in process of filling cache. Is used to
                prevent recursive calls of cache filling function.

                is_request_pending (bool): cache was empty, user is waiting for media.

                to_discard_download_on_reset (bool): if user performed subreddit reset
                after next media has been downloaded the media must be discarded.
                The flag is used in pair with reset flag to distinguish initial reset
                and keep downloaded media.

            Signals:
                sig_stop (QtCore.pyqtSignal): user closed app.

                sig_request_next (QtCore.pyqtSignal): user requested next media.

                sig_reset (QtCore.pyqtSignal): user changed subreddit.

                sig_provided (QtCore.pyqtSignal): signal main window media delivery.

                sig_fill_cache (QtCore.pyqtSignal): internal signal. Not enough media
                in cache, the cache is needed to be filled.
    """
    sig_request_next = QtCore.pyqtSignal()
    sig_reset = QtCore.pyqtSignal(str)
    sig_stop = QtCore.pyqtSignal()
    sig_provided = QtCore.pyqtSignal(Media)
    sig_fill_cache = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_thread = QtCore.QThread()
        self.main_thread.start()
        self.moveToThread(self.main_thread)

        self.media_iterator = None
        self.max_cache_size = 10
        self.cache = queue.Queue(maxsize=self.max_cache_size)

        self.to_discard_download_on_reset = False
        self.is_reseted = False
        self.is_stopped = False
        self.is_filling_cache = False
        self.is_request_pending = False

        self.sig_stop.connect(self.stop, QtCore.Qt.QueuedConnection)
        self.sig_fill_cache.connect(self.fill_cache, QtCore.Qt.QueuedConnection)
        self.sig_request_next.connect(self.next, QtCore.Qt.QueuedConnection)
        self.sig_reset.connect(self.reset, QtCore.Qt.QueuedConnection)

    @QtCore.pyqtSlot()
    def run(self):
        """Event loop"""
        self.exec_()

    @QtCore.pyqtSlot()
    def stop(self):
        """
        User closed app -- set stop flag True to stop filling cache if running,
        stop event loop.
        """
        self.is_stopped = True
        self.main_thread.exit()

    @QtCore.pyqtSlot(str)
    def reset(self, subreddit_name):
        """
        User changed subreddit -- clear cache, request first media submitted in chosen
        subreddit.

        Args:
            subreddit_name (str): chosen subreddit.
        """
        if self.media_iterator is not None:
            self.media_iterator.reset(subreddit_name)
        else:
            self.media_iterator = MediaIterator(subreddit_name)
        self.cache = queue.Queue(maxsize=self.max_cache_size)
        self.is_stopped = False
        self.is_reseted = True
        self.next()

    @QtCore.pyqtSlot()
    def next(self):
        """
        User requested next media. Get it from cache or in case if empty request
        process of cache filling and wait for next download.
        """
        if not self.cache.empty():
            self.sig_provided.emit(self.cache.get())
        else:
            self.is_request_pending = True
            if not self.is_filling_cache:
                self.sig_fill_cache.emit()

    @QtCore.pyqtSlot()
    def fill_cache(self):
        """
        Start filling cache.
        May be interrupted on events processing before and after time consuming
        media requests.
        On request failure deliver special media object.
        On success if user is waiting deliver downloaded media immediately, otherwise
        put in cache.
        """
        self.is_filling_cache = True
        while not self.is_stopped and not self.cache.full():
            QtWidgets.qApp.processEvents()
            try:
                media = next(self.media_iterator)
            except StopIteration:
                self.is_stopped = True
                media = Media(type=None,
                              content=None,
                              preview=None
                             )
            QtWidgets.qApp.processEvents()
            if self.is_reseted:
                self.is_reseted = False
                if self.to_discard_download_on_reset:
                    continue
                self.to_discard_download_on_reset = True

            if self.is_request_pending:
                self.sig_provided.emit(media)
                self.is_request_pending = False
            else:
                self.cache.put(media)
        self.is_filling_cache = False


class MediaIterator:
    """
    Iterates over subreddit submissions using SubredditIterator,
    resolves URLs to gfycat.com, imgur.com and downloads submission
    related image.
    Performs timed requests for media to resources other than reddit.
    Implements iterator interface.
    In case of album submission downloads it's first image.
    In case of video submission downloads preview. URL of submitted video
    is returned to be used for streaming.

    Class attributes:
        class HTTPRequestsFailed (Exception).

    Instance attributes:
        video_extensions (tuple of str): known extensions.

        image_extensions (tuple of str): known extensions.

        subreddit (SubredditIterator): iterator, iterates
        over hot section of given subreddit.

        imgur_resolver (ImgurResolver): replaces submitted URL to
        imgur.com with direct URL of media file. Updates related
        URLs accordingly.

        gfycat_resolver (GfycatResolver): replaces submitted URL to
        gfycat.com with direct URL of media file. Updates related
        URLs accordingly.

        direct_url_resolver (DirectURLResolver): checks whether given
        URL is direct.

        download_session (requests.Session): HTTP session solely used
        to download submitted media files.

        media_request_interval (int): reasonable request time internal for
        web resources other than reddit.

        last_request_time (dict): key (str) -- domain,
        value (int) -- approximate last request time.

    Args:
        subreddit_name (str): used by SubredditIterator.

    Note:
        Resolvers act according to the choice of known video and image
        file extensions.
    """

    class HTTPRequestsFailed(Exception):
        """Internal exception causes StopIteration"""

    def __init__(self, subreddit_name):
        self.video_extensions = ("mp4", "webm")
        self.image_extensions = ("jpg", "jpeg", "png")
        self.subreddit = SubredditIterator(subreddit_name)
        self.imgur_resolver = ImgurResolver(self.video_extensions
                                            + self.image_extensions)
        self.gfycat_resolver = GfycatResolver(self.video_extensions)
        self.direct_url_resolver = DirectURLResolver(self.video_extensions
                                                     + self.image_extensions)
        self.download_session = requests.Session()
        self.download_session.headers.update(BROWSER_HEADERS)

        self.last_request_time = dict()
        self.media_request_interval = 1

    def reset(self, subreddit_name):
        """Change subreddit"""
        self.subreddit.reset(subreddit_name)

    def __iter__(self):
        return self

    def __next__(self):
        """
        Get next submission related URLs from SubredditIterator.
        Resolve URLs and download submitted file on success.
        Each failure counts until the count exceeds the maximum and
        StopIteration is raised. This is done to limit requests count
        and user response waiting time for subreddits lacking of
        media submissions of known type. Initially maximum count of unresolved
        submissions is set roughly to 3 * SubredditIterator.SUBMISSIONS_PER_PAGE.

        Note: occasionally next(SubredditIterator) returns None.
        This behaviour is unexpected so additional checking for None
        is added.

        Raises:
            StopIteration: is caused by NoSubmissionsAvailable exception
            or if maximum count of unresolved submissions is exceeded or
            file downloading failure (HTTPRequestsFailed exception).

        Returns:
            Media: submitted media or special Media object in case of request failure.
        """
        media_type = None
        media_content = None
        media_preview = None
        unresolved_left = 3 * SubredditIterator.SUBMISSIONS_PER_PAGE
        while media_type is None and unresolved_left > 0:
            try:
                submission = next(self.subreddit)
            except SubredditIterator.NoSubmissionsAvailable as error:
                raise StopIteration from error

            if submission is None:
                continue

            media_type = self.resolve_submission(submission)
            if media_type is None:
                unresolved_left -= 1
                continue

            try:
                if media_type == "image":
                    response = self.request_media_file(submission.url,
                                                       submission.url_referer)
                    media_content = response.content
                elif media_type == "video" and submission.url_extra is not None:
                    response = self.request_media_file(submission.url_extra,
                                                       submission.url_referer)
                    media_content = submission.url
                    media_preview = response.content
                else:
                    media_type = None
                    unresolved_left -= 1
            except self.HTTPRequestsFailed as error:
                raise StopIteration from error

        if unresolved_left == 0:
            raise StopIteration("Too many unresolved submissions, "
                                "probably non-media subreddit")

        return Media(type=media_type,
                     content=media_content,
                     preview=media_preview
                    )

    def request_media_file(self, url, url_referer):
        """Series of requests

        Note: Uses time.sleep between requests initially with
        interval of 1s. Retries request if response code is not 200.

        Args:
            url (str): target URL.
            url_referer (str): HTTP referer.

        Raises:
            HTTPRequestsFailed.

        Returns:
            requests.Response: response containing media file.
        """
        referer_header = {"Referer": url_referer} if url_referer is not None else {}
        tries = 2
        domain = urlparse(url).netloc
        while True:
            self.wait_before_request(domain)
            response = self.download_session.get(url, headers=referer_header)
            self.last_request_time[domain] = time.monotonic()
            if response.status_code != 200:
                if tries == 0:
                    raise self.HTTPRequestsFailed(
                        f"Code {response.status_code}, {url}")
                tries -= 1
            else:
                break
        return response

    def resolve_submission(self, submission):
        """
        If submitted URL points to gfycat.com use gfycat resolver,
        for imgur.com use imgur resolver. In the third case URL is
        either direct and checked with direct URL resolver or not,
        which means ignored and None is returned.
        Perform timed requests.

        Note: ignore imgur albums. /zip ended URLs
        are replaced with URLs of preview images.

        Args:
            submission (SubmissionRL): submission related URLs.

        Returns:
            str or None: strings "video", "image" are returned
            if direct URL of file with known extension is found,
            None otherwise.
        """
        url_parts = urlparse(submission.url)
        try:
            if url_parts.netloc == "gfycat.com":
                self.wait_before_request("gfycat.com")
                self.gfycat_resolver.resolve(submission)
                self.last_request_time["gfycat.com"] = time.monotonic()
                return "video"

            if url_parts.netloc == "imgur.com":
                self.wait_before_request("imgur.com")
                self.imgur_resolver.resolve(submission)
                self.last_request_time["imgur.com"] = time.monotonic()
                if (url_parts.path.rsplit(".", maxsplit=1)[-1]
                        in self.video_extensions):
                    return "video"

                if submission.url_extra is not None:
                    submission.url = submission.url_extra
                    return "image"

                return None

            self.direct_url_resolver.resolve(submission)
            if (url_parts.path.rsplit(".", maxsplit=1)[-1]
                    in self.video_extensions):
                return "video"

            return "image"
        except SubmissionResolver.MediaIsUnavailable:
            return None

    def wait_before_request(self, domain):
        """
        Sleep if request time interval to given domain is less than
        chosen request period.
        """
        interval = time.monotonic() - self.last_request_time.get(domain, 0)
        if interval < self.media_request_interval:
            time.sleep(self.media_request_interval - interval)


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    window = QuickPeek()
    window.show()
    sys.exit(app.exec_())
