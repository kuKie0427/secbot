"""Phase 1 新工具单测：参数校验失败路径 + 不依赖外网的 happy path。"""
import asyncio

import pytest

from tools.pentest.security.nmap_scan_tool import NmapScanTool, _parse_xml
from tools.pentest.security.nuclei_scan_tool import NucleiScanTool, parse_json_lines
from tools.pentest.security.nikto_scan_tool import NiktoScanTool, _parse_output as nikto_parse
from tools.pentest.security.ffuf_scan_tool import FfufScanTool
from tools.pentest.security.screenshot_tool import ScreenshotTool
from tools.pentest.security.code_audit_tool import CodeAuditTool, RULES
from tools.pentest.security.credential_spray_tool import CredentialSprayTool, _parse_target
from tools.pentest.network.dns_zone_transfer_tool import DnsZoneTransferTool
from tools.pentest.network.cidr_scan_tool import CidrScanTool
from tools.pentest.network.wifi_scan_tool import WifiScanTool, _parse_macos
from tools.pentest.network.sniff_tool import SniffTool, _parse as sniff_parse
from tools.protocol.ssh_probe_tool import SshProbeTool, _analyze_banner
from tools.protocol.ftp_probe_tool import FtpProbeTool, _analyze_banner as ftp_analyze
from tools.protocol.email_enum_tool import EmailEnumTool
from tools.protocol.ldap_enum_tool import LdapEnumTool
from tools.cloud.cloud_bucket_enum_tool import CloudBucketEnumTool
from tools.defense.container_escape_check_tool import ContainerEscapeCheckTool
from tools.offense.control.install_tool import InstallToolTool, INSTALL_REGISTRY
from tools.web.wappalyzer_tool import WappalyzerTool
from tools.web.api_schema_scan_tool import ApiSchemaScanTool


def run(coro):
    return asyncio.run(coro)


class TestParamValidation:
    """每个新工具：缺必填参数 → 结构化错误（非异常崩溃）。"""

    @pytest.mark.parametrize("tool,kwargs", [
        (NmapScanTool(), {}),
        (NucleiScanTool(), {}),
        (NiktoScanTool(), {}),
        (FfufScanTool(), {}),
        (ScreenshotTool(), {}),
        (CodeAuditTool(), {}),
        (CredentialSprayTool(), {}),
        (DnsZoneTransferTool(), {}),
        (CidrScanTool(), {}),
        (SshProbeTool(), {}),
        (FtpProbeTool(), {}),
        (EmailEnumTool(), {}),
        (LdapEnumTool(), {}),
        (CloudBucketEnumTool(), {}),
        (WappalyzerTool(), {}),
        (ApiSchemaScanTool(), {}),
    ])
    def test_missing_required_param(self, tool, kwargs):
        result = run(tool.execute(**kwargs))
        assert result.success is False
        assert result.error and "缺少" in result.error

    def test_screenshot_rejects_non_http(self):
        result = run(ScreenshotTool().execute(url="ftp://x"))
        assert result.success is False

    def test_cidr_invalid(self):
        result = run(CidrScanTool().execute(cidr="999.0.0.0/24"))
        assert result.success is False

    def test_install_tool_rejects_unknown(self):
        result = run(InstallToolTool().execute(tool="nmap-evil"))
        assert result.success is False
        assert "不支持自动安装" in result.error

    def test_install_tool_whitelist_matches_ts(self):
        expected = {
            "nuclei", "nikto", "nmap", "ffuf", "tshark", "traceroute", "sqlmap",
            "hydra", "subfinder", "httpx", "gobuster", "amass", "masscan",
            "whatweb", "wpscan", "testssl", "feroxbuster",
        }
        assert expected == set(INSTALL_REGISTRY.keys())


