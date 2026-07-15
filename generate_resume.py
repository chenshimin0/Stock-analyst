#!/usr/bin/env python3
"""生成陈世民的中文简历PDF"""

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ── 配色 ──────────────────────────────────────────────
PRIMARY   = (41, 98, 173)     # 深蓝
ACCENT    = (70, 130, 220)    # 亮蓝
LIGHT_BG  = (235, 242, 252)   # 浅蓝背景
DARK_TEXT  = (33, 33, 33)     # 正文黑色
GRAY_TEXT  = (120, 120, 120)  # 灰色文字
WHITE      = (255, 255, 255)
LIGHT_LINE = (200, 210, 220)

# ── 字体路径 ──────────────────────────────────────────
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"  # macOS 冬青黑体


class ResumePDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.add_font("CN", "", FONT_PATH)
        self.add_font("CN", "B", FONT_PATH)  # fpdf2 会使用同一文件（粗体模拟）
        self.set_auto_page_break(auto=True, margin=18)

    # ── 页头 ──────────────────────────────────────────
    def header_block(self):
        self.set_fill_color(*PRIMARY)
        self.rect(0, 0, 210, 38, "F")

        self.set_text_color(*WHITE)
        self.set_font("CN", "B", 24)
        self.set_xy(20, 8)
        self.cell(0, 12, "陈世民", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_font("CN", "", 10)
        self.set_xy(20, 24)
        self.cell(0, 6, "全栈开发工程师  |  深圳", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # ── 联系方式行 ────────────────────────────────────
    def contact_row(self):
        contacts = [
            "186-8896-8591",
            "shiminchen625@gmail.com",
            "github.com/shiminchen",
            "微信: shiminchen625",
        ]
        self.set_fill_color(*LIGHT_BG)
        self.rect(0, 38, 210, 10, "F")
        self.set_text_color(*DARK_TEXT)
        self.set_font("CN", "", 8.5)
        x_start = 15
        for c in contacts:
            self.set_xy(x_start, 39)
            self.cell(45, 8, c)
            x_start += 46

    # ── 小节标题 ──────────────────────────────────────
    def section_title(self, title):
        self.ln(4)
        self.set_font("CN", "B", 14)
        self.set_text_color(*PRIMARY)
        self.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # 下划线
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.6)
        y = self.get_y()
        self.line(15, y, 195, y)
        self.ln(4)

    # ── 正文 ──────────────────────────────────────────
    def body_text(self, text, size=9.5):
        self.set_font("CN", "", size)
        self.set_text_color(*DARK_TEXT)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet(self, text, size=9.5):
        self.set_font("CN", "", size)
        self.set_text_color(*DARK_TEXT)
        self.set_x(self.l_margin)
        self.cell(5, 5.5, "•")
        w = self.w - self.r_margin - self.get_x()
        self.multi_cell(w, 5.5, text)

    # ── 经历条目 ──────────────────────────────────────
    def exp_entry(self, title, subtitle, period, bullets):
        # 标题行（左对齐标题，右对齐时间）
        self.set_font("CN", "B", 10.5)
        self.set_text_color(*DARK_TEXT)
        self.cell(0, 6, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        # 副标题 + 时间
        self.set_font("CN", "", 9)
        self.set_text_color(*GRAY_TEXT)
        self.cell(100, 5, subtitle)
        self.set_x(150)
        self.cell(0, 5, period, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.ln(1)
        for b in bullets:
            self.bullet(b)
        self.ln(1)

    # ── 技能标签 ──────────────────────────────────────
    def skill_tag(self, label, x, y):
        self.set_xy(x, y)
        self.set_fill_color(*LIGHT_BG)
        self.set_draw_color(*ACCENT)
        self.set_text_color(*PRIMARY)
        self.set_font("CN", "", 8.5)
        w = self.get_string_width(label) + 5
        self.cell(w, 6, label, border=1, fill=True, align="C")

    def skills_section(self, groups):
        for label, items in groups:
            self.set_font("CN", "B", 10)
            self.set_text_color(*DARK_TEXT)
            w_lbl = self.get_string_width(label + "：") + 1
            self.cell(w_lbl, 6, label + "：")
            self.set_font("CN", "", 9)
            self.set_text_color(*GRAY_TEXT)
            w_remain = self.w - self.r_margin - self.get_x()
            self.cell(w_remain, 6, items, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(2)

    # ── 证书条目 ──────────────────────────────────────
    def cert_entry(self, name, issuer, date):
        self.set_font("CN", "B", 9.5)
        self.set_text_color(*DARK_TEXT)
        w_name = self.get_string_width(name) + 2
        self.cell(w_name, 5.5, name)
        self.set_font("CN", "", 8.5)
        self.set_text_color(*GRAY_TEXT)
        self.cell(0, 5.5, f"{issuer}  |  {date}", align="R",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)


def build_resume():
    pdf = ResumePDF()
    pdf.add_page()

    # ── 页头 ──────────────────────────────────────────
    pdf.header_block()
    pdf.contact_row()

    # ── 个人简介 ──────────────────────────────────────
    pdf.section_title("个人简介")
    pdf.body_text(
        "拥有 2 年全栈开发经验，精通 JavaScript/TypeScript、Python 及主流前后端框架。"
        "具备独立架构设计能力，善于团队协作与技术分享。对股票量化分析有浓厚兴趣，"
        "独立开发了全栈股票分析系统。持续学习新技术，追求代码质量与工程效率。"
    )

    # ── 教育背景 ──────────────────────────────────────
    pdf.section_title("教育背景")
    pdf.exp_entry(
        "太原科技大学",
        "计算机科学与技术 · 本科",
        "2019.09 — 2023.06",
        [
            "主修课程：数据结构与算法、操作系统、数据库原理、计算机网络、软件工程",
            "毕业设计：《基于深度学习的股票价格预测系统》，获院级优秀论文",
            "在校期间获国家励志奖学金、ACM 校赛二等奖",
        ],
    )

    # ── 工作经历 ──────────────────────────────────────
    pdf.section_title("工作经历")

    pdf.exp_entry(
        "深圳银兴科技有限公司",
        "全栈开发工程师",
        "2023.07 — 至今",
        [
            "负责公司核心 ERP 系统的全栈开发与维护，支撑 500+ 企业客户日常使用",
            "主导前端架构升级：React + TypeScript + Ant Design Pro → 微前端（qiankun），"
            "首屏加载时间降低 40%",
            "基于 Node.js + NestJS 搭建 RESTful API 网关，整合 6 个微服务，日均处理请求 50 万+",
            "设计 PostgreSQL 分库分表方案，优化慢查询 30+ 条，核心接口响应时间 < 200ms",
            "搭建 Docker + GitLab CI 自动化部署流水线，实现每天多次迭代发布",
        ],
    )

    pdf.exp_entry(
        "北京云创科技",
        "前端开发实习生",
        "2022.06 — 2022.12",
        [
            "参与公司 SaaS 平台的前端开发，基于 Vue 3 + Element Plus 实现 20+ 业务页面",
            "封装可复用组件库（表格、表单、图表），提升团队开发效率约 30%",
            "配合后端完成 RESTful API 联调与测试，编写单元测试覆盖率达 85%",
        ],
    )

    # ── 专业技能 ──────────────────────────────────────
    pdf.section_title("专业技能")
    pdf.skills_section([
        ("语言",     "TypeScript / JavaScript, Python, Java, Go, SQL"),
        ("前端",     "React / Redux, Vue 3 / Pinia, Ant Design, TailwindCSS, HTML5 / CSS3"),
        ("后端",     "Node.js / NestJS, Python / Django / Flask, Java / Spring Boot, RESTful / GraphQL"),
        ("数据库",   "PostgreSQL, MySQL, Redis, MongoDB, Elasticsearch"),
        ("云与运维", "Docker / K8s, AWS (EC2/S3/Lambda), 阿里云, Nginx, GitLab CI / GitHub Actions"),
        ("其他",     "Git / Linux, WebSocket, RabbitMQ, Webpack / Vite, Jest, 敏捷开发"),
    ])

    # ── 项目经验 ──────────────────────────────────────
    pdf.section_title("项目经验")

    pdf.exp_entry(
        "股票分析系统（开源个人项目）",
        "全栈独立开发",
        "2024.01 — 至今",
        [
            "独立设计并开发全栈股票分析平台，集成行情数据采集、技术指标计算与可视化分析",
            "后端：Python FastAPI + Celery + PostgreSQL + Redis，对接东方财富/腾讯行情数据接口",
            "前端：React + TypeScript + Ant Design + ECharts，实现 K 线图、MACD/RSI 等技术指标展示",
            "部署：Docker Compose + 阿里云 ECS，配置 Nginx 反向代理与 HTTPS",
            "GitHub Star 120+，技术博客系列阅读量 5000+",
        ],
    )

    pdf.exp_entry(
        "智能客服对话平台",
        "后端核心开发（团队项目）",
        "2024.03 — 2024.08",
        [
            "基于 Spring Boot + Netty 开发高并发 WebSocket 消息推送服务，支持万人同时在线的客服系统",
            "设计消息队列（RabbitMQ）+ Redis 缓存架构，消息延迟 < 50ms",
            "实现智能路由分配算法（基于轮询 + 技能标签），平均响应时间缩短 60%",
            "编写 API 文档（Swagger）与压力测试报告（JMeter，QPS 峰值 8000+）",
        ],
    )

    pdf.exp_entry(
        "个人博客与技术社区",
        "全栈开发",
        "2023.08 — 2024.02",
        [
            "基于 Next.js + MDX + TailwindCSS 构建技术博客，支持全文搜索与评论互动",
            "后端使用 Strapi Headless CMS + PostgreSQL，部署于 Vercel + Railway",
            "累计发表 25+ 篇技术文章，涵盖前端工程化、Python 量化、系统设计等主题",
            "实现 RSS 订阅、暗色模式、PWA 离线访问等特性",
        ],
    )

    # ── 证书 ──────────────────────────────────────────
    pdf.section_title("证书与荣誉")

    pdf.cert_entry("Google Professional Cloud Architect", "Google Cloud", "2024.08")
    pdf.cert_entry("Google Professional Data Engineer", "Google Cloud", "2024.06")
    pdf.cert_entry("AWS Certified Solutions Architect – Associate", "Amazon Web Services", "2024.03")
    pdf.cert_entry("全国计算机等级考试三级（数据库技术）", "教育部", "2022.03")

    pdf.ln(3)
    pdf.set_font("CN", "", 7.5)
    pdf.set_text_color(*GRAY_TEXT)
    pdf.cell(0, 5, "更新于 2025 年 7 月", align="C")

    # ── 输出 ──────────────────────────────────────────
    pdf.output("/Users/shiminchen/stock-analysis-system/陈世民_简历.pdf")
    print("✅ 简历已生成：陈世民_简历.pdf")


if __name__ == "__main__":
    build_resume()
