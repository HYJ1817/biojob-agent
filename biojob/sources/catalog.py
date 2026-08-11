"""Reviewed default source catalog and adapter registry."""

from __future__ import annotations

from dataclasses import dataclass

from biojob.sources.base import JobSourceAdapter
from biojob.sources.feed import FeedJobAdapter
from biojob.sources.http import SafeHttpClient
from biojob.sources.manual import ManualJobAdapter
from biojob.sources.public_page import PublicPageAdapter


@dataclass(frozen=True)
class DefaultSource:
    source_id: str
    name: str
    adapter_type: str
    url: str
    company_name: str
    enabled: bool
    description: str

    @property
    def config(self) -> dict[str, str]:
        return {"url": self.url, "company_name": self.company_name}


DEFAULT_SOURCES = (
    DefaultSource(
        "default-qilu",
        "齐鲁制药招聘",
        "public_page",
        "https://www.qilu-pharma.com/position.html",
        "齐鲁制药",
        True,
        "齐鲁制药官方招聘入口；页面变化时可能返回零条。",
    ),
    DefaultSource(
        "default-remegen",
        "荣昌生物招聘",
        "public_page",
        "https://www.remegen.cn/index.php?cid=45&v=listing",
        "荣昌生物",
        True,
        "荣昌生物官方招聘入口；动态跳转时可能返回零条。",
    ),
    DefaultSource(
        "default-luye",
        "绿叶制药招聘",
        "public_page",
        "https://www.luye.cn/lvye/joinUs.php",
        "绿叶制药",
        True,
        "绿叶制药官方招聘入口；页面变化时可能返回零条。",
    ),
    DefaultSource(
        "default-bloomage",
        "华熙生物招聘",
        "public_page",
        "https://www.hotjob.cn/wt/HXSW/web/index?brandCode=1",
        "华熙生物",
        True,
        "华熙生物公开招聘入口；动态/WAF 页面可能返回零条或失败。",
    ),
    DefaultSource(
        "default-pharmaron-campus",
        "康龙化成校园招聘",
        "public_page",
        "https://app.mokahr.com/m/campus-recruitment/pharmaron/74162",
        "康龙化成",
        True,
        "康龙化成校园招聘入口；动态/WAF 页面可能返回零条或失败。",
    ),
    DefaultSource(
        "default-public-search-experimental",
        "公开搜索发现（实验）",
        "feed",
        "https://www.bing.com/search?format=rss&q=生物制药+校园招聘+QA+QC+工艺",
        "公开搜索结果",
        False,
        "实验性公开搜索 RSS，默认关闭；结果质量与可用性不作保证。",
    ),
)


def default_adapter_registry() -> dict[str, JobSourceAdapter]:
    http = SafeHttpClient()
    adapters: tuple[JobSourceAdapter, ...] = (
        ManualJobAdapter(),
        PublicPageAdapter(http),
        FeedJobAdapter(http),
    )
    return {adapter.adapter_type: adapter for adapter in adapters}
