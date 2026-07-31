---
name: kochab
description: Understand or apply evaluation-driven harness evolution. Use when the user wants to learn Kochab's capability-cycle idea, migrate evaluation-driven development into their own system, or optimize a skill with the kochab CLI.
---

# 紫微 · Kochab

紫微是评估驱动开发的参考实现：一份方法论、一层参考抽象、一套供智能体驱动的动态技能工具。这三层对应三件可以做的事。用户没有说明要做什么时，先把三件事摆给用户；意图已经明确时，直接进入对应的一件。

## 一、理解紫微的思想

紫微回答的问题是：智能体如何扩展大语言模型的能力边界？答案是完整的闭环——能力先被组织进运行框架，经评测驱动迭代变得可靠，验证过的方法再经训练回到参数。紫微从这条循环中切出一段来建模：错误归因之后，运行框架如何被修改。

完整论述见[《智能体如何扩展大语言模型的能力边界》](docs/reference/capability-cycle.md)。

## 二、把评测驱动开发迁移到你的系统

参考抽象定义了局部循环的领域模型、接口与一轮迭代，可以整体迁移进你的软件。做法是对齐范式：先参考紫微的数据结构与思想，审计你的系统有没有可观测性、可复现的环境、评测集与验证器，把整条链路缺的东西写成 TODO 逐项补齐；补完之后，进入评测驱动开发。按[迁移指南](docs/migration.md)推进。

## 三、优化一个 skill

用 `kochab` 命令行在自己的技能上跑一轮动态技能优化，全程由你主导。选一个真实任务，拷贝若干份，每份初始化后交给一个干净的执行会话运行；你分析轨迹、修改技能，再让下一个执行会话复测。执行者用你的 sub agent，或你给自己开的会话；两者都没有时，与用户协商执行方式。全流程见[本地工具](docs/local-tools.md)。
