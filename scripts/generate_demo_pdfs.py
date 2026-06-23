from __future__ import annotations

from pathlib import Path
import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "rag" / "demo_assets"
TMP = ROOT / "tmp" / "pdfs"
OUT.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)
FONT = Path("/mnt/c/Windows/Fonts/msyh.ttc")
FONT_BOLD = Path("/mnt/c/Windows/Fonts/msyhbd.ttc")
A4 = fitz.paper_rect("a4")
NAVY = (0.075, 0.145, 0.235)
TEAL = (0.055, 0.49, 0.48)
INK = (0.11, 0.14, 0.18)
MUTED = (0.38, 0.43, 0.49)
PALE = (0.94, 0.97, 0.97)
RED = (0.75, 0.16, 0.18)


def fonts(page):
    return None


def header(page, section, classification="INTERNAL"):
    fonts(page)
    page.draw_rect(fitz.Rect(0, 0, A4.width, 48), color=NAVY, fill=NAVY)
    page.insert_text((42, 31), "星海科技 · RAGPilot Demo", fontname="china-s", fontsize=11, color=(1, 1, 1))
    page.insert_text((A4.width - 150, 31), classification, fontname="china-s", fontsize=9, color=(0.7, 0.95, 0.9))
    page.insert_text((42, 70), section, fontname="china-s", fontsize=9, color=TEAL)


def footer(page, number):
    page.draw_line((42, A4.height - 40), (A4.width - 42, A4.height - 40), color=(0.82, 0.85, 0.88), width=0.6)
    page.insert_text((42, A4.height - 22), "虚构演示数据 · 不包含真实个人或商业信息", fontname="china-s", fontsize=8, color=MUTED)
    page.insert_text((A4.width - 72, A4.height - 22), f"{number:02d}", fontname="china-s", fontsize=8, color=MUTED)


def textbox(page, rect, text, size=11, bold=False, color=INK, lineheight=1.45, align=0):
    remaining = page.insert_textbox(rect, text, fontname="china-s", fontsize=size, color=color, lineheight=lineheight, align=align)
    if remaining < 0:
        raise RuntimeError(f"Text overflow ({remaining:.1f} pt): {text[:60]}")
    return remaining


def cover(doc, title, subtitle, classification="INTERNAL", accent=TEAL):
    page = doc.new_page(width=A4.width, height=A4.height)
    fonts(page)
    page.draw_rect(page.rect, color=NAVY, fill=NAVY)
    page.draw_rect(fitz.Rect(0, 0, 15, A4.height), color=accent, fill=accent)
    page.draw_circle((A4.width - 90, 100), 42, color=accent, fill=accent)
    textbox(page, fitz.Rect(58, 170, A4.width - 58, 310), title, 28, True, (1, 1, 1), 1.25)
    textbox(page, fitz.Rect(60, 320, A4.width - 65, 410), subtitle, 13, False, (0.78, 0.86, 0.91), 1.55)
    page.insert_text((60, A4.height - 95), "RAGOPS CONTROLLED DEMO", fontname="china-s", fontsize=10, color=accent)
    page.insert_text((60, A4.height - 68), classification, fontname="china-s", fontsize=10, color=(1, 1, 1))
    return page


def content_page(doc, title, intro, sections, number, classification="INTERNAL"):
    page = doc.new_page(width=A4.width, height=A4.height)
    header(page, title, classification)
    textbox(page, fitz.Rect(42, 88, A4.width - 42, 126), title, 21, True, NAVY, 1.2)
    textbox(page, fitz.Rect(42, 132, A4.width - 42, 178), intro, 10.5, False, MUTED, 1.45)
    y = 194
    for heading, body in sections:
        page.draw_rect(fitz.Rect(42, y, A4.width - 42, y + 29), color=PALE, fill=PALE)
        page.draw_rect(fitz.Rect(42, y, 47, y + 29), color=TEAL, fill=TEAL)
        textbox(page, fitz.Rect(58, y + 6, A4.width - 52, y + 27), heading, 11.5, True, NAVY, 1.2)
        y += 38
        needed = max(64, 22 * (body.count("\n") + 2))
        textbox(page, fitz.Rect(52, y, A4.width - 48, min(y + needed, A4.height - 60)), body, 10.2, False, INK, 1.5)
        y += needed + 14
    footer(page, number)
    return page


