# ste-explain

[![test](https://github.com/lianghaofeng/ste-explain/actions/workflows/test.yml/badge.svg)](https://github.com/lianghaofeng/ste-explain/actions/workflows/test.yml)

让 Claude 解释代码、diff、CI 结果、排查结论时，按 ASD-STE100 的结构规则写中文。ASD-STE100 是 Simplified Technical English，航空维修手册用的受控语言规范。规则是一句一事、句长有上限、一词一义、保留原文的不确定程度，部件多时附一张 mermaid 图。默认取 Karpathy 2026 年 10 月提出的「80% of the way to ASD-STE100」刻度。


## 1. 安装

### 1.1 在 claude.ai 添加

1. 打开 claude.ai 的 Customize > Plugins，选择 Add > Add marketplace，填入 `lianghaofeng/ste-explain`。
2. 在这个 marketplace 里安装 ste-explain 插件。
3. 打开这个 marketplace 的 Sync automatically，作者推送的更新会自动同步到你的账号。

用同一账号登录的 Claude Code 在启动时同步插件。会话中出现 `Plugins changed. Run /reload-plugins to activate.` 时，运行 `/reload-plugins` 加载。

### 1.2 只用 Claude Code 命令行

```
/plugin marketplace add lianghaofeng/ste-explain
/plugin install ste-explain@ste-explain
```

### 1.3 依赖

脚本只用 Python 3 标准库。

### 1.4 自检

在仓库的 `skills/ste-explain/` 目录下运行：

```bash
python3 -m unittest scripts/test_ste_check.py
```

## 2. 用法

显式触发：

```
/ste-explain 解释这段 diff 改了什么
用 STE 解释这轮 CI 为什么失败
把这段改写成 80% STE
严格 STE：写这个脚本的操作步骤
```

想让它成为日常默认，在项目的 CLAUDE.md 加一句：解释类回复按 ste-explain 的 80% 规则写。

默认只输出改写后的文本。说「看改动」时输出「规则 / 改前 / 改后」三列表。

## 3. 规则一览

| 层 | 内容 |
| --- | --- |
| 80% 规则，九条 | 一句一事；一句不超过 45 字；主动语态；用动词不用名词化；一词一义；用数字和场景不打比方；序列用清单、比较用表格；一段一主题且重点句放段首；术语首现定义 |
| 100% 追加，五条 | 每条指令单独成句用祈使句；不省略主语；不用缩略语；安全类先写后果；每句对应一条事实，推断单独标注 |
| 守则，高于规则 | 保留不确定程度；不新增原因与机制；代码与报错原文不改；事实与推断分开标注；清楚即止；已合规不硬改 |
| 图 | 三个以上相互作用的部件或有状态变化时加 mermaid 图，一图一事，箭头带动词 |

完整规则表与取舍理由在 `skills/ste-explain/references/rules.md`，前后对照在 `references/examples.md`。

## 4. 脚本

`skills/ste-explain/scripts/ste_check.py` 做两项确定性检查：

| 检查 | 规则 | 输出 |
| --- | --- | --- |
| 句长 | 一个句号内字数超过上限（默认 45；CJK 一字算 1，ASCII 串算 1） | `文件:行号 [句长] 68 字，上限 45：<前 30 字>` |
| 同义词轮换 | 同一文档里同一组词出现两个以上，组在 `references/synonyms.txt` | `文件 [同义词] 检查 / 校验 同组出现 2 个词：检查 第 12、30 行；校验 第 18 行` |

```bash
python3 scripts/ste_check.py 文件.md               # 只提示
python3 scripts/ste_check.py --strict 文件.md      # 有命中退出码 1，给提交钩子用
python3 scripts/ste_check.py --json 文件.md        # 结构化输出
echo "文本" | python3 scripts/ste_check.py        # 读标准输入
```

围栏代码块、行内代码、链接目标、HTML 注释不检查。

## 5. 不做的事

- 不含 ASD 官方词典。ASD 不允许转载，且词典是英文。
- 不做 Karpathy 四级里的 HTML 页与讲解视频。
- 不用于创意与宣传文案。

## 6. 来源

- Karpathy，2026-10-02：https://x.com/karpathy/status/2105819303471976479
- danyuchn/asd-ste100-skill：https://github.com/danyuchn/asd-ste100-skill ，守则中「保留不确定程度」「不新增事实」的出处
- prithivrajmu/asd-ste100：https://github.com/prithivrajmu/asd-ste100 ，80% 规则化写法与图的约束的出处
- ASD-STE100 官方站：https://www.asd-ste100.org/

## 7. 许可证

MIT，见 LICENSE。
