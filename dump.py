#!/usr/bin/python3

"""Functions for dumping submission related information

dump_urls -- dumps submission related URLs as json,

download_submissions -- downloads submitted media files.

Functions rely on non-api access to web resources:
    old.reddit.com, imgur.com. gfycat.com.
"""

import argparse
import json
import os
import time
from urllib.parse import urlparse

import requests

from submission import SubmissionRL
from adapters import (
    BROWSER_HEADERS,
    SubredditIterator,
    SubmissionResolver,
    GfycatResolver,
    ImgurResolver,
    DirectURLResolver
)


class SubmissionIterator:
    """Helper class used to iterate over submissions posted in hot section
    of given subreddit and to provide direct URLs of submitted media files

    To obtain direct URL of submitted media file corresponding submission
    must initially contain direct URL or point to imgur.com or gfycat.com.
    Class implements iterator interface. On each iteration URLs related to
    submitted media are returned.

    Args:
        subreddit_name (str).

        image_extensions (tuple or list of str): target extensions of submitted
        images.

        video_extensions (tuple or list of str): target extensions of submitted
        video files.

    Attributes:
        subreddit_iterator (SubredditIterator): used to iterate over submissions
        posted in hot section of given subreddit.

        Resolvers replace submitted URLs with direct URLs:
            gfycat_resolver (GfycatResolver): for domain gfycat.com.

            imgur_resolver (ImgurResolver): for domain imgur.com.

            direct_url_resolver (DirectURLResolver): checks whether given URL
            is direct and target file has known media extension.

        Request period sets reasonable restriction on requests frequency:
            REDDIT_ACCESS_PERIOD (int): for old.reddit.com.

            RESOLVE_PERIOD (int): for external media resources.

        Last access time value is used to track request time intervals and to
        comply with chosen request frequency restriction:
            last_reddit_access_time (int): for old.reddit.com.

            last_gfycat_access_time (int): for gfycat.com.

            last_imgur_access_time (int): for imgur.com.

        submissions_requested (int): total count of observed submissions.
    """
    def __init__(self, subreddit_name, image_extensions, video_extensions):
        self.subreddit_iterator = SubredditIterator(subreddit_name)
        self.gfycat_resolver = GfycatResolver(video_extensions)
        self.imgur_resolver = ImgurResolver(image_extensions + video_extensions)
        self.direct_url_resolver = DirectURLResolver(image_extensions + video_extensions)
        self.last_reddit_access_time = 0
        self.last_gfycat_access_time = 0
        self.last_imgur_access_time = 0
        self.REDDIT_ACCESS_PERIOD = 2
        self.RESOLVE_PERIOD = 1
        self.submissions_requested = 0

    def __iter__(self):
        return self

    def __next__(self):
        try:
            submission = self.__request_submission_at_time()
        except StopIteration as error:
            raise StopIteration from error

        if submission is not None:
            self.__resolve(submission)

        return submission

    def __request_submission_at_time(self):
        """
        Get submission related URLs with respect to old.reddit.com access period.

        Returns:
            SubmissionRL: submission related URLs.

        Raises:
            StopIteration: if no more submissions available.
        """
        if (self.submissions_requested
                % self.subreddit_iterator.SUBMISSIONS_PER_PAGE == 0
                and self.submissions_requested > 0
           ):
            reddit_access_interval = time.monotonic() - self.last_reddit_access_time
            if reddit_access_interval < self.REDDIT_ACCESS_PERIOD:
                time.sleep(self.REDDIT_ACCESS_PERIOD - reddit_access_interval)
            try:
                submission = next(self.subreddit_iterator)
            finally:
                self.last_reddit_access_time = time.monotonic()
        else:
            submission = next(self.subreddit_iterator)
        self.submissions_requested += 1
        return submission

    def __resolve(self, submission):
        """
        Replace submitted URLs with direct URLs. Update related URLs accordingly.

        Args:
            submission (SubmissionRL).
        """
        url_parts = urlparse(submission.url)
        domain = url_parts.netloc
        if domain == "imgur.com":
            self.last_imgur_access_time =\
                self.__resolve_at_time(self.imgur_resolver, submission,
                                       self.last_imgur_access_time)
        elif domain == "gfycat.com":
            self.last_gfycat_access_time =\
                self.__resolve_at_time(self.gfycat_resolver, submission,
                                       self.last_gfycat_access_time)
        else:
            self.direct_url_resolver.resolve(submission)

    def __resolve_at_time(self, resolver, submission, last_resolve_time):
        """Called by __resolve method

        Used to abstract from details of resolver.
        Complies request frequency restrictions.

        Args:
            resolver (SubmissionResolver or DirectURLResolver).

            submission (SubmissionRL).

            last_resolve_time (int).

        Returns:
            int: time of last request to external media resource.
        """
        resolve_interval = time.monotonic() - last_resolve_time
        if resolve_interval < self.RESOLVE_PERIOD:
            time.sleep(self.RESOLVE_PERIOD - resolve_interval)
        resolver.resolve(submission)
        return time.monotonic()


