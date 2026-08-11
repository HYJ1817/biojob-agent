from __future__ import annotations

import httpx
import pytest

from biojob.domain import RawJob
from biojob.sources import (
    FeedJobAdapter,
    ManualJobAdapter,
    PublicPageAdapter,
    SafeHttpClient,
    SourceConfigurationError,
    SourceFetchError,
    SourceSecurityError,
)


PUBLIC_IP = "93.184.216.34"


def client_for(handler, *, resolver=None, max_body_bytes=2 * 1024 * 1024):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    safe_client = SafeHttpClient(
        client=http_client,
        resolver=resolver or (lambda _hostname: [PUBLIC_IP]),
        max_body_bytes=max_body_bytes,
    )
    return safe_client, http_client


def test_manual_adapter_converts_structured_jobs_without_network():
    adapter = ManualJobAdapter()

    jobs = adapter.fetch({
        "jobs": [
            {
                "company_name": "齐鲁制药",
                "title": "生物工艺工程师",
                "detail_url": "https://example.test/jobs/1",
                "city": "济南",
                "jd_text": "本科应届，发酵生产。",
            }
        ]
    })

    assert jobs == [
        RawJob(
            company_name="齐鲁制药",
            title="生物工艺工程师",
            detail_url="https://example.test/jobs/1",
            city="济南",
            jd_text="本科应届，发酵生产。",
        )
    ]
    assert adapter.adapter_type == "manual"


@pytest.mark.parametrize("jobs", [None, "not-a-list", ["not-an-object"]])
def test_manual_adapter_rejects_malformed_config(jobs):
    with pytest.raises(SourceConfigurationError):
        ManualJobAdapter().fetch({"jobs": jobs})


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@example.test/jobs",
        "http://127.0.0.1/jobs",
        "http://[::1]/jobs",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_safe_http_rejects_non_public_destinations_before_transport(url):
    requests = []
    safe, raw_client = client_for(lambda request: requests.append(request))
    try:
        with pytest.raises(SourceSecurityError):
            safe.get(url)
    finally:
        raw_client.close()
    assert requests == []


def test_safe_http_rejects_hostname_resolving_to_private_address():
    safe, raw_client = client_for(
        lambda _request: httpx.Response(200, text="no"),
        resolver=lambda _hostname: ["10.0.0.7"],
    )
    try:
        with pytest.raises(SourceSecurityError, match="public"):
            safe.get("https://jobs.example.test/")
    finally:
        raw_client.close()


def test_safe_http_revalidates_redirect_and_blocks_dns_rebinding():
    resolutions = iter([[PUBLIC_IP], ["127.0.0.1"]])

    def resolver(_hostname):
        return next(resolutions)

    def handler(request):
        return httpx.Response(302, headers={"location": str(request.url)})

    safe, raw_client = client_for(handler, resolver=resolver)
    try:
        with pytest.raises(SourceSecurityError):
            safe.get("https://jobs.example.test/start")
    finally:
        raw_client.close()


def test_safe_http_follows_bounded_redirects_and_reports_final_url():
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            content="招聘岗位".encode(),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    safe, raw_client = client_for(handler)
    try:
        response = safe.get("https://jobs.example.test/start")
    finally:
        raw_client.close()

    assert response.url == "https://jobs.example.test/final"
    assert response.content_type == "text/html"
    assert response.text == "招聘岗位"


def test_safe_http_rejects_redirect_limit_body_limit_and_timeout():
    def looping(_request):
        return httpx.Response(302, headers={"location": "/again"})

    safe, raw_client = client_for(looping)
    try:
        with pytest.raises(SourceFetchError, match="redirect"):
            safe.get("https://jobs.example.test/again")
    finally:
        raw_client.close()

    safe, raw_client = client_for(
        lambda _request: httpx.Response(200, content=b"12345678901"),
        max_body_bytes=10,
    )
    try:
        with pytest.raises(SourceFetchError, match="large"):
            safe.get("https://jobs.example.test/large")
    finally:
        raw_client.close()

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    safe, raw_client = client_for(timeout)
    try:
        with pytest.raises(SourceFetchError, match="failed"):
            safe.get("https://jobs.example.test/slow")
    finally:
        raw_client.close()


def test_safe_http_sends_honest_user_agent():
    seen = {}

    def handler(request):
        seen["user_agent"] = request.headers["user-agent"]
        return httpx.Response(200, text="ok")

    safe, raw_client = client_for(handler)
    try:
        safe.get("https://jobs.example.test/")
    finally:
        raw_client.close()

    assert seen["user_agent"].startswith("BioJob-Agent/")


