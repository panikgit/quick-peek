"""
Adapters to http resources: reddit.com
"""
import re
import time
from urllib.parse import urlparse
import requests

from bs4 import BeautifulSoup

from submission import Submission

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"\
            " (KHTML, like Gecko) Chrome/77.0.3835.0 Safari/537.36"
}

class SubredditAdapter:
    """Reddit parser. Iterates over submissions."""

    class NoSubmissionsAvailable(Exception):
        """Universal error"""

    REDDIT_URL = "https://old.reddit.com"
    DEFAULT_SLICE_LENGTH = 25

    def __init__(self, subreddit_name):
        """
        Tie parser to the given subreddit to iterate over hot submissions.
        Make http session with persistent cookies.
        referer - http referer value to mimic legal browser,
        after - url parameter used by reddit denoting last submission on slice,
        count - ditto, number of already seen submissions,
        submissions - list of parsed Submission objects,
        submission_idx points to next submission.
        """
        self.subreddit_url = SubredditAdapter.REDDIT_URL + "/r/" + subreddit_name
        self.referer = ""
        self.after = ""
        self.count = 0
        self.submissions = []
        self.submission_idx = 0

        self.session = requests.Session()
        self.session.headers.update(**COMMON_HEADERS, **{"Host": "old.reddit.com"})
        self.__next_submissions()

    def reset(self, subreddit_name):
        """
        Clear, tie to subreddit_name. Session is untouched.
        May be used to change subreddit."
        """
        self.subreddit_url = SubredditAdapter.REDDIT_URL + "/r/" + subreddit_name
        self.referer = ""
        self.after = ""
        self.count = 0
        self.submissions = []
        self.submission_idx = 0

    def __next_submissions(self):
        """
        Request and parse reddit submissions.
        Makes 'tries' request attempts with reddit's 'interval'=2s.
        Throws NoSubmissionsAvailable when http requests fail
        or requested subreddit page has no submissions.
        On exception keeps internal state unchanged, updates on success.
        """
        url = self.subreddit_url
        if self.count != 0:
            url += f"/?count={self.count}&after={self.after}"

        tries = 2
        interval = 2
        while True:
            response = self.session.get(url, headers=\
                    {"Referer": self.referer} if self.referer else {})
            if response.status_code == 200:
                break
            tries -= 1
            if tries == 0:
                raise SubredditAdapter.NoSubmissionsAvailable(
                    f"Page {response.url} is unavailable."\
                    f" Last response status {response.status_code}.")
            time.sleep(interval)

        if urlparse(response.url).path.rsplit("/", maxsplit=1)[-1] == "over18":
            time.sleep(interval)
            response = self.session.post(
                response.url,
                headers={
                    "Origin": SubredditAdapter.REDDIT_URL,
                    "Referer": SubredditAdapter.REDDIT_URL,
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                params={"dest": url},
                data={"over18": "yes"}
            )
        if response.status_code != 200:
            raise SubredditAdapter.NoSubmissionsAvailable(
                f"Age verification step failed, code {response.status_code}.")

        parsed_submissions, last_submission_id = self.parse(response)
        if len(parsed_submissions) == 0:
            raise SubredditAdapter.NoSubmissionsAvailable(
                f"No submissions on page {response.url}")

        self.submissions = parsed_submissions
        self.submission_idx = 0
        self.referer = response.url
        self.after = last_submission_id
        self.count += SubredditAdapter.DEFAULT_SLICE_LENGTH

    @staticmethod
    def parse(response):
        """Parses response page for submissions' urls, saves referer."""
        parsed_submissions = []
        submission_id_pattern = re.compile("thing_t3")
        thing = BeautifulSoup(response.content, "lxml")\
                    .find("div", id=submission_id_pattern)
        last_submission_id = None
        while thing is not None:
            if "promoted" not in thing.attrs["class"]:
                parsed_submissions.append(
                    Submission(url=thing.attrs["data-url"],
                               referer=response.url)
                )
                last_submission_id = thing.attrs["id"]
            thing = thing.find_next_sibling("div", id=submission_id_pattern)

        if last_submission_id is None:
            return [], None

        return parsed_submissions, last_submission_id.replace("thing_", "")

    def __next__(self):
        """Returns next submission from cache list. Requests for more if none."""
        if self.submission_idx == len(self.submissions):
            try:
                self.__next_submissions()
            except SubredditAdapter.NoSubmissionsAvailable as error:
                raise StopIteration from error
        i = self.submission_idx
        self.submission_idx += 1
        return self.submissions[i]

    def __iter__(self):
        return self