class TestParsers:
    """输出解析器 happy path（fixture 字符串，无网络）。"""

    def test_nmap_xml_parse(self):
        xml = """<nmaprun><host><address addr="10.0.0.1"/>
        <ports><port protocol="tcp" portid="80"><state state="open"/>
        <service name="http" version="nginx 1.24"/></port></ports></host></nmaprun>"""
        parsed = _parse_xml(xml)
        assert parsed["hosts"][0]["ip"] == "10.0.0.1"
        assert parsed["hosts"][0]["open_ports"][0]["port"] == 80

    def test_nuclei_jsonl_parse(self):
        lines = '{"template-id":"cve-x","info":{"name":"Test","severity":"high"},"host":"a.com","matched-at":"http://a.com"}'
        findings = parse_json_lines(lines)
        assert findings[0]["template_id"] == "cve-x"
        assert findings[0]["severity"] == "high"

    def test_nikto_json_parse(self):
        out = '{"vulnerabilities":[{"id":"OSVDB-1","msg":"x","url":"/"}]}'
        assert nikto_parse(out)[0]["id"] == "OSVDB-1"

    def test_sniff_parse(self):
        out = "frame.number|ip.src\n1|10.0.0.1\n2|10.0.0.2"
        packets = sniff_parse(out)
        assert len(packets) == 2
        assert packets[0]["ip.src"] == "10.0.0.1"

    def test_ssh_banner_analysis(self):
        r = _analyze_banner("SSH-1.99-OpenSSH_7.2\r\n")
        assert r["protocol"] == "1.99"
        assert any("SSH v1" in f for f in r["findings"])

    def test_ftp_banner_analysis(self):
        r = ftp_analyze("220 (vsFTPd 2.3.4)")
        assert "vsftpd" in r["software"].lower()
        assert len(r["findings"]) == 1

    def test_wifi_macos_parse(self):
        out = "SSID BSSID RSSI CHANNEL HT CC SECURITY\nMyWifi aa:bb:cc:dd:ee:ff -52 6 y -- CN WPA2(PSK)"
        nets = _parse_macos(out)
        assert nets[0]["ssid"] == "MyWifi"
        assert nets[0]["rssi"] == -52

    def test_credential_target_parse(self):
        assert _parse_target("http://a.com:8080/x", "http") == ("http", "a.com", 8080, "/x")
        proto, host, port, _ = _parse_target("10.0.0.1:2222", "ssh")
        assert (proto, host, port) == ("ssh", "10.0.0.1", 2222)


class TestCodeAudit:
    def test_detects_python_sqli_fstring(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text('cursor.execute(f"SELECT * FROM users WHERE id={uid}")\n')
        result = run(CodeAuditTool().execute(path=str(tmp_path)))
        assert result.success
        assert any(x["rule_id"] == "SQLI-002" for x in result.result["findings"])

    def test_detects_hardcoded_secret(self, tmp_path):
        f = tmp_path / "cfg.js"
        f.write_text('const api_key = "sk-1234567890abcdef";\n')
        result = run(CodeAuditTool().execute(path=str(tmp_path)))
        assert any(x["rule_id"] == "SECRET-001" for x in result.result["findings"])

    def test_ignores_node_modules(self, tmp_path):
        (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
        (tmp_path / "node_modules" / "pkg" / "a.js").write_text('eval(userInput)\n')
        result = run(CodeAuditTool().execute(path=str(tmp_path)))
        assert result.result["total_findings"] == 0

    def test_rule_count_covers_25_plus(self):
        assert len(RULES) >= 25


class TestSensitivityContract:
    """sensitive 集合与 TS 一致：attack_test/exploit/sniff/credential_spray (+ mcp_call Phase 3)。"""

    def test_high_sensitivity_set(self):
        sniff = SniffTool()
        spray = CredentialSprayTool()
        assert getattr(sniff, "sensitivity", "low") == "high"
        assert getattr(spray, "sensitivity", "low") == "high"

    def test_ssh_probe_not_sensitive(self):
        # TS ssh_probe sensitive=false，勿过度收紧确认流
        assert getattr(SshProbeTool(), "sensitivity", "low") != "high"


class TestSchemaContract:
    def test_all_new_tools_have_real_schema(self):
        tools = [
            NmapScanTool(), NucleiScanTool(), NiktoScanTool(), FfufScanTool(),
            ScreenshotTool(), CodeAuditTool(), CredentialSprayTool(),
            DnsZoneTransferTool(), CidrScanTool(), WifiScanTool(), SniffTool(),
            SshProbeTool(), FtpProbeTool(), EmailEnumTool(), LdapEnumTool(),
            CloudBucketEnumTool(), ContainerEscapeCheckTool(), InstallToolTool(),
            WappalyzerTool(), ApiSchemaScanTool(),
        ]
        for t in tools:
            schema = t.get_schema()
            params = schema.get("parameters") or {}
            props = params.get("properties")
            assert isinstance(props, dict) and len(props) > 0 or t.name == "container_escape_check", t.name
            assert schema["name"] == t.name


class TestRegistryIntegration:
    def test_tool_names_in_catalog(self):
        from router.tools import _CATEGORIES
        names = {t.name for _, _, lst in _CATEGORIES for t in lst}
        for n in [
            "nmap_scan", "nuclei_scan", "nikto_scan", "ffuf_scan", "screenshot",
            "code_audit", "credential_spray", "wappalyzer", "api_schema_scan",
            "dns_zone_transfer", "cidr_scan", "wifi_scan", "sniff",
            "ssh_probe", "ftp_probe", "email_enum", "ldap_enum",
            "cloud_bucket_enum", "container_escape_check", "install_tool",
            "ssl_analyze",
        ]:
            assert n in names, f"{n} missing from catalog"

    def test_ssl_analyzer_alias(self):
        from router.tools import _CATEGORIES
        names = [t.name for _, _, lst in _CATEGORIES for t in lst]
        assert names.count("ssl_analyzer") == 1  # 兼容别名转发同实例
