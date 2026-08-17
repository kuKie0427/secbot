# 工具索引（脚本生成，勿手改）

> 共 15 类 / 82 个工具。生成命令：`uv run python scripts/gen_tool_index.py`；事实源 `router/tools.py::_CATEGORIES`（与 `GET /api/tools` 同源）。

## 核心安全（core）— 4 个

- `port_scan` — 扫描目标主机的开放端口。参数: host(目标IP/域名), scan_type(quick/full, 默认quick), ports(可选, 指定端口列表)
- `service_detect` — 识别目标主机上运行的服务。参数: host 或 target(目标IP/域名), ports(需要检测的端口列表, 可选)
- `vuln_scan` — 检测目标的常见漏洞（SQL注入、XSS、目录遍历、敏感文件等）。参数: host 或 target(目标), port(端口), service(服务类型: http/ssh/ftp)
- `recon` — 对目标进行信息收集（主机名、IP、DNS、开放端口、Web信息等）。参数: target(目标域名或IP)

## 扫描器（scanner）— 6 个

- `nmap_scan` — Nmap 扫描 — 调用 nmap 执行端口扫描、服务版本检测、OS 识别、NSE 脚本扫描等
- `nuclei_scan` — Nuclei 模板扫描 — 使用 nuclei 引擎对目标执行漏洞模板检测
- `nikto_scan` — Nikto Web 漏扫 — 调用 nikto 对 Web 服务器执行综合漏洞扫描
- `ffuf_scan` — Ffuf 目录/参数爆破 — 调用 ffuf 执行高性能模糊测试
- `screenshot` — 页面截图 — 使用 headless 浏览器对目标 URL 进行截图
- `code_audit` — 静态代码安全审计 — 扫描源码中的安全漏洞模式（SQLi、XSS、命令注入、路径遍历、SSRF、反序列化等）

## 网络探测（network）— 14 个

- `dns_lookup` — 查询域名的 DNS 记录（A/AAAA/MX/NS/CNAME/TXT/SOA）。参数: domain(目标域名), record_type(记录类型, 默认ALL)
- `whois_lookup` — 查询域名或IP的WHOIS注册信息（注册人、注册时间、到期时间、NS等）。参数: target(域名或IP)
- `ssl_analyze` — 分析目标的SSL/TLS证书（颁发者、有效期、加密套件、协议版本等）。参数: host(目标域名/IP), port(端口, 默认443)
- `http_request` — 发送HTTP请求并返回响应信息（状态码、头部、响应体）。参数: url(目标URL), method(GET/POST/HEAD/OPTIONS/PUT/DELETE, 默认GET), headers(自定义头部dict), data(请求体), follow_redirects(是否跟随重定向, 默认true)
- `ping_sweep` — Ping扫描指定目标或网段，检测存活主机。参数: target(IP/域名/CIDR网段如192.168.1.0/24), timeout(超时秒数, 默认2)
- `traceroute` — 追踪到目标的网络路由路径（经过的每一跳路由器）。参数: target(目标IP/域名), max_hops(最大跳数, 默认30)
- `subdomain_enum` — 枚举目标域名的子域名（基于字典暴力解析 + DNS 查询）。参数: domain(目标域名), wordlist(自定义子域名列表, 可选)
- `banner_grab` — 抓取目标端口的服务Banner信息（版本、欢迎消息等）。参数: host(目标IP/域名), ports(端口列表, 默认[21,22,25,80,443,3306,5432,6379,8080,8443])
- `arp_scan` — 通过 ARP 协议扫描局域网，发现存活主机及其 MAC 地址。参数: network(CIDR 格式的网段,如 192.168.1.0/24), timeout(超时秒数,默认3)
- `dns_zone_transfer` — DNS 区域传送 — 尝试 AXFR 获取完整 DNS 记录
- `cidr_scan` — 网段扫描 — 对 CIDR 范围批量端口扫描并汇总
- `wifi_scan` — 无线网络扫描 — 列出周围 WiFi 网络及安全配置
- `sniff` — 抓包分析 — 调用 tshark 进行网络流量捕获与协议分析
- `ssl_analyzer` — 分析目标的SSL/TLS证书（颁发者、有效期、加密套件、协议版本等）。参数: host(目标域名/IP), port(端口, 默认443)

## 防御监控（defense）— 6 个

