"""wappalyzer — 基于 Wappalyzer 规则的深度 Web 技术栈指纹识别。

镜像 TS server/src/modules/tools/security/wappalyzer.tool.ts（与已有 tech_detect 并存，TS 亦两者并存）。
"""
import re
from typing import Any, Dict, List, Pattern

import httpx

from tools.base import BaseTool, ToolResult


class _TechRule:
    __slots__ = ("name", "category", "headers", "cookies", "html", "scripts", "meta")

    def __init__(self, name, category, headers=None, cookies=None, html=None, scripts=None, meta=None):
        self.name = name
        self.category = category
        self.headers: Dict[str, Pattern] = headers or {}
        self.cookies: Dict[str, Pattern] = cookies or {}
        self.html: List[Pattern] = html or []
        self.scripts: List[Pattern] = scripts or []
        self.meta: Dict[str, Pattern] = meta or {}


RULES: List[_TechRule] = [
    # Web Servers
    _TechRule("Nginx", "web-server", headers={"server": re.compile(r"nginx", re.I)}),
    _TechRule("Apache", "web-server", headers={"server": re.compile(r"apache", re.I)}),
    _TechRule("IIS", "web-server", headers={"server": re.compile(r"microsoft-iis", re.I)}),
    _TechRule("LiteSpeed", "web-server", headers={"server": re.compile(r"litespeed", re.I)}),
    _TechRule("Caddy", "web-server", headers={"server": re.compile(r"caddy", re.I)}),
    # Languages / Runtimes
    _TechRule("PHP", "language", headers={"x-powered-by": re.compile(r"php", re.I)},
              cookies={"PHPSESSID": re.compile(r".*")}),
    _TechRule("ASP.NET", "language",
              headers={"x-powered-by": re.compile(r"asp\.net", re.I), "x-aspnet-version": re.compile(r".*")},
              cookies={"ASP.NET_SessionId": re.compile(r".*")}),
    _TechRule("Express", "framework", headers={"x-powered-by": re.compile(r"express", re.I)}),
    _TechRule("Java", "language", headers={"x-powered-by": re.compile(r"servlet|jsp|tomcat", re.I)},
              cookies={"JSESSIONID": re.compile(r".*")}),
    _TechRule("Python", "language", headers={"server": re.compile(r"python|gunicorn|uvicorn|waitress", re.I)}),
    # JS Frameworks
    _TechRule("React", "js-framework", html=[re.compile(r"data-reactroot|_react|__NEXT_DATA__")],
              scripts=[re.compile(r"react(?:\.production|\.development)")]),
    _TechRule("Next.js", "js-framework", html=[re.compile(r"__NEXT_DATA__|_next/static")],
              headers={"x-powered-by": re.compile(r"next\.js", re.I)}),
    _TechRule("Vue.js", "js-framework", html=[re.compile(r"data-v-[a-f0-9]|__vue__|Vue\.config")],
              scripts=[re.compile(r"vue(?:\.runtime)?(?:\.min)?\.js")]),
    _TechRule("Nuxt.js", "js-framework", html=[re.compile(r"__NUXT__|_nuxt/")]),
    _TechRule("Angular", "js-framework", html=[re.compile(r"ng-version|ng-app|angular\.(?:min\.)?js")]),
    _TechRule("Svelte", "js-framework", html=[re.compile(r"svelte-[a-z0-9]|__svelte")]),
    # CMS
    _TechRule("WordPress", "cms", html=[re.compile(r"wp-content|wp-includes|wp-json")],
              meta={"generator": re.compile(r"wordpress", re.I)}),
    _TechRule("Drupal", "cms", html=[re.compile(r"sites/default/files|drupal\.js")],
              headers={"x-drupal-cache": re.compile(r".*"), "x-generator": re.compile(r"drupal", re.I)}),
    _TechRule("Joomla", "cms", html=[re.compile(r"/media/jui/|com_content")],
              meta={"generator": re.compile(r"joomla", re.I)}),
    _TechRule("Ghost", "cms", html=[re.compile(r"ghost-(?:url|api)")],
              meta={"generator": re.compile(r"ghost", re.I)}),
    _TechRule("Shopify", "ecommerce", html=[re.compile(r"cdn\.shopify\.com|Shopify\.theme")]),
    _TechRule("Magento", "ecommerce", html=[re.compile(r"mage/cookies|Magento_Ui")],
              cookies={"frontend": re.compile(r".*")}),
    # CDN / Proxy
    _TechRule("Cloudflare", "cdn", headers={"server": re.compile(r"cloudflare", re.I), "cf-ray": re.compile(r".*")}),
    _TechRule("Fastly", "cdn", headers={"x-served-by": re.compile(r"cache-", re.I), "via": re.compile(r"varnish", re.I)}),
    _TechRule("AWS CloudFront", "cdn", headers={"x-amz-cf-id": re.compile(r".*"), "via": re.compile(r"cloudfront", re.I)}),
    _TechRule("Vercel", "paas", headers={"x-vercel-id": re.compile(r".*"), "server": re.compile(r"vercel", re.I)}),
    _TechRule("Netlify", "paas", headers={"server": re.compile(r"netlify", re.I), "x-nf-request-id": re.compile(r".*")}),
    # Security
    _TechRule("ModSecurity", "waf", headers={"server": re.compile(r"mod_security|modsecurity", re.I)}),
    _TechRule("AWS WAF", "waf", headers={"x-amzn-waf": re.compile(r".*")}),
    # Analytics
    _TechRule("Google Analytics", "analytics",
              html=[re.compile(r"google-analytics\.com/analytics|gtag\(|UA-\d{4,10}-\d{1,4}")]),
    _TechRule("Google Tag Manager", "analytics", html=[re.compile(r"googletagmanager\.com/gtm")]),
    # Misc
    _TechRule("jQuery", "js-library", scripts=[re.compile(r"jquery(?:\.min)?\.js")]),
    _TechRule("Bootstrap", "css-framework", html=[re.compile(r"bootstrap(?:\.min)?\.(?:css|js)")]),
    _TechRule("Tailwind CSS", "css-framework", html=[re.compile(r"tailwindcss|tailwind\.min\.css")]),
]

