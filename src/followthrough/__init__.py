"""Follow-Through: an OpenMinion agent for maintainer follow-ups."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("followthrough")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0"
