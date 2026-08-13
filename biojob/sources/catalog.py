"""Reviewed default source catalog and adapter registry."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from biojob.sources.base import JobSourceAdapter
from biojob.sources.feed import FeedJobAdapter
from biojob.sources.http import SafeHttpClient
from biojob.sources.manual import ManualJobAdapter
from biojob.sources.public_page import PublicPageAdapter
from biojob.sources.search_feed import SearchFeedAdapter


@dataclass(frozen=True)
class DefaultSource:
    source_id: str
    name: str
    adapter_type: str
    url: str
    enabled: bool
    description: str
    company_name: str = ""
    query_label: str = ""
    reviewed_hosts: tuple[str, ...] = ()

    @property
    def config(self) -> dict[str, str]:
        result = {"url": self.url}
        if self.company_name:
            result["company_name"] = self.company_name
        if self.query_label:
            result["query_label"] = self.query_label
        return result


def _search_page(query: str) -> str:
    return f"https://www.so.com/s?{urlencode({'q': query})}"


def _search(source_id: str, name: str, label: str, query: str) -> DefaultSource:
    return DefaultSource(
        source_id=source_id,
        name=name,
        adapter_type="search_feed",
        url=_search_page(query),
        enabled=True,
        description=f"公开搜索订阅：{label}；结果进入候选池后需打开原页面核验。",
        query_label=label,
        reviewed_hosts=("www.so.com",),
    )


def _portal(source_id: str, name: str, company_name: str, url: str) -> DefaultSource:
    hostname = urlsplit(url).hostname
    return DefaultSource(
        source_id=source_id,
        name=name,
        adapter_type="portal",
        url=url,
        enabled=False,
        description="企业官方招聘入口；点击打开并核验岗位，不执行自动抓取。",
        company_name=company_name,
        reviewed_hosts=(hostname,) if hostname else (),
    )


DEFAULT_SOURCES = (
    _search(
        "search-production-process",
        "生产与工艺岗位发现",
        "生产工艺",
        "生物制药 工艺 招聘",
    ),
    _search(
        "search-quality",
        "质量岗位发现",
        "QA QC",
        "QA QC 制药 招聘",
    ),
    _search(
        "search-cell-lab",
        "细胞与实验岗位发现",
        "细胞实验",
        "细胞培养 实验员 招聘",
    ),
    _search(
        "search-fermentation-microbiology",
        "发酵与微生物岗位发现",
        "发酵微生物",
        "发酵工程 微生物 招聘",
    ),
    _search(
        "search-shandong",
        "山东生物医药岗位发现",
        "山东",
        "山东 生物制药 招聘",
    ),
    _search(
        "search-major-cities",
        "周边与大城市岗位发现",
        "大城市",
        "生物医药 应届生 北京 上海 江苏 浙江 招聘",
    ),
    _search(
        "search-university-careers",
        "高校就业网岗位发现",
        "高校就业网",
        "site:edu.cn 生物制药 校园招聘",
    ),
    _search(
        "search-target-companies",
        "重点药企岗位发现",
        "重点企业",
        "齐鲁制药 荣昌生物 绿叶制药 华熙生物 招聘",
    ),
    _search(
        "search-cro-cdmo",
        "CRO/CDMO岗位发现",
        "CRO CDMO",
        "康龙化成 药明康德 凯莱英 生物 招聘",
    ),
    _search(
        "search-internship",
        "相关实习岗位发现",
        "短期实习",
        "生物工程 生物制药 实习 招聘",
    ),
    _portal(
        "default-qilu",
        "齐鲁制药招聘",
        "齐鲁制药",
        "https://www.qilu-pharma.com/position.html",
    ),
    _portal(
        "default-remegen",
        "荣昌生物招聘",
        "荣昌生物",
        "https://www.remegen.cn/index.php?cid=45&v=listing",
    ),
    _portal(
        "default-luye",
        "绿叶制药招聘",
        "绿叶制药",
        "https://www.luye.cn/lvye/joinUs.php",
    ),
    _portal(
        "default-bloomage",
        "华熙生物招聘",
        "华熙生物",
        "https://www.hotjob.cn/wt/HXSW/web/index?brandCode=1",
    ),
    _portal(
        "default-pharmaron-campus",
        "康龙化成校园招聘",
        "康龙化成",
        "https://app.mokahr.com/m/campus-recruitment/pharmaron/74162",
    ),
    _portal(
        "portal-wuxi-apptec",
        "药明康德招聘",
        "药明康德",
        "https://careers.wuxiapptec.com/",
    ),
    _portal(
        "portal-asymchem",
        "凯莱英招聘",
        "凯莱英",
        "https://www.asymchem.com/cn/careers",
    ),
    _portal(
        "portal-hengrui",
        "恒瑞医药招聘",
        "恒瑞医药",
        "https://www.hrs.com.cn/join",
    ),
    _portal(
        "portal-lunan",
        "鲁南制药招聘",
        "鲁南制药",
        "https://www.lunan.com.cn/join",
    ),
    _portal(
        "portal-lukang",
        "鲁抗医药招聘",
        "鲁抗医药",
        "https://www.lkpc.com/rczp",
    ),
)


_REVIEWED_HOSTS = {
    source.source_id: frozenset(source.reviewed_hosts)
    for source in DEFAULT_SOURCES
    if source.reviewed_hosts
}


def reviewed_hosts_for_source(source_id: str) -> frozenset[str]:
    return _REVIEWED_HOSTS.get(source_id, frozenset())


def default_adapter_registry() -> dict[str, JobSourceAdapter]:
    http = SafeHttpClient()
    adapters: tuple[JobSourceAdapter, ...] = (
        ManualJobAdapter(),
        PublicPageAdapter(http),
        FeedJobAdapter(http),
        SearchFeedAdapter(http),
    )
    return {adapter.adapter_type: adapter for adapter in adapters}
