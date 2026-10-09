#!/usr/bin/env python3
"""对中文技术文本做两项确定性检查：句长、同义词轮换。

只检查有唯一答案的规则。一句一事、主动语态这类判断留给 SKILL.md 的规则，
不在这里猜。默认只提示，--strict 时有命中退出码 1；文件读不到或同义词表打不开退出码 2。

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

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->")
HEADING = re.compile(r"^\s*#+\s*")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
ASCII_RUN = re.compile(r"[A-Za-z0-9_]+")
SENTENCE_END = re.compile(r"[。！？；]")


class CheckError(Exception):
    """文件读不到、同义词表打不开这类运行错误。main 把它打到 stderr 并以退出码 2 结束，与「有命中」的退出码 1 区分。"""


def clean_lines(text):
    """返回 [(行号, 清洗后文本)]。

    跳过围栏代码块与 HTML 注释里的内容，抹掉行内代码、链接目标、标题井号和列表标记。
    这些位置的文字不是给读者读的句子，不计句长，也不参与同义词统计。
    """
    out = []
    fence = None  # 开栏的 (字符, 长度)；按 CommonMark，关栏要同字符且不短于开栏
    in_comment = False
    for no, raw in enumerate(text.splitlines(), 1):
        m = FENCE.match(raw)
        if fence is None and m:
            fence = (m.group(1)[0], len(m.group(1)))
            continue
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1]:
                fence = None
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


def load_synonyms(path):
    """读同义词组文件。# 开头是注释，! 开头是例外词，其余每行一组、以 / 分隔，少于两个词的行忽略。"""
    groups, exceptions = [], []
    try:
        f = open(path, encoding="utf-8")
    except OSError as e:
        raise CheckError(f"无法读取同义词表 {path}：{e.strerror or e}")
    with f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if ln.startswith("!"):
                exceptions.append(ln[1:].strip())
                continue
            words = [w.strip() for w in ln.split("/") if w.strip()]
            if len(words) >= 2:
                groups.append(words)
    return groups, exceptions


def check_synonyms(text, groups, exceptions, fname):
    """以文件为单位统计：同一组内出现两个以上不同的词即报，列出每个词的行号。

    先把例外词从每行抹掉再找组内词，所以「验证码」不算「验证」出现。
    """
    lines = []
    for no, line in clean_lines(text):
        for ex in exceptions:
            line = line.replace(ex, " ")
        lines.append((no, line))
    findings = []
    for group in groups:
        seen = {}
        for no, line in lines:
            for w in group:
                if w in line:
                    seen.setdefault(w, []).append(no)
        if len(seen) >= 2:
            detail = "；".join(f"{w} 第 {'、'.join(map(str, nos))} 行" for w, nos in seen.items())
            findings.append({
                "file": fname, "rule": "synonym-rotation", "words": seen,
                "message": f"{fname} [同义词] {' / '.join(seen)} 同组出现 {len(seen)} 个词：{detail}",
            })
    return findings


def _read_sources(paths):
    """没有文件参数时读标准输入，文件名记为 <stdin>。"""
    if not paths:
        return [("<stdin>", sys.stdin.read())]
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                out.append((p, f.read()))
        except OSError as e:
            raise CheckError(f"无法读取 {p}：{e.strerror or e}")
        except UnicodeDecodeError:
            raise CheckError(f"无法读取 {p}：不是 UTF-8 文本")
    return out


def run(paths, max_len, syn_path, as_json):
    """跑全部检查，按 --json 决定输出形式，返回命中数。

    syn_path 为 None 时用默认同义词表，默认表不存在就跳过同义词检查；
    用户显式传入的路径打不开则抛 CheckError，不静默放行。
    """
    if syn_path is None:
        syn_path = DEFAULT_SYNONYMS if os.path.exists(DEFAULT_SYNONYMS) else None
    groups, exceptions = load_synonyms(syn_path) if syn_path else ([], [])
    findings = []
    for name, text in _read_sources(paths):
        findings += check_length(text, max_len, name)
        findings += check_synonyms(text, groups, exceptions, name)
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
    ap.add_argument("--synonyms", default=None, help="同义词组文件，默认 references/synonyms.txt")
    ap.add_argument("--strict", action="store_true", help="有命中时退出码 1")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    args = ap.parse_args(argv)
    try:
        hits = run(args.paths, args.max_len, args.synonyms, args.json)
    except CheckError as e:
        print(e, file=sys.stderr)
        return 2
    return 1 if (args.strict and hits) else 0


if __name__ == "__main__":
    sys.exit(main())
