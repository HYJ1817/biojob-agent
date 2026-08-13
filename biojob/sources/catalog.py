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


def _bing_feed(query: str) -> str:
    return f"https://www.bing.com/search?{urlencode({'format': 'rss', 'q': query})}"


def _search(source_id: str, name: str, label: str, query: str) -> DefaultSource:
    return DefaultSource(
        source_id=source_id,
        name=name,
        adapter_type="search_feed",
        url=_bing_feed(query),
        enabled=True,
        description=f"公开搜索订阅：{label}；结果进入候选池后需打开原页面核验。",
        query_label=label,
        reviewed_hosts=("www.bing.com",),
    )


def _portal(
    source_id: str, name: str, company_name: str, url: str
) -> DefaultSource:
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
        "2027 校园招聘 本科 生物制药 生产技术 工艺工程 生物工艺",
    ),
    _search(
        "search-quality",
        "质量岗位发现",
        "QA QC",
        "2027 校园招聘 本科 生物制药 QA QC GMP 质量管理",
    ),
    _search(
        "search-cell-lab",
        "细胞与实验岗位发现",
        "细胞实验",
        "2027 校园招聘 本科 细胞培养 实验员 生物分析 研发助理",
    ),
    _search(
        "search-fermentation-microbiology",
        "发酵与微生物岗位发现",
        "发酵微生物",
        "2027 校园招聘 本科 发酵工程 微生物培养 菌株筛选",
    ),
    _search(
        "search-shandong",
        "山东生物医药岗位发现",
        "山东",
        "2027 校园招聘 本科 生物制药 山东 济南 青岛 烟台 济宁 QA QC 工艺",
    ),
    _search(
        "search-major-cities",
        "周边与大城市岗位发现",
        "大城市",
        "2027 校园招聘 本科 生物医药 北京 天津 上海 江苏 浙江 工艺 QA QC",
    ),
    _search(
        "search-university-careers",
        "高校就业网岗位发现",
        "高校就业网",
        "site:edu.cn 2027 校园招聘 生物制药 本科 工艺 QA QC 实验员",
    ),
    _search(
        "search-target-companies",
        "重点药企岗位发现",
        "重点企业",
        "2027 校园招聘 齐鲁制药 荣昌生物 绿叶制药 华熙生物 恒瑞 鲁南",
    ),
    _search(
        "search-cro-cdmo",
        "CRO/CDMO岗位发现",
        "CRO CDMO",
        "2027 校园招聘 本科 康龙化成 药明康德 凯莱英 生物 工艺 实验",
    ),
    _search(
        "search-internship",
        "相关实习岗位发现",
        "短期实习",
        "2027 生物工程 本科 实习 细胞培养 QA QC 发酵 山东",
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
