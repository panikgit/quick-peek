"""Class representing reddit non-API submission."""

class SubmissionRL:
    """Resource locator of reddit submission
    
    Args:
        url (str): URL of submission may be indirect.

        url_extra (str): URL of supplemental media may be None.

        url_referer (str): HTTP referer.

    Attributes:
        url (str): URL of submitted media may be either direct initially
            or later updated with direct one.
        
        url_extra (str): URL of supplemental media, e.g. first
            image of album, initially may be None.

        url_referer (str): HTTP referer value used to mimic legal browsing.
            Should be updated appropriately.
    """

    def __init__(self, *, url=None, url_extra=None, url_referer=None):
        self.url = url
        self.url_extra = url_extra
        self.url_referer = url_referer

    def __repr__(self):
        return f"url={self.url}"\
               f"\nextra={self.url_extra}"\
               f"\nreferer={self.url_referer}"

    def __str__(self):
        return self.__repr__()

    @staticmethod
    def to_json(submission_rl):
        """To make class json serializable"""
        return {"url": submission_rl.url,
                "extra": submission_rl.url_extra,
                "referer": submission_rl.url_referer
               }
