# quick-peek
Subreddit hot media submissions viewer

Click through hot section of chosen subreddit, view submitted images (except albums), watch videos.
Currently non-API page parsing based access to media resources is implemented.
Parses old.reddit.com, imgur.com, gfycat.com to obtain direct URLs of submitted files.
Supported media formats: jpg, jpeg, png, mp4, webm.
Format determination is implemented trivially by checking of file name extension in direct URL.

Supplied with standalone dump script.
Provided dump functions are used for downloading or obtaining direct URLs of submitted media files
and were designed primarily for testing of underlying non-API web access functionality.

Requires | Tested version
---------| -------------
Python3 | 3.6
PyQt5 | 5.10
requests | 2.22
beautifulsoup4 | 4.8
lxml | 4.5
python-vlc | 3.0