class SubmissionDownloader:
    """Helper class used to download media files

    Sets and complies reasonable restriction on requests frequency.

    Args:
         outdir_path (str): path to save media files. If directory
         doesn't exist attempt to create one.

    Attributes:
        outdir_path (str).

        download_session (requests.Session).

        DOWNLOAD_PERIOD (int): default download time interval 1s.

        last_downloads (dict): key (str) - domain,
        value (int) - last download time.
    """
    def __init__(self, outdir_path):
        if not os.path.exists(outdir_path):
            os.makedirs(outdir_path)
        self.outdir_path = outdir_path
        self.download_session = requests.Session()
        self.download_session.headers.update(BROWSER_HEADERS)
        self.DOWNLOAD_PERIOD = 1
        self.last_downloads = dict()

    def download(self, submission):
        """
        Download submitted media file with use of given HTTP referer.
        If main media file is not available try to download additional
        media file, e.g. preview image, if URL is presented.
        Complies chosen download frequency restrictions.

        Args:
            submission (SubmissionRL).

        Returns:
            bool: True if successfully downloaded and saved at least one file,
            False otherwise.
        """
        url_parts = urlparse(submission.url)
        domain = url_parts.netloc
        download_interval = (time.monotonic()
                             - self.last_downloads.get(domain, 0))
        if download_interval < self.DOWNLOAD_PERIOD:
            time.sleep(self.DOWNLOAD_PERIOD - download_interval)

        referer_header = ({"Referer": submission.url_referer}
                          if submission.url_referer is not None else {})
        try:
            response = self.download_session.get(submission.url,
                                                 headers=referer_header)
        except requests.exceptions.TooManyRedirects as error:
            print(error)
            return False
        finally:
            self.last_downloads[domain] = time.monotonic()

        request_succeed = False
        if response.status_code != 200:
            print(f"Fail, code: {response.status_code}, {response.url}")
            if submission.url_extra is not None:
                print(f"Try download extra {submission.url_extra}")
                response = self.download_session.get(submission.url_extra,
                                                     headers=referer_header)
                if response.status_code != 200:
                    print(f"Extra fail, code: {response.status_code}, {response.url}")
                else:
                    request_succeed = True
        else:
            request_succeed = True
        self.last_downloads[domain] = time.monotonic()

        if request_succeed:
            return self.__save_content(response)

        return False

    def __save_content(self, response):
        """
        Save content of downloaded media file under name specified in response URL.
        If file with same name exists append _copy to the name.

        Args:
            response (requests.Response): response with media file content.

        Returns:
            bool: True if saved successfully, False otherwise.
        """
        outfile_path = os.path.join(self.outdir_path,
                                    os.path.basename(urlparse(response.url).path))
        if os.path.exists(outfile_path):
            root, ext = os.path.splitext(outfile_path) 
            outfile_path = root + "_copy" + ext
        try:
            with open(outfile_path, "wb") as outf:
                outf.write(response.content)
        except FileNotFoundError:
            print(f"Failed to save {outfile_path}")
            return False

        return True


def print_causes(error):
    """Naive helper function used to traceback exception cause"""
    print("Error", type(error).__name__, "caused by:")
    error = error.__cause__
    while error is not None:
        print("^", type(error).__name__, error)
        error = error.__cause__