def test_public_page_parses_schema_org_jobposting():
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      "title": "细胞培养技术员",
      "hiringOrganization": {"@type": "Organization", "name": "荣昌生物"},
      "jobLocation": {"address": {"addressLocality": "烟台"}},
      "description": "<p>本科，负责细胞培养与GMP记录。</p>",
      "datePosted": "2026-08-10",
      "validThrough": "2026-09-10",
      "url": "/jobs/cell-1"
    }
    </script></head><body><script>ignore()</script></body></html>
    """
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200, text=html, headers={"content-type": "text/html"}
        )
    )
    try:
        jobs = PublicPageAdapter(safe).fetch({
            "url": "https://jobs.example.test/careers"
        })
    finally:
        raw_client.close()

    assert jobs == [
        RawJob(
            company_name="荣昌生物",
            title="细胞培养技术员",
            detail_url="https://jobs.example.test/jobs/cell-1",
            city="烟台",
            jd_text="本科，负责细胞培养与GMP记录。",
            published_at="2026-08-10",
            deadline_at="2026-09-10",
        )
    ]


def test_public_page_accepts_only_signalled_job_anchors():
    html = """
    <main>
      <p>我们是一家长期深耕生物医药的企业，欢迎了解公司。</p>
      <a href="/about">公司介绍</a>
      <a href="/jobs/qc-1">招聘：QC实验员</a>
      <a href="javascript:alert(1)">招聘：错误链接</a>
      <a href="/news/1">招聘活动新闻</a>
    </main>
    """
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200, text=html, headers={"content-type": "text/html"}
        )
    )
    try:
        jobs = PublicPageAdapter(safe).fetch({
            "url": "https://jobs.example.test/careers",
            "company_name": "华熙生物",
        })
    finally:
        raw_client.close()

    assert [job.title for job in jobs] == ["招聘：QC实验员"]
    assert jobs[0].detail_url == "https://jobs.example.test/jobs/qc-1"
    assert jobs[0].company_name == "华熙生物"


def test_public_page_generic_landing_copy_creates_no_candidate():
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200,
            text="<html><p>加入我们，共创未来。</p></html>",
            headers={"content-type": "text/html"},
        )
    )
    try:
        assert (
            PublicPageAdapter(safe).fetch({
                "url": "https://jobs.example.test/careers",
                "company_name": "测试企业",
            })
            == []
        )
    finally:
        raw_client.close()


def test_public_page_rejects_non_html_response():
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200, content=b"%PDF", headers={"content-type": "application/pdf"}
        )
    )
    try:
        with pytest.raises(SourceFetchError, match="HTML"):
            PublicPageAdapter(safe).fetch({"url": "https://jobs.example.test/a"})
    finally:
        raw_client.close()


def test_feed_adapter_parses_rss_and_atom_entries():
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>发酵生产技术员</title>
      <link>https://jobs.example.test/jobs/fermentation</link>
      <description><![CDATA[<p>本科应届，负责发酵生产。</p>]]></description>
      <pubDate>2026-08-12</pubDate>
    </item></channel></rss>"""
    atom = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>QA专员</title>
      <link href="https://jobs.example.test/jobs/qa" />
      <summary>本科，负责GMP质量体系。</summary>
      <updated>2026-08-12T08:00:00Z</updated>
    </entry></feed>"""

    def handler(request):
        body = rss if request.url.path == "/rss" else atom
        return httpx.Response(
            200, text=body, headers={"content-type": "application/xml"}
        )

    safe, raw_client = client_for(handler)
    adapter = FeedJobAdapter(safe)
    try:
        rss_jobs = adapter.fetch({
            "url": "https://jobs.example.test/rss",
            "company_name": "齐鲁制药",
        })
        atom_jobs = adapter.fetch({
            "url": "https://jobs.example.test/atom",
            "company_name": "鲁南制药",
        })
    finally:
        raw_client.close()

    assert rss_jobs[0].title == "发酵生产技术员"
    assert rss_jobs[0].jd_text == "本科应届，负责发酵生产。"
    assert rss_jobs[0].published_at == "2026-08-12"
    assert atom_jobs[0].title == "QA专员"
    assert atom_jobs[0].published_at == "2026-08-12T08:00:00Z"


@pytest.mark.parametrize(
    "xml",
    [
        '<!DOCTYPE rss SYSTEM "file:///etc/passwd"><rss/>',
        '<!ENTITY xxe SYSTEM "file:///etc/passwd"><rss/>',
    ],
)
def test_feed_rejects_dtd_and_entities(xml):
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200, text=xml, headers={"content-type": "application/xml"}
        )
    )
    try:
        with pytest.raises(SourceSecurityError, match="DTD|entity"):
            FeedJobAdapter(safe).fetch({
                "url": "https://jobs.example.test/rss",
                "company_name": "测试",
            })
    finally:
        raw_client.close()


def test_feed_requires_company_and_skips_invalid_entries():
    xml = """<rss><channel>
      <item><title>Missing link</title></item>
      <item><link>https://jobs.example.test/jobs/missing-title</link></item>
    </channel></rss>"""
    safe, raw_client = client_for(
        lambda _request: httpx.Response(
            200, text=xml, headers={"content-type": "application/rss+xml"}
        )
    )
    try:
        with pytest.raises(SourceConfigurationError):
            FeedJobAdapter(safe).fetch({"url": "https://jobs.example.test/rss"})
        assert (
            FeedJobAdapter(safe).fetch({
                "url": "https://jobs.example.test/rss",
                "company_name": "测试",
            })
            == []
        )
    finally:
        raw_client.close()
