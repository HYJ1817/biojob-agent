"""Public source-adapter API for BioJob."""

from biojob.sources.base import (
    JobSourceAdapter,
    SourceAdapterError,
    SourceConfigurationError,
    SourceFetchError,
    SourceSecurityError,
)
from biojob.sources.feed import FeedJobAdapter
from biojob.sources.http import SafeHttpClient, SafeHttpResponse
from biojob.sources.manual import ManualJobAdapter
from biojob.sources.public_page import PublicPageAdapter

__all__ = [
    "FeedJobAdapter",
    "JobSourceAdapter",
    "ManualJobAdapter",
    "PublicPageAdapter",
    "SafeHttpClient",
    "SafeHttpResponse",
    "SourceAdapterError",
    "SourceConfigurationError",
    "SourceFetchError",
    "SourceSecurityError",
]