def dump_urls(subreddit_name, count, outfile_path=None):
    """
    Save URLs related to submitted media files into json file.

    Note: failed attempts to obtain direct URLs of media files
    from submitted URLs count separately in total as number of
    unresolved submissions. If the number exceeds a threshold,
    initially 2 * <given count of submissions>, traverse stops
    and given subreddit may be assumed to have to many text
    submissions or submitted indirect URLs mostly point to
    resources different from known: imgur.com, gfycat.com.
    Full list of known resources is defined by resolvers used.

    Args:
        subreddit_name (str): subreddit to scrape.

        count (int): count of submissions to dump, failures
        don't count.

        outfile_path (str): json extension is not required.
        If not specified everything is saved into <subreddit_name>.json.
    """
    if count <= 0:
        print(f"Submissions count must be > 0, given {count}")
        return

    image_extensions = ("jpg", "jpeg", "png", "webp", "gif")
    video_extensions = ("mp4", "webm")
    submission_iterator = SubmissionIterator(subreddit_name,
                                             image_extensions,
                                             video_extensions)
    submissions_left = count
    submissions_unresolved = 0
    MAX_UNRESOLVED = 2 * count
    submissions = list()
    with open(subreddit_name + ".json" if outfile_path is None else outfile_path, "w")\
            as outfile:
        while submissions_left > 0:
            print(f"To go: {submissions_left}",
                  f"Unresolved: {submissions_unresolved}")
            try:
                submitted_media_rl = next(submission_iterator)
                if submitted_media_rl is None:
                    print("Unexpected None submission")
                    continue
            except StopIteration as error:
                print_causes(error)
                break
            except SubmissionResolver.MediaIsUnavailable as error:
                print(error)
                submissions_unresolved += 1
                if submissions_unresolved < MAX_UNRESOLVED:
                    continue
                print("Break: too many unresolved submissions")
                break

            submissions.append(submitted_media_rl)
            submissions_left -= 1
        json.dump(submissions, outfile, default=SubmissionRL.to_json, indent=2)


def download_submissions(subreddit_name, count, outdir_path=None):
    """
    Download media files submitted in hot section of given subreddit.

    Note: fails count separately. Threshold of total number of failed
    attempts to obtain direct URLs of media files from submitted indirect
    URLs is initially equal to 2 * <given count of submissions>.
    Threshold of total number of download fails is initially equal to
    <given count of submissions> // 2.

    Args:
        subreddit (str).

        count (int): count of submitted media files to download.

        outdir_path (str): target directory. If None try to create
        directory with subreddit name.
    """
    if count <= 0:
        print(f"Submissions count must be > 0, given {count}")
        return

    if outdir_path is None:
        outdir_path = subreddit_name

    image_extensions = ("jpg", "jpeg", "png", "gif", "webp")
    video_extensions = ("mp4", "webm")
    submission_iterator = SubmissionIterator(subreddit_name,
                                             image_extensions,
                                             video_extensions)
    submission_downloader = SubmissionDownloader(outdir_path)
    submissions_left = count
    submissions_unresolved = 0
    MAX_UNRESOLVED = 2 * count
    download_fails = 0
    MAX_DOWNLOAD_FAILS = count // 2
    while submissions_left > 0:
        print(f"To go: {submissions_left}",
              f"Unresolved: {submissions_unresolved}",
              f"Download fails: {download_fails}")
        try:
            submitted_media_rl = next(submission_iterator)
            if submitted_media_rl is None:
                print("Unexpected None submission")
                continue
        except StopIteration as error:
            print_causes(error)
            break
        except SubmissionResolver.MediaIsUnavailable as error:
            print(error)
            submissions_unresolved += 1
            if submissions_unresolved < MAX_UNRESOLVED:
                continue
            print("Break: too many unresolved submissions")
            break

        print(f"Try download {submitted_media_rl.url}")
        if submission_downloader.download(submitted_media_rl):
            print("->Downloaded")
            submissions_left -= 1
        else:
            print("->Failed to download")
            download_fails += 1
            if download_fails >= MAX_DOWNLOAD_FAILS:
                print("Too many failed downloads")
                break


def main():
    parser = argparse.ArgumentParser(description="Dump hot submissions.")
    parser.add_argument(
        'type',
        choices=['media', 'url'],
        help="""Type of submission related information to dump.
             media -- submitted media files.
             url -- submission related URLs (as json): direct URL of submitted media,
                    extra direct URL of preview if any, HTTP referer to submitted media.
             """
    )
    parser.add_argument('subreddit', help="Name of target subreddit.")
    parser.add_argument('count', type=int, help="Count of submissions.")
    parser.add_argument(
        '-o',
        dest='path',
        help="""Dump destination.
             For URLs -- output file, if not specified data is saved into
             ./<subreddit name>.json.
             For media -- output directory, if not specified media files
             are saved into ./<subreddit name>/.
          """
    )
    args = parser.parse_args()
    if args.type == "url":
        dump_urls(args.subreddit, args.count, args.path)
    elif args.type == "media":
        download_submissions(args.subreddit, args.count, args.path)
    else:
        print(f"Unexpected type: {args.type}")
        parser.print_help()
        return


if __name__ == "__main__":
    main()
