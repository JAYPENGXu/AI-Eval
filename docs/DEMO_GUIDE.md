# RAGPilot 十分钟全链路演示

这套演示数据用于让面试官亲手验证文档解析、OCR、切片、混合召回、精细引用、Trace、评测、安全隔离、Agent 参数实验，以及 HITL 发布和回滚。演示内容全部是虚构企业资料，不包含真实个人或商业数据。

## 一次性准备

固定 PDF 位于 `backend/rag/demo_assets/`，纳入版本控制和 Docker 镜像。`seed_demo_workspace` 只复制这些资产，不会重新生成 PDF。生成脚本 `scripts/generate_demo_pdfs.py` 仅用于维护资产，不属于部署启动流程。

```bash
cd backend
source venv/bin/activate
python manage.py migrate

# 正式演示：真实执行本地 PDF 解析、PaddleOCR、Embedding 和 Milvus 索引。
python manage.py seed_demo_workspace --reset

# CI 或无外网的界面测试：只建立租户、策略、Case、Baseline 和 HITL 场景。
# 该模式不会伪造解析、OCR、Chunk 或向量索引成功状态。
python manage.py seed_demo_workspace --reset --no-process
```

正式 Seed 需要 Redis、独立 Milvus 服务、可用的 Embedding 配置，以及混合扫描 PDF 所需的 PaddleOCR 配置。任何外部服务失败都会让命令明确失败，不会生成假向量或把扫描页静默当成空白页。

## 演示角色

启用 `DEMO_MODE=true` 后，登录页显示一键 Persona 登录：

| Persona | 用途 |
| --- | --- |
| 组织负责人 | 查看组织内全部密级，确认配置发布和回滚 |
| 知识库管理员 | 查看解析、切片、索引和评测集维护能力 |
| 审计员 | 只读查看 Trace、评测与授权审计 |
| 研发员工 | 查看研发资料和本人薪资，无法查看 HR 薪酬政策 |
| HR 专员 | 查看 HR 薪酬与个人薪资，无法查看研发机密资料 |
| 外部供应商 | 只属于第二租户，用于验证跨租户零召回 |

`demo_suspended` 作为停用 Principal 保留在安全评测集中，不提供登录入口。

## 十分钟演示路径

1. **解析与 OCR**：以知识库管理员登录，打开 `xinghai_mixed_ocr_dr.pdf`。检查逐页预览、OCR 页标记、质量指标和第 3 页术语 `ORION-7421`。
2. **切片与索引**：查看 Chunk 的 `page_start/page_end/heading_path/block_ids`，再查看索引签名和过期检测。
3. **召回、引用与 Trace**：询问“ORION 灾备演练的验证码是什么？”，检查混合召回、Rerank、Compression、页码引用及各阶段 Trace。
4. **专家评测**：查看 smoke、benchmark、regression、release 与 security suite；打开固定 Baseline 的失败 Case，检查 deterministic checks 和 Judge JSON。
5. **安全隔离**：先以研发员工提问并保留会话，再退出并切换外部供应商，检查当前对话与历史会话中均不存在研发内容；同时比较研发、HR 和供应商的文档列表与召回结果。越权文档名称、正文、Citation、Trace、历史答案和其他用户会话均不可泄露。
6. **Agent 实验**：打开固定实验计划，比较 Baseline 与两个 Variant，查看 Winner 依据和 Release Gate。
7. **HITL 发布**：以组织负责人确认“发布通过 Release Gate 的 RAG 配置”，检查活跃版本和 Deployment 审计。
8. **HITL 回滚**：对 v1 发起回滚并再次独立确认，检查活跃版本恢复和第二条审计记录。

## 公共 Demo 保护

- Persona 登录不暴露密码，直接签发短期 JWT。
- Demo 用户和高成本接口受 DRF 限流控制。
- 预置 Organization、KB、Document、Role、Policy、Membership 和工作区重置接口禁止访客破坏。
- Persona 切换会先取消上一身份的进行中请求并清空浏览器内存状态，新身份数据加载完成前不会渲染工作台。
- 演示会话按 User 私有；共享 Organization/KnowledgeBase 只共享被授权的知识资源，不共享聊天历史。
- 访客可以创建临时 KB、Policy、文档、评测和 Agent 运行，用于真实体验。
- Celery Beat 周期执行 `rag.reset_demo_runtime`，清理访客数据并恢复待发布卡片，但保留已经完成的解析、OCR、Chunk 和向量索引。

手工恢复初始状态：

```bash
python manage.py shell -c "from rag.demo_reset import reset_demo_runtime; print(reset_demo_runtime())"
```

彻底删除并重建两个演示租户：

```bash
python manage.py reset_demo_workspace --confirm demo-workspace
```

## 部署验收

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
python -m compileall rag assistant_backend
pytest rag/tests -q

cd ../frontend
npm run typecheck
npm run build
npm run e2e
```

最后还必须在部署环境验证：Redis `PONG`、Celery Worker `ping`、Milvus 端口可达、全部演示文档为 `indexed`、混合 OCR 页为 `ocr`，并以研发员工执行一次实际查询，确认答案引用包含页码且 HR 薪酬文档零召回。