- `defense_scan` — 对本机执行完整安全自检（系统漏洞扫描+网络连接分析+入侵检测+综合报告）。无需参数。
- `self_vuln_scan` — 扫描本机安全漏洞（系统更新、密码策略、不必要服务、文件权限、开放端口、防火墙状态、应用漏洞等）。参数: scan_type(system/network/application/all, 默认all)
- `network_analyze` — 分析本机当前网络连接状态（已建立连接、监听端口、可疑连接、流量统计）。参数: include_traffic(是否含流量统计, 默认true)
- `intrusion_detect` — 检测入侵行为（分析日志/流量中的端口扫描、暴力破解、SQL注入、XSS、DoS、恶意软件等攻击模式）。参数: source_ip(来源IP, 可选), data(待分析数据, 可选), hours(查看最近几小时, 默认24)
- `system_info` — 收集本机系统信息（主机名、OS、CPU、内存、磁盘、网络接口、进程列表、用户列表等）。参数: category(system/network/process/user/all, 默认all)
- `container_escape_check` — 容器逃逸检测 — 检查 Docker/K8s 容器中的逃逸向量

## 实用工具（utility）— 10 个

- `hash_tool` — 哈希计算、识别和验证。参数: action(hash/identify/verify), text(待哈希文本), file_path(待哈希文件路径), algorithm(md5/sha1/sha256/sha512/all, 默认all), hash_value(待识别或验证的哈希值)
- `encode_decode` — 编码/解码工具（Base64、URL、Hex、HTML实体、Unicode、ROT13、二进制）。参数: action(encode/decode), format(base64/url/hex/html/unicode/rot13/binary), text(待处理文本)
- `ip_geolocation` — 查询IP地址的地理位置信息（国家、城市、ISP、AS号、经纬度等）。参数: ip(目标IP, 留空查自己的公网IP)
- `file_analyze` — 分析文件属性（类型、大小、哈希、权限、可疑特征等）。参数: path(文件路径), deep(是否深度分析内容, 默认false)
- `cve_lookup` — 查询CVE漏洞信息（CVSS评分、描述、影响产品、修复建议等）。参数: cve_id(CVE编号如CVE-2021-44228), keyword(关键词搜索), product(产品名称搜索)
- `log_analyze` — 分析日志文件中的安全事件（失败登录、攻击特征、异常访问等）。参数: path(日志文件路径), lines(分析最近N行, 默认1000), pattern(自定义正则匹配), log_text(直接传入日志文本)
- `password_audit` — 评估密码强度（熵值、复杂度、弱密码检查）或审计系统密码策略。参数: password(要评估的密码,可选), policy_check(是否检查系统密码策略,bool,默认false)
- `secret_scanner` — 扫描文件或目录中的敏感信息（API Key、密码、Token、私钥等）。参数: path(文件或目录路径), patterns(自定义正则规则,可选), max_files(最大扫描文件数,默认500)
- `dependency_audit` — 扫描项目依赖文件（requirements.txt / package.json / pom.xml / Cargo.toml / go.mod 等），通过 OSV 数据库查询已知漏洞。参数: path(项目目录或依赖文件路径), type(python/node/java/rust/go/php/ruby, 可选自动检测)
- `payload_generator` — 生成常见漏洞利用 payload 文本（SQL注入/XSS/命令注入/反向Shell/路径穿越）。仅返回 payload 字符串，不执行任何攻击。参数: type(sqli/xss/cmd_inject/reverse_shell/path_traversal), sub_type(子类型,可选), platform(目标平台,可选), ip(反向Shell用的监听IP,可选), port(反向Shell用的监听端口,可选)

## Web 安全（web）— 10 个

