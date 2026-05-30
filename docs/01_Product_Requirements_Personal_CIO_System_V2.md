# Personal CIO System（个人首席投资官系统）
## Product Requirements Document (PRD) V2.0

## 项目愿景

构建一名永不疲倦、严格执行规则、持续学习、能够自动生成高质量投资计划的 Personal CIO。

系统负责：
- 收集信息
- 分析市场
- 评估风险
- 制定投资计划
- 生成订单草稿
- 自动复盘总结

用户负责：
- 审核计划
- 批准交易
- 承担最终投资决策责任

---

## 核心目标

### 减少重复劳动
自动完成：
- 查看股票图表
- 查看均线结构
- 查看财报日期
- 查看新闻
- 风险检查
- 投资日志记录
- 投资复盘

### 降低决策噪音
减少：
- 情绪化交易
- 追涨杀跌
- 被假跌破洗出
- 忘记风险事件
- 临时改变计划

### 节省时间

当前：60~120分钟/天

目标：5~15分钟/天

---

## 系统总体架构

market-data-service
↓
analysis-engine
↓
trade-planner
↓
personal-cio-agent
↓
broker-gateway-schwab
↓
investment-journal

---

## 六大核心模块

### 1. market-data-service
统一管理市场数据

### 2. analysis-engine
将市场数据转化为结构化信号

### 3. trade-planner
生成高质量交易计划

### 4. broker-gateway-schwab
连接 Schwab API，生成订单草稿

### 5. personal-cio-agent
生成 Daily CIO Brief

### 6. investment-journal
记录与复盘

---

## MVP路线

Phase 1: Analysis Engine

Phase 2: Trade Planner

Phase 3: Investment Journal

Phase 4: Personal CIO Agent

Phase 5: Broker Gateway

---

## 最终目标

打造一个：

Personal CIO
+ Trade Planner
+ Order Draft Generator
+ Investment Journal

帮助用户减少噪音、减少重复劳动、减少情绪化决策、提高复盘能力和长期投资质量。
