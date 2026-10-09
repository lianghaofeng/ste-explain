#!/usr/bin/env python3
"""对中文技术文本做两项确定性检查：句长、同义词轮换。

只检查有唯一答案的规则。一句一事、主动语态这类判断留给 SKILL.md 的规则，
不在这里猜。默认只提示，--strict 时有命中退出码 1。

用法：
    ste_check.py <文件…>
    ste_check.py --strict <文件…>
    ste_check.py --max-len 45 <文件…>
    ste_check.py --synonyms <文件> <文件…>
    ste_check.py --json <文件…>
    echo "文本" | ste_check.py
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SYNONYMS = os.path.join(HERE, "..", "references", "synonyms.txt")
DEFAULT_MAX_LEN = 45

FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->")
HEADING = re.compile(r"^\s*#+\s*")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
ASCII_RUN = re.compile(r"[A-Za-z0-9_]+")
SENTENCE_END = re.compile(r"[。！？；]")


def clean_lines(text):
    """返回 [(行号, 清洗后文本)]。

    跳过围栏代码块与 HTML 注释里的内容，抹掉行内代码、链接目标、标题井号和列表标记。
    这些位置的文字不是给读者读的句子，不计句长，也不参与同义词统计。
    """
    out = []
    in_fence = False
    in_comment = False
    for no, raw in enumerate(text.splitlines(), 1):
        if FENCE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = raw
        if in_comment:
            end = line.find("-->")
            if end < 0:
                continue
            line = line[end + 3:]
            in_comment = False
        line = HTML_COMMENT.sub(" ", line)
        start = line.find("<!--")
        if start >= 0:
            line = line[:start]
            in_comment = True
        line = INLINE_CODE.sub(" ", line)
        line = LINK_TARGET.sub("]", line)
        line = HEADING.sub("", line)
        line = LIST_MARKER.sub("", line)
        out.append((no, line))
    return out


def split_sentences(line):
    """表格行先按 | 分格，再按「。！？；」切句，去掉空串。"""
    cells = line.split("|") if "|" in line else [line]
    sents = []
    for cell in cells:
        for s in SENTENCE_END.split(cell):
            s = s.strip()
            if s:
                sents.append(s)
    return sents


def count_units(s):
    """字数：一个 CJK 字符算 1，连续的 ASCII 字母数字下划线串算 1，标点与空白不计。"""
    return len(CJK.findall(s)) + len(ASCII_RUN.findall(s))


def check_length(text, max_len, fname):
    """报出字数超过 max_len 的句子，带行号与前 30 字摘录。"""
    findings = []
    for no, line in clean_lines(text):
        for s in split_sentences(line):
            n = count_units(s)
            if n > max_len:
                excerpt = s if len(s) <= 30 else s[:30] + "…"
                findings.append({
                    "file": fname, "line": no, "rule": "sentence-length",
                    "count": n, "limit": max_len, "excerpt": excerpt,
                    "message": f"{fname}:{no} [句长] {n} 字，上限 {max_len}：{excerpt}",
                })
    return findings


def _read_sources(paths):
    """没有文件参数时读标准输入，文件名记为 <stdin>。"""
    if not paths:
        return [("<stdin>", sys.stdin.read())]
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            out.append((p, f.read()))
    return out


def run(paths, max_len, syn_path, as_json):
    """跑全部检查，按 --json 决定输出形式，返回命中数。"""
    findings = []
    for name, text in _read_sources(paths):
        findings += check_length(text, max_len, name)
    if as_json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f["message"])
    return len(findings)


def main(argv=None):
    ap = argparse.ArgumentParser(description="中文句长与同义词轮换检查")
    ap.add_argument("paths", nargs="*", help="要检查的文件，缺省读标准输入")
    ap.add_argument("--max-len", type=int, default=DEFAULT_MAX_LEN, help=f"句长上限，默认 {DEFAULT_MAX_LEN}")
    ap.add_argument("--synonyms", default=DEFAULT_SYNONYMS, help="同义词组文件")
    ap.add_argument("--strict", action="store_true", help="有命中时退出码 1")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    args = ap.parse_args(argv)
    hits = run(args.paths, args.max_len, args.synonyms, args.json)
    return 1 if (args.strict and hits) else 0


if __name__ == "__main__":
    sys.exit(main())
