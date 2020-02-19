"""Shared module with class representing reddit submission."""

class Submission:
    """Encapsulates reddit submission related information."""

    def __init__(self, *, url=None, referer=None):
        """
        url - submission url,
        referer - http request referer value used to mimic
            legal browsing. May be changed after resolving submission
            url to external resource.
        """
        self.url = url
        self.referer = referer

    def __repr__(self):
        return f"url={self.url}; referer={self.referer}"

    def __str__(self):
        return self.__repr__()

    @staticmethod
    def to_json(instance):
        """To make class json serializable."""
        return {"url": instance.url, "ref": instance.referer}