- `dir_bruteforce` — 枚举Web服务器的隐藏目录和文件（管理面板、备份文件、配置文件、API端点等）。参数: url(目标URL), wordlist(自定义路径列表, 可选), extensions(扩展名列表如['.php','.bak'], 可选), threads(并发数, 默认20)
- `waf_detect` — 检测目标Web服务是否部署了WAF防火墙（Cloudflare、AWS WAF、Akamai、ModSecurity等）。参数: url(目标URL)
- `tech_detect` — 识别目标Web应用的技术栈（服务器、编程语言、CMS、前端框架、JS库等）。参数: url(目标URL)
- `header_analyze` — 分析目标Web应用的HTTP安全头配置（HSTS、CSP、X-Frame-Options等），给出安全评分和改进建议。参数: url(目标URL)
- `cors_check` — 检查目标Web应用的CORS跨域配置安全性（是否允许任意来源、是否暴露敏感头等）。参数: url(目标URL), test_origins(自定义测试来源列表, 可选)
- `jwt_analyze` — 解码和分析JWT Token的安全性（Header、Payload、算法、有效期、常见漏洞）。参数: token(JWT字符串)
- `param_fuzzer` — 对目标 URL 的参数进行 Fuzz 测试，注入 SQL/XSS/命令注入/路径穿越等 payload，通过响应差异检测潜在漏洞。参数: url(目标 URL), params(要测试的参数名列表,可选,默认自动提取), categories(测试类别列表: sqli/xss/cmd/path, 默认全部)
- `ssrf_detect` — 检测目标 URL 的参数是否存在 SSRF（服务端请求伪造）漏洞。向参数注入内网地址和云元数据 URL，通过响应差异检测漏洞。参数: url(目标 URL), param(可能存在 SSRF 的参数名)
- `wappalyzer` — 深度技术指纹 — 基于 Wappalyzer 规则识别 Web 技术栈
- `api_schema_scan` — API Schema 发现 — 探测 OpenAPI/Swagger/GraphQL 端点

## OSINT（osint）— 4 个

- `shodan_query` — 通过 Shodan 查询目标 IP 的开放端口、服务、漏洞及地理位置等情报。参数: target(IP 地址，可选) 或 query(Shodan 搜索语法，可选)，至少提供一个。
- `virustotal_check` — 通过 VirusTotal 查询 IP / 域名 / URL / 文件哈希的恶意检测结果。参数: target(查询对象), type(ip/domain/url/hash)
- `cert_transparency` — 通过证书透明度日志（crt.sh）查询域名的所有 SSL 证书记录，可用于发现子域名和历史证书。参数: domain(目标域名)
- `credential_leak_check` — 查询邮箱或域名是否在已知数据泄露事件中出现（使用 Have I Been Pwned API）。参数: email(邮箱地址,可选), domain(域名,可选), 至少提供一个

## 协议探测（protocol）— 8 个

- `smb_enum` — 探测目标 SMB 服务的基本信息（OS 版本、域名、签名状态、共享目录等）。参数: target(目标 IP 或域名), port(默认 445)
- `redis_probe` — 检测目标 Redis 是否存在未授权访问漏洞，获取服务器信息。参数: target(目标 IP 或域名), port(默认 6379)
- `mysql_probe` — 探测目标 MySQL 服务的版本、协议号、能力标志等信息（仅读取 Greeting 包，不尝试登录）。参数: target(目标 IP 或域名), port(默认 3306)
- `snmp_query` — 通过 SNMP 协议查询目标设备信息（系统描述、联系人、位置等）。参数: target(目标 IP), community(社区字符串,默认 public), oid(OID 或预设名称: sysDescr/sysName/sysLocation 等, 默认查询全部常用 OID)
- `ssh_probe` — SSH 探测 — Banner 抓取、密钥交换算法识别、弱口令检测
- `ftp_probe` — FTP 探测 — Banner 抓取、匿名登录检测
- `email_enum` — SMTP 用户枚举 — 通过 VRFY/RCPT TO 验证邮箱地址是否存在
- `ldap_enum` — LDAP 枚举 — 匿名绑定探测 + 基础信息获取

## 报告（reporting）— 1 个

- `report_generator` — 将安全扫描发现整理为结构化安全报告（Markdown / HTML / JSON）。参数: title(报告标题), findings(发现列表,每项含 title/risk/description/recommendation), format(输出格式: markdown/html/json/pentest, 默认 markdown), target(测试目标, 可选), attack_chain(攻击链结果, 可选), exploit_results(漏洞利用结果, 可选)

## 云安全（cloud）— 4 个

- `cloud_metadata_detect` — 检测当前环境或目标是否可访问云元数据端点（AWS/GCP/Azure/阿里云/腾讯云等），评估 SSRF 攻击风险。参数: target(可选,指定要测试的 URL,默认测试本机), providers(可选,指定要测试的云厂商列表)
- `s3_bucket_enum` — 枚举公开的 AWS S3 存储桶，检查是否存在未授权的列目录或读取权限。参数: keyword(用于生成桶名猜测的关键词), wordlist(自定义桶名后缀列表,可选)
- `container_info` — 检测当前环境是否运行在 Docker / Kubernetes 容器中，收集容器相关信息（容器 ID、镜像、挂载点、capabilities 等）。无需参数。
- `cloud_bucket_enum` — 多云存储桶枚举 — 支持 AWS S3 / Azure Blob / GCP Storage / 阿里云 OSS

