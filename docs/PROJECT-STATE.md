# 项目状态（接续用）

> 新会话接手时先读本文件和 `../AGENTS.md`、`DECISIONS.md`，再动代码。
> 本文件随每轮工作结束更新「当前状态」和「排队清单」两节。

更新于：2026-07-23（本轮：降级触发修正 D33——移除字高独立降级，字号下限渲染兜底）

## 当前状态

- **测试**:136 passed（`pytest tests/ -q`，约 25s，含 1 个 ~12s slow 真实图验收）;offscreen 冒烟 `tests/smoke_gui.py` → SMOKE OK;`tests/test_requirements.py` 守护依赖声明完整性;`tests/conftest.py` autouse 逐测 GC（防隐藏窗口引用环累积致 offscreen 崩溃，D30）
- **CI/CD**:`.github/workflows/ci.yml`（push main/PR，三平台 × Python 3.14，Linux 装 X11/GL,offscreen pytest + 冒烟）;`.github/workflows/release.yml`（v* 标签，三平台 build.py 打包 → zip/tar → gh release,**尚未实机运行，首轮结果待观察**）
- **功能**:批量导入（拖放/文件对话框/剪贴板粘贴）、全码制识别（zxing-cpp)、分层管线 v2+L3 区域层（签名共识误识防护，真实图 5/5）、命中位置反变换、DecodeProfile 参数化（pre/l1/l2/l3/consensus 五组全开放，默认零变化）+ 识别档案池（内置默认可恢复）+ 导出模板池（4 个内置预设）、**识别框全局编号（疑似黄框）+ 点击高亮橙框 + F1 独立预览窗口（缩放/旋转/平移/标记开关）**、识别框高亮预览、识别控制项（三档/码制白名单/疑似码/单图增强重扫，与档案正交）、去重视图+计数、SQLite 历史库+搜索、按码重命名、两段式模板导出 + XLSX/JSON + 导出过滤 + 按模板复制到剪贴板、状态持久化、轮转日志、中文界面
- **数据**:SQLite 库含 `records` + `strategy_log` 两表；数据目录新增 `profiles.json`（识别档案池）与 `templates.json`（导出模板池，首跑写入 4 个内置预设）；真实验证集起步：`tests/images/real_drug_labels.png`
- **打包**:`python build.py` → PyInstaller;2026-07-23 已重打 `dist/BarcodeReader.app`(120MB,98 测试全绿后构建，offscreen 启动验证通过、无翻译警告，D24)

## 路线图（2026-07-22 用户确认）

| 阶段 | 内容 | 启动门槛 |
| --- | --- | --- |
| **R1 导出增强** | 两段式模板聚合导出（行模板+连接符+外模板+分组维度）+ XLSX/JSON + 导出过滤（类型/长度/前缀/正则）+ 导出到剪贴板 | 设计已确认（D16），用户发话即开工 |
| **R2 真实验证** | 真实疑难图跑管线出命中率报告，针对性补层 | **部分推进**：首张真实图（药品追溯码）已入库，驱动产出 L3 区域层（D19），5/5 命中 |
| **阶段 2 在线学习** | ε-greedy bandit 按图像特征动态排序参数组合 | **地基就绪（D20 profile 参数化）**；数据门槛：strategy_log ≥200 条真实图记录 且 L1/L2 救回样本 ≥30 条（低于此学了也是噪声） |
| **阶段 3 深度学习** | 离线训练小模型 → ONNX 推理（onnxruntime） | 阶段 2 上线且 strategy_log ≥2000 条后评估 |
| **挂起** | `.claude/skills` 改写、Windows/Linux 实机验证、体验项（主题/预览缩放/CLI/HEIC/PDF，按需点单不主动铺） | 用户发话 |

## 排队清单（优先级序）

1. ~~高亮框坐标反变换~~（D13）~~档位/白名单/疑似码/增强重扫~~（D14/D15）~~R1 导出增强~~（D16/D18，67 passed 全绿）
2. **R2 真实验证**（待用户供图）
3. **阶段 2 在线学习**（待数据门槛达成，见路线图）
4. 阶段 3 深度学习（ONNX)：数据充足后评估
5. `.claude/skills` 精选改写到 `.agents/skills/`（D12 挂起项）

## 待用户输入

- **真实疑难图验证集**:agent 只能合成模糊/旋转/低对比/反光/反色图，真实识不出的图才是金标准
- Windows/Linux 实机验证（剪贴板 DIB、打包）
- **健壮性审查遗留（D25，待决策）**:~~① profiles/templates JSON 损坏时静默回落默认~~（D26 已完成：备份+一次性弹窗+写失败转 ValueError）;② records/strategy_log 写库失败仅记日志（D 系列既定"不阻塞主流程"，如需可见可改状态栏提示）;③ 极限档 15-20s/批量大图无中间进度（worker 只报完成数，建议评估是否加"当前第 N 层"状态）;~~④ 解码失败只有列表项文本无批量汇总通知~~（D27 已完成：状态栏汇总+日志清单）;⑤ profile 参数组合合法性（如空 binarizers 列表）编辑时不做语义校验（decode 期会列表项报错到达 UI）

## 关键文件索引

| 内容 | 位置 |
| --- | --- |
| 项目约定（必读） | `../AGENTS.md` |
| 决策日志 | `DECISIONS.md`（本目录） |
| 使用手册 | `USER-GUIDE.md`（本目录，README 搬出的细节） |
| 常见问题 | `FAQ.md`（本目录） |
| 分层管线 | `../decoder.py` |
| 策略日志表 | `../history.py` `strategy_log` |
| 项目门面 | `../README.md`（定位/亮点/快速开始/文档地图） |
| CI/Release | `../.github/workflows/ci.yml` / `release.yml` |

## 协作规则摘要（详见 ~/.agents/AGENTS.md）

业务功能：讨论 → 设计 → 确认 → 实施；调试：先复现再分析；单步小步快跑；改完全量测试 + 冒烟全绿才算完；新决策追加到 DECISIONS.md。