META_TAG_RE = re.compile(
    r"<meta[^>]+name=[\"'](?P<name>[^\"']+)[\"'][^>]+content=[\"'](?P<content>[^\"']*)[\"']",
    re.IGNORECASE,
)


class WappalyzerTool(BaseTool):
    def __init__(self):
        super().__init__(
            name="wappalyzer",
            description="深度技术指纹 — 基于 Wappalyzer 规则识别 Web 技术栈",
        )

    async def execute(self, url: str = "", timeout: int = 15, **kwargs) -> ToolResult:
        url = (url or "").strip()
        if not url:
            return ToolResult(success=False, result=None, error="缺少必要参数: url")

        timeout_s = min(int(timeout or 15), 30)
        try:
            async with httpx.AsyncClient(
                timeout=timeout_s,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; secbot/1.0)"},
            ) as client:
                resp = await client.get(url)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            cookies: Dict[str, str] = {}
            for part in resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []:
                m = re.match(r"\s*([^=]+)=([^;]*)", part)
                if m:
                    cookies[m.group(1).strip()] = m.group(2).strip()
            body = resp.text
            detected = self._detect(headers, cookies, body)
            return ToolResult(
                success=True,
                result={
                    "url": url,
                    "status": resp.status_code,
                    "technologies_count": len(detected),
                    "technologies": detected,
                },
            )
        except Exception as e:
            return ToolResult(success=False, result=None, error=f"指纹识别失败: {e}")

    def _detect(
        self, headers: Dict[str, str], cookies: Dict[str, str], body: str
    ) -> List[Dict[str, str]]:
        found: List[Dict[str, str]] = []
        body_slice = body[:200_000]
        metas: Dict[str, str] = {}
        for m in META_TAG_RE.finditer(body_slice):
            metas[m.group("name").lower()] = m.group("content")

        for rule in RULES:
            matched = False
            for h, pattern in rule.headers.items():
                if h in headers and pattern.search(headers[h]):
                    matched = True
                    break
            if not matched:
                for c, pattern in rule.cookies.items():
                    if c in cookies and pattern.search(cookies[c]):
                        matched = True
                        break
            if not matched:
                for pattern in rule.html + rule.scripts:
                    if pattern.search(body_slice):
                        matched = True
                        break
            if not matched:
                for name, pattern in rule.meta.items():
                    if name in metas and pattern.search(metas[name]):
                        matched = True
                        break
            if matched:
                found.append({"name": rule.name, "category": rule.category, "confidence": "certain" if rule.headers or rule.cookies else "probable"})
        return found

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "timeout": {"type": "integer", "description": "超时秒数（默认 15）"},
                },
                "required": ["url"],
            },
        }
