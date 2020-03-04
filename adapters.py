"""Non-API adapters to http resources: reddit.com, gfycat.com, imgur.com"""

import abc
import re
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from submission import SubmissionRL


BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"\
            " (KHTML, like Gecko) Chrome/77.0.3835.0 Safari/537.36"
}


class SubredditIterator:
    """old.reddit.com scraper

    Implements iterator interface.
    Iterates over submissions of hot section of given subreddit.
    Parses whole page at time.

    Class attributes:
        class NoSubmissionsAvailable (Exception): main exception
        caused by HTTPRequestsFailed or NoSubmissionsOnPage.

        class HTTPRequestsFailed (Exception): raised on HTTP requests failure.

        class NoSubmissionsOnPage (Exception): raised if reddit page
        has no submissions.

        REDDIT_URL (str): old.subreddit.com.

        SUBMISSIONS_PER_PAGE (int): 25 submissions per page.

    Instance attributes:
        subreddit_url (str): https://old.reddit.com/r/<subreddit>.

        referer (str): HTTP referer -- previous subreddit page.

        after (str): URL parameter used by reddit to denote previous submission.

        count (int): ditto, number of viewed submissions.

        submissions (list): parsed submissions of type SubmissionRL.

        submission_idx (int): points to next submission in submissions list.

    Args:
        subreddit_name (str): name of subreddit to browse.

        http_headers (dict): HTTP session headers.
        If not specified used BROWSER_HEADERS.
    """

    class NoSubmissionsAvailable(Exception):
        """High-level exception

        Causes StopIteration.
        Caused by other internal exceptions.
        """

    class HTTPRequestsFailed(Exception):
        """HTTP requests failed"""

    class NoSubmissionsOnPage(Exception):
        """No submissions on reddit page"""

    REDDIT_URL = "https://old.reddit.com"
    SUBMISSIONS_PER_PAGE = 25

    def __init__(self, subreddit_name, http_headers=None):
        self.subreddit_url = self.REDDIT_URL + "/r/" + subreddit_name
        self.referer = ""
        self.after = ""
        self.count = 0
        self.submissions = []
        self.submission_idx = 0
        self.session = requests.Session()
        if http_headers is None:
            http_headers = BROWSER_HEADERS
        self.session.headers.update(**http_headers, **{"Host": "old.reddit.com"})
        try:
            self.load_submissions()
        except self.NoSubmissionsAvailable:
            pass

    def reset(self, subreddit_name):
        """
        Clear state and assign /r/<subreddit_name>.
        HTTP session is untouched.

        Args:
            subreddit_name (str): new subreddit to scrape.
        """
        self.subreddit_url = self.REDDIT_URL + "/r/" + subreddit_name
        self.referer = ""
        self.after = ""
        self.count = 0
        self.submissions = []
        self.submission_idx = 0

    def __iter__(self):
        return self

    def __next__(self):
        """
        Returns:
            SubmissionRL: parsed submission related URLs.

        Note:
            Internal state is unchanged on failure.
        """
        next_submission = self.get_next_submission()
        if next_submission is None:
            try:
                self.load_submissions()
            except self.NoSubmissionsAvailable as error:
                raise StopIteration from error

        next_submission = self.get_next_submission()
        return next_submission

    def get_next_submission(self):
        """
        Returns:
            SubmissionRL: next cached submission if any.

            None: otherwise.
        """
        if self.submission_idx < len(self.submissions):
            i = self.submission_idx
            self.submission_idx += 1
            return self.submissions[i]

        return None

    def load_submissions(self):
        """
        Request and parse next page.
        Update submissions cache and internal state accordingly.

        Raises:
            NoSubmissionsAvailable.
        """
        try:
            response = self.__request_next_page()
            self.__update(response)
        except (self.HTTPRequestsFailed, self.NoSubmissionsOnPage) as error:
            raise self.NoSubmissionsAvailable from error

    def __request_next_page(self):
        """
        Request next subreddit page.

        Returns:
            requests.Response: HTTP response containing next subreddit page.

        Raises:
            NoSubmissionsAvailable: HTTP requests failed.
        """
        url = self.subreddit_url
        if self.count != 0:
            url += f"/?count={self.count}&after={self.after}"
        referer_header = {"Referer": self.referer} if self.referer is not None else {}
        tries = 2
        interval = 2
        while True:
            response = self.session.get(url, headers=referer_header)
            if response.status_code == 200:
                break
            tries -= 1
            if tries == 0:
                raise self.HTTPRequestsFailed(f"Code {response.status_code}"
                                              f", {response.url}")
            time.sleep(interval)

        if urlparse(response.url).path.rsplit("/", maxsplit=1)[-1] == "over18":
            time.sleep(interval)
            response = self.session.post(
                response.url,
                headers={
                    "Origin": self.REDDIT_URL,
                    "Referer": self.REDDIT_URL,
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                params={"dest": url},
                data={"over18": "yes"}
            )
        if response.status_code != 200:
            raise self.HTTPRequestsFailed("Age verification step"
                                          f", code {response.status_code}"
                                          f", {response.url}")
        return response

    def __update(self, response):
        """
        Update submissions cache and internal state.

        Args:
            response (requests.Response): HTTP response containing subreddit page.

        Raises:
            NoSubmissionsOnPage.
        """
        parsed_submissions, last_submission_id = self.parse(response)
        if parsed_submissions is None:
            raise self.NoSubmissionsOnPage(response.url)

        for submission in parsed_submissions:
            submission.url_referer = response.url
        self.submissions = parsed_submissions
        self.submission_idx = 0
        self.referer = response.url
        self.after = last_submission_id
        self.count += self.SUBMISSIONS_PER_PAGE

    @staticmethod
    def parse(response):
        """
        Parse subreddit page.

        Args:
            response (requests.Response): response with subreddit page.

        Returns:
            list: list of objects SubmissionRL with parsed submissions.

            str: id of last submission on page used by reddit as HTTP
            request parameter 'after'.
        """
        parsed_submissions = []
        submission_id_pattern = re.compile("thing_t3")
        thing = BeautifulSoup(response.content, "lxml")\
                    .find("div", id=submission_id_pattern)
        last_submission_id = None
        while thing is not None:
            if "promoted" not in thing.attrs["class"]:
                parsed_submissions.append(SubmissionRL(url=thing.attrs["data-url"]))
                last_submission_id = thing.attrs["id"]
            thing = thing.find_next_sibling("div", id=submission_id_pattern)

        if last_submission_id is None:
            return None, None

        return parsed_submissions, last_submission_id.replace("thing_", "")


class SubmissionResolver(abc.ABC):
    """Abstract base class of resolvers of submission related URLs

       Replaces URLs of external resources with direct URLs of
       media files.

       Class attributes:
            class HTTPRequestsFailed (Exception): raised if HTTP requests fail.

            class MediaIsUnavailable (Exception): high-level exception caused by
            other internal exceptions.

       Instance attributes:
            session (requests.Session): persistent HTTP session established with
            external resource delivering submitted media.

            target_media_extensions (list or tuple of str): extensions of
            wanted media file types.

       Args:
            target_media_extensions (lits | tuple of str): collection
            of file extensions without periods.

            http_headers (dict): base HTTP headers.
    """

    class HTTPRequestsFailed(Exception):
        """HTTP requests fail"""

    class MediaIsUnavailable(Exception):
        """Universal exception raised in case if no requested media is found"""

    def __init__(self, target_media_extensions, http_headers=None):
        self.session = requests.Session()
        if http_headers is None:
            http_headers = BROWSER_HEADERS
        self.session.headers.update(http_headers)
        self.target_media_extensions = target_media_extensions

    def resolve(self, submission):
        """
        Replace submitted URL with direct URL of media file.
        Replace other URLs accordingly.

        Args:
            submission (SubmissionRL): submission related URLs.

        Raises:
            MediaIsUnavailable.
        """
        try:
            response = self.request_page(submission.url, submission.url_referer)
        except self.HTTPRequestsFailed as error:
            raise self.MediaIsUnavailable from error

        url_direct, url_extra = self.parse(response)
        if url_direct is None:
            raise self.MediaIsUnavailable(f"No media with known extension found"
                                          f", {response.url}")

        submission.url = url_direct
        submission.url_extra = url_extra
        submission.url_referer = response.url

    def request_page(self, url_page, url_referer=None):
        """
        Make several HTTP requests with given arguments.

        Args:
            url_page (str): URL of requested HTTP page.

            url_referer (str): HTTP referer, may be None.

        Returns:
            response (requests.Response): response with requested page.

        Raises:
            HTTPRequestsFailed: if page is unavailable.
        """
        referer_header = {"Referer": url_referer} if url_referer is not None else {}
        tries = 2
        interval = 1
        while True:
            response = self.session.get(url_page, headers=referer_header)
            if response.status_code != 200:
                if tries == 0:
                    raise self.HTTPRequestsFailed(
                        f"Code {response.status_code}, {url_page}")

                time.sleep(interval)
                tries -= 1
            else:
                break
        return response

    @abc.abstractmethod
    def parse(self, response):
        """Abstract method of page parsing
        Parse requested page.
        Args:
            response (requests.Response): HTTP response with HTML page to be parsed.

        Returns:
            str: direct URL of submitted media file.

            str: extra URL related to submitted media, e.g. preview image.

        Note: is expected not to raise exceptions and return pair of None instead.
        """
        return None, None


class GfycatResolver(SubmissionResolver):
    """Gfycat URL resolver

    Replaces submitted URL of gfycat page with direct URL of video file.
    Adds extra URL of preview image if any.

    Parents:
        SubmissionResolver: abstract class.

    Overrides:
        parse.

    Args:
        video_extensions (list or tuple of str): sequence of known video
        extensions.

        http_headers (dict): basic HTTP headers.
    """

    def __init__(self,
                 video_extensions=("mp4", "webp", "webm"),
                 http_headers=None):
        super().__init__(video_extensions, http_headers)
        self.session.headers.update({"Host": "gfycat.com"})

    def parse(self, response):
        """
        Parse gfycat page to obtain direct URL of submitted video and preview
        image if any.
        Accept domains thumbs.gfycat.com or zippy.gfycat.com.

        Args:
            response (requests.Response): response containing gfycat page.

        Returns:
            str: direct URL of video.

            str: direct URL of image preview.
        """
        video = BeautifulSoup(response.content, "lxml").find("video")
        if video is None:
            return None, None

        url_poster = video.attrs.get("poster")
        for source in video.find_all("source"):
            url = source.attrs["src"]
            url_parts = urlparse(url)
            if (url_parts.netloc.startswith(("thumbs", "zippy"))
                    and (url_parts.path.rsplit(".", maxsplit=1)[-1]
                         in self.target_media_extensions)
               ):
                return url, url_poster

        return None, None


class ImgurResolver(SubmissionResolver):
    """Imgur URL resolver

    Replaces submitted URL of imgur page with direct URL
    of media file if possible.
    Extracts direct URL of media or indirect URL of zip-packed album.
    Adds extra URL of preview image if any.

    Parents:
        SubmissionResolver: abstract class.

    Overrides:
        resolve,
        parse.

    Args:
        media_extensions (list or tuple of str): collection of known media
        extensions.

        http_headers (dict): basic HTTP headers.

    Attributes:
        session (requests.Session).
    """

    def __init__(self,
                 media_extensions=("mp4", "webp", "webm", "jpg", "jpeg", "png"),
                 http_headers=None):
        super().__init__(media_extensions, http_headers)
        self.session.headers.update({"Host": "imgur.com"})

    def resolve(self, submission):
        """
        Do nothing if URL has filename with media extension.
        Use older version of imgur URLs to call parent's resolve.
        Such an indirect URL concatenated with /zip points to submitted media.

        Args:
            submission (SubmissionRL): URLs related to submitted media.

        Raises:
            MediaIsUnavailable: imgur is unavailable or no media file
            with target media extension is found.
        """
        url_parts = urlparse(submission.url)
        if "." in url_parts.path.rsplit("/", maxsplit=1)[-1]:
            ext = url_parts.path.rsplit(".", maxsplit=1)[-1]
            if ext in self.target_media_extensions:
                return

            raise self.MediaIsUnavailable(f"Unknown media extension {ext}"
                                          f", {submission.url}")

        if url_parts.path.startswith("/gallery"):
            submission.url = submission.url.replace("gallery", "a")

        SubmissionResolver.resolve(self, submission)

    def parse(self, response):
        """
        Parse imgur page to obtain direct URL of submitted media and preview
        image if any.
        Accept domains thumbs.gfycat.com or zippy.gfycat.com.

        Args:
            response (requests.Response): response containing imgur page.

        Returns:
            str: direct URL of media.

            str: direct URL of image preview.

        Note: preview image is expected to be jpeg or jpg file so it's URL
        is not verified.
        """
        head = BeautifulSoup(response.content, "lxml").head
        image = head.find("link", {"rel": "image_src"})
        if image is not None:
            url_direct = response.url + "/zip"
            # expected jpg, jpeg image
            url_extra = image.attrs.get("href")
        else:
            video = head.find("meta", {"property": "og:video"})
            if video is not None:
                url_direct = video.attrs.get("content")
                if (url_direct.rsplit(".", maxsplit=1)[-1]
                        not in self.target_media_extensions):
                    return None, None

                image = head.find("meta", {"property": "og:image"})
                # expected jpg, jpeg image
                url_extra = image.attrs.get("content")
                if url_extra is not None:
                    url_extra = url_extra.split("?", maxsplit=1)[0]
            else:
                return None, None

        return url_direct, url_extra


class DirectURLResolver:
    """File extension checker

    Is intended for verification of direct URLs.

    Attributes:
        target_media_extensions (list or tuple of str): collection of known media
        extensions.

    Args:
        media_extensions (lits or tuple of str): collection
        of file extensions without periods.
    """
    def __init__(self, media_extensions=("mp4", "webp", "webm", "jpg", "jpeg", "png")):
        self.target_media_extensions = media_extensions

    def resolve(self, submission):
        """
        Check file extension specified in submitted URL.
        If extension is known do nothing.

        Raises:
            SubmissionResolver.MediaIsUnavailable: extension is unknown.
        """
        if "." not in urlparse(submission.url).path.rsplit("/", maxsplit=1)[-1]:
            raise SubmissionResolver.MediaIsUnavailable(
                f"Expected period in filename, {submission.url}")

        ext = urlparse(submission.url).path.rsplit(".", maxsplit=1)[-1]
        if ext not in self.target_media_extensions:
            raise SubmissionResolver.MediaIsUnavailable(
                f"Unknown media extension {ext}, {submission.url}")