def save(doc, name):
    path = OUT / name
    doc.set_metadata({"title": name, "author": "RAGPilot Demo", "subject": "Synthetic enterprise demo material"})
    doc.save(path, garbage=4, deflate=True)
    doc.close()
    print(path)


def manual():
    d = fitz.open(); cover(d, "RAGPilot 全链路体验指南", "10 分钟验证解析、OCR、切片、召回、引用、Trace、评测、安全隔离、Agent 实验与配置发布回滚。", "DEMO GUIDE")
    pages = [
      ("01 · 演示地图", "建议按页码顺序体验，所有账号与数据均为虚构。", [("角色入口", "demo_owner：组织治理、发布与回滚\ndemo_km：文档、解析、索引、评测与 Agent\ndemo_auditor：只读 Trace、评测与授权审计\ndemo_engineer：全员、研发与本人薪资资料\ndemo_hr：HR 与薪酬资料\ndemo_vendor：另一租户，仅供应商资料"), ("目标", "面试官可以亲手验证同一问题在不同身份下得到不同的授权召回范围。")]),
      ("02 · 文档解析", "上传后由 Celery 异步执行文件校验与统一 IR 解析。", [("统一 IR", "DocumentIR → PageIR → BlockIR。Block 保存 page、heading_path、bbox、paragraph 和 parser metadata。"), ("质量门禁", "观察文本覆盖率、空白页比例、异常字符率、OCR 页比例与解析耗时。低质量结果需人工确认。")]),
      ("03 · OCR 验证", "《混合扫描应急预案》第 3 页是纯图片页。", [("操作", "在解析预览切换到第 3 页，确认 extraction_method=ocr，并搜索灾备验证码 ORION-7421。"), ("边界", "本地文本页不会发送外部 OCR，只有扫描候选页组成子 PDF 提交 PaddleOCR。")]),
      ("04 · 切片与索引", "选择 Sentence 或 Markdown Chunker，观察来源位置保持。", [("来源链", "Chunk metadata 保存 page_numbers、heading_path、block_ids、paragraph_range 与 parse_run_id。"), ("索引签名", "文件、解析器、Chunker、Embedding 模型、维度、Vector backend 与 schema 共同生成签名。")]),
      ("05 · 召回与引用", "问题：P0 故障触发后，多久必须完成升级通知？", [("预期", "回答包含“5 分钟内”，并引用《研发故障响应与发布流程》第 2 页。"), ("可观测", "在 Debug 查看 Vector、BM25、Hybrid/RRF、Rerank、Compression 的候选变化。")]),
      ("06 · Trace 复盘", "打开刚才问答的 Trace。", [("检查项", "Query Router、Rewrite、阶段分数、位置、Token、延迟、配置版本和权限 Scope fingerprint。"), ("隐私", "Trace 不保存完整 Prompt 或 Context，只保留必要 ID、Hash 与脱敏摘要。")]),
      ("07 · 四类评测", "运行 smoke、benchmark、regression、release 与 security。", [("Deterministic", "router_intent、answer_contains、citation_required、vector_hit、rerank_keep、max_latency_ms。"), ("Judge", "固定 Prompt + JSON Schema 输出 correctness_score、citation_score、hallucination_risk 和 reason。")]),
      ("08 · 权限安全", "分别使用 demo_engineer 与 demo_hr 查询“管理层奖金系数”。", [("工程师", "Vector、BM25、Hybrid、Rerank、Compression 均不得出现薪酬 Chunk。"), ("HR", "满足 clearance 与 Role 授权后可召回薪酬制度；跨 Organization 仍为零。")]),
      ("09 · Agent 实验", "选择预置 Baseline，点击开始诊断与优化。", [("闭环", "Agent 定位 recall/rerank 失败 → 生成 Variant → HITL 确认 → Celery 评测 → 选择 Winner。"), ("稳定门禁", "Winner 必须提升至少 0.01、失败 Case 不增加、Deterministic/Judge 通过且性能劣化不超过 20%。")]),
      ("10 · 发布与回滚", "Release Suite 通过后才出现发布 Action Card。", [("发布", "确认后原子切换 KnowledgeBase.active_config_version，并记录 RagConfigDeployment。"), ("回滚", "选择历史上已发布且验证通过的版本，创建独立 HITL 卡并记录原因。")]),
    ]
    for i,(t,intro,sections) in enumerate(pages,2): content_page(d,t,intro,sections,i,"DEMO GUIDE")
    save(d,"ragpilot_demo_guide.pdf")