## 系统控制（control）— 3 个

- `terminal_session` — 持久化终端会话工具。由 Agent 打开的终端仅由 Agent 通过 exec 执行命令，对用户为只读（用户仅可查看输出，不可输入）。action=open: 进程内终端，可 exec 发命令并读输出。action=open_external: 真正打开一个新的系统终端窗口（Windows: cmd/PowerShell，Mac: Terminal，Linux: gnome-terminal/xterm）；可传 user_intent(用户意图) 由 LLM 生成初始命令在新窗口执行，或直接传 initial_command。action=exec/read/close/list: 同 open 会话配合使用。参数: action(open/open_external/exec/read/close/list), session_id, command(exec时), cwd(open/open_external时), initial_command(open_external时可选), user_intent(open_external时可选，由 LLM 转为命令), timeout(exec时默认30)
- `web_crawler` — 爬取网页内容并提取信息
- `install_tool` — 安装安全工具 — 自动检测包管理器并安装所需的安全测试工具

## Web 研究（web_research）— 5 个

- `smart_search` — 智能联网搜索：根据关键词搜索互联网，自动访问搜索结果页面并用 AI 提取摘要，最终返回综合研究报告。参数: query(搜索关键词), max_results(访问页面数,默认3), summarize(是否AI总结,默认true)
- `page_extract` — 智能提取网页内容。支持三种模式: text(纯文本提取)、structured(结构化数据如表格/列表)、custom(自定义提取schema)。参数: url(目标URL), mode(text/structured/custom,默认text), schema(custom模式的提取模式dict), css_selector(可选CSS选择器聚焦内容)
- `deep_crawl` — 从起始URL出发，广度优先发现并爬取相关链接页面。参数: start_url(起始URL), max_depth(最大深度,默认2), max_pages(最大页面数,默认10), url_pattern(可选正则过滤URL), extract_info(是否AI提取摘要,默认false), same_domain(是否限同域,默认true)
- `api_client` — 通用REST API客户端，可发送HTTP请求并解析JSON响应。支持两种用法: (1) 自定义请求: 指定url/method/headers/body; (2) 内置模板: 指定preset和query即可快速调用常用API。可用模板: weather(天气查询 (wttr.in)), ip_info(IP 信息查询 (ip-api.com)), ip_self(本机公网 IP (httpbin.org)), github_user(GitHub 用户信息), github_repo(GitHub 仓库信息), exchange_rate(汇率查询 (open.er-api.com)), random_fact(随机趣闻 (uselessfacts.jsph.pl)), country_info(国家信息 (restcountries.com)), dns_resolve(DNS 解析 (dns.google)), url_shorten(URL 缩短检查 (unshorten.me))。参数: url(自定义URL), method(GET/POST等,默认GET), headers(请求头dict), params(query参数dict), body(请求体), auth_type(none/bearer/api_key), auth_value(认证值), preset(模板名), query(模板查询参数)
- `web_research` — 联网研究工具：委托Web研究子Agent自主完成互联网信息收集。支持模式: auto(子Agent自主研究,默认), search(智能搜索), extract(网页提取), crawl(深度爬取), api(API调用)。参数: query(研究主题/搜索词), mode(auto/search/extract/crawl/api,默认auto), url(extract/crawl模式必需的目标URL), preset(api模式的内置模板名)

## Skills（skills）— 3 个

- `list_skills` — List available Secbot skills.
- `get_skill` — Read metadata and body for a Secbot skill.
- `create_skill` — Create a new Secbot skill in the local workspace.

## MCP（mcp）— 1 个

- `mcp_call` — List or call tools from an external MCP stdio server.

## 高级（需确认）（advanced）— 3 个

- `attack_test` — 执行攻击测试（需用户确认）。参数: attack_type(brute_force/sql_injection/xss/dos), target_url(目标URL), parameter(测试参数名, 用于sql_injection/xss), username(用于brute_force)
- `exploit` — 针对已发现的漏洞执行利用（需用户确认）。参数: exploit_type(web/network/post), target(目标), payload(可选, 利用载荷dict)
- `credential_spray` — 凭据喷洒 — 多协议弱口令检测 (HTTP/FTP/SSH banner)

