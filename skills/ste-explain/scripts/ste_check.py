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