def employee():
    d=fitz.open(); cover(d,"星海科技员工手册", "适用于全体正式员工的考勤、费用、安全与协作规范。", "INTERNAL")
    content_page(d,"工作时间与休假","所有申请通过 PeopleHub 提交。",[("考勤","核心协作时段为工作日 10:00-16:00。年假至少提前 2 个工作日申请；连续 3 天以上需直属负责人审批。"),("费用报销","差旅费用须在行程结束后 10 个工作日内提交。单笔超过 3,000 元需成本中心负责人复核。")],2)
    content_page(d,"信息安全与沟通","内部资料不得发送到个人邮箱。",[("数据分级","内部资料可向 active Membership 开放；confidential 与 restricted 必须通过 AccessPolicy 授权。"),("安全事件","疑似凭据泄露应在 15 分钟内上报安全值班，并立即吊销相关 Token。")],3)
    content_page(d,"常用服务入口","以下均为虚构演示入口。",[("服务台","IT 服务台：it-help@xinghai.example\nHR 服务台：people@xinghai.example\n安全值班：sec-oncall@xinghai.example"),("文档责任人","员工手册由 People Operations 每季度复核，版本号 DEMO-2026.06。")],4)
    save(d,"xinghai_employee_handbook.pdf")


def engineering():
    d=fitz.open(); cover(d,"研发故障响应与发布流程", "面向 Engineering 部门的 P0/P1 事件响应、发布门禁和回滚标准。", "CONFIDENTIAL")
    content_page(d,"事件等级","事件指挥官以用户影响和数据风险定级。",[("P0","核心链路完全不可用、重大数据风险或影响超过 30% 活跃用户。"),("P1","关键能力明显降级但存在替代路径，或影响 5%-30% 活跃用户。")],2,"CONFIDENTIAL")
    content_page(d,"P0 响应时限","P0 采用强制升级节奏。",[("五分钟升级","P0 故障触发后 5 分钟内必须完成升级通知，并建立事件频道。10 分钟内指定 Incident Commander。"),("状态更新","未恢复期间每 15 分钟更新一次影响范围、止损动作和下一检查点。")],3,"CONFIDENTIAL")
    content_page(d,"发布门禁","生产发布必须有可执行回滚方案。",[("发布前","通过 smoke 与 release suite；确认监控、负责人、变更窗口和回滚命令。"),("自动回滚","错误率连续 5 分钟超过 2%，或 P95 延迟较基线恶化 30%，立即停止发布并回滚。")],4,"CONFIDENTIAL")
    content_page(d,"复盘与行动项","P0/P1 必须形成无责复盘。",[("时限","故障恢复后 2 个工作日内完成复盘草稿，5 个工作日内关闭高优先级行动项。"),("证据","保留 Trace ID、配置版本、Deployment、关键日志 Hash 和指标截图。")],5,"CONFIDENTIAL")
    save(d,"xinghai_engineering_release.pdf")


def compensation():
    d=fitz.open(); cover(d,"薪酬等级与奖金制度", "仅 HR、Owner/Admin 及明确授权人员可访问。", "RESTRICTED", RED)
    content_page(d,"薪酬等级","薪酬数字均为虚构演示数据。",[("专业序列","P4 月薪带宽 22,000-30,000 元；P5 为 28,000-38,000 元；P6 为 36,000-50,000 元。"),("管理序列","M2 月薪带宽 35,000-48,000 元；M3 为 46,000-65,000 元。")],2,"RESTRICTED")
    content_page(d,"奖金系数","年度奖金由公司、团队和个人三个因子组成。",[("公式","年度奖金 = 月度固定薪资 × 目标月数 × 公司系数 × 团队系数 × 个人系数。"),("管理层规则","管理层目标月数为 4，个人系数范围 0.8-1.4；该规则不得向普通 Member 返回。")],3,"RESTRICTED")
    content_page(d,"访问与审计","薪酬资料遵循 deny-first。",[("授权","必须满足 confidential/restricted clearance，并命中 HR Role、allowed user 或 Owner/Admin 豁免。"),("审计","查看、拒绝、Policy 更新、Citation 与 Agent Tool 访问均记录 AuthorizationAuditLog。")],4,"RESTRICTED")
    save(d,"xinghai_compensation_policy.pdf")


def salary():
    d=fitz.open(); cover(d,"个人薪资单 · 林晓", "2026 年 5 月 · 仅本人、HR 与 Owner/Admin 可访问。", "RESTRICTED", RED)
    content_page(d,"薪资明细","以下姓名和金额均为虚构。",[("员工信息","姓名：林晓\n员工编号：DEMO-E-1042\n部门：Engineering\n职级：P5"),("本月明细","固定薪资：28,000 元\n演示奖金：3,200 元\n应发合计：31,200 元\n验证码：PAY-DEMO-1042")],2,"RESTRICTED")
    save(d,"xinghai_personal_salary_linxiao.pdf")


def scanned_page_image(path):
    w,h=1240,1754
    img=Image.new("RGB",(w,h),"white"); draw=ImageDraw.Draw(img)
    title=ImageFont.truetype(str(FONT_BOLD),48); body=ImageFont.truetype(str(FONT),30); small=ImageFont.truetype(str(FONT),22)
    draw.rectangle((0,0,w,120),fill=(18,37,60)); draw.text((70,35),"灾备中心离线操作卡",font=title,fill="white")
    draw.text((75,175),"仅用于 OCR 演示的扫描页",font=small,fill=(80,95,110))
    lines=["步骤 1：确认主区域连续 5 分钟不可用。","步骤 2：由 Incident Commander 发起灾备切换。","步骤 3：双人复核数据复制延迟小于 60 秒。","步骤 4：输入灾备切换验证码 ORION-7421。","步骤 5：切换后每 10 分钟发布一次状态。"]
    y=300
    for line in lines:
        draw.rounded_rectangle((70,y-18,1170,y+66),radius=12,outline=(48,126,122),width=3)
        draw.text((100,y),line,font=body,fill=(28,35,42)); y+=155
    draw.text((75,1580),"星海科技 · 虚构演示数据 · SCANNED PAGE",font=small,fill=(90,100,110))
    img.save(path,quality=92)


def mixed_ocr():
    d=fitz.open(); cover(d,"混合扫描应急预案", "第 3 页为纯图片扫描页，用于验证按页 OCR、原始页码恢复与精细引用。", "CONFIDENTIAL")
    content_page(d,"灾备触发条件","本页为原生文本，不应提交 OCR。",[("触发条件","主区域连续 5 分钟不可用且自动恢复失败；数据复制延迟必须小于 60 秒。"),("角色","Incident Commander 发起切换，Database Owner 与 SRE 双人复核。")],2,"CONFIDENTIAL")
    image_path=TMP/"demo_scanned_page.jpg"; scanned_page_image(image_path)
    page=d.new_page(width=A4.width,height=A4.height); page.insert_image(page.rect,filename=str(image_path))
    content_page(d,"切换后验证","本页恢复为原生文本。",[("验证清单","检查登录、知识库检索、Embedding、Milvus、Celery 与审计日志。"),("回切门禁","业务指标稳定 30 分钟后方可回切；回切同样需要双人确认。")],4,"CONFIDENTIAL")
    save(d,"xinghai_mixed_ocr_dr.pdf")


def vendor():
    d=fitz.open(); cover(d,"远航供应商交付规范", "属于独立 Organization，星海科技成员不得召回。", "TENANT B")
    content_page(d,"交付窗口","供应商资料用于跨租户零召回验证。",[("时间","每周二、周四 14:00-17:00 接收交付。"),("验收口令","供应商验收口令为 VENDOR-SEA-8820，仅远航供应商成员可见。")],2,"TENANT B")
    save(d,"yuanhang_vendor_delivery.pdf")


if __name__ == "__main__":
    manual(); employee(); engineering(); compensation(); salary(); mixed_ocr(); vendor()
