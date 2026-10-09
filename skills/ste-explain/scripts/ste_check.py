#!/usr/bin/env python3
"""对中文技术文本做三项确定性检查：句长、同义词轮换、反面词。

只检查有唯一答案的规则。一句一事、主动语态这类判断留给 SKILL.md 的规则，
不在这里猜。默认只提示，--strict 时有命中退出码 1；文件读不到或同义词表打不开退出码 2。

用法：
    ste_check.py <文件…>
    ste_check.py --strict <文件…>
    ste_check.py --max-len 45 <文件…>
    ste_check.py --synonyms <文件> <文件…>
    ste_check.py --banned <文件> [--banned <文件>…] <文件…>
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
DEFAULT_BANNED = os.path.join(HERE, "..", "references", "banned-words.txt")
DEFAULT_MAX_LEN = 45

FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK_TARGET = re.compile(r"\]\([^)]*\)")
HTML_COMMENT = re.compile(r"<!--.*?-->")
HEADING = re.compile(r"^\s*#+\s*")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
BLOCKQUOTE = re.compile(r"^\s*>")
MARKER = re.compile(r"(?:ste_check|check_banned):(off|on|skip)")
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
ASCII_RUN = re.compile(r"[A-Za-z0-9_]+")
SENTENCE_END = re.compile(r"[。！？；]")


class CheckError(Exception):
    """文件读不到、同义词表打不开这类运行错误。main 把它打到 stderr 并以退出码 2 结束，与「有命中」的退出码 1 区分。"""


def clean_lines(text):
    """返回 [(行号, 清洗后文本)]。

    跳过围栏代码块、引用块、HTML 注释里的内容，抹掉行内代码、链接目标、标题井号和列表标记。
    这些位置的文字不是给读者读的句子，不计句长，不参与同义词统计，也不查反面词。
    忽略标记写在 HTML 注释里：`<!-- ste_check:off -->` 起到 `<!-- ste_check:on -->` 止整段不查，
    `<!-- ste_check:skip -->` 所在行不查；前缀 `check_banned:` 同义，兼容旧文档。
    """
    out = []
    fence = None  # 开栏的 (字符, 长度)；按 CommonMark，关栏要同字符且不短于开栏
    in_comment = False
    disabled = False
    for no, raw in enumerate(text.splitlines(), 1):
        mk = MARKER.search(raw)
        if mk:
            if mk.group(1) == "off":
                disabled = True
            elif mk.group(1) == "on":
                disabled = False
            continue
        if disabled:
            continue
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
        if BLOCKQUOTE.match(line):
            continue
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


def load_banned(path):
    """读反面词表。每行「反面词 → 标准词」，可带「! 例外前缀…」；`re:` 开头的是正则；# 开头是注释。

    返回 [(type, 反面词或正则, 标准词, 例外前缀列表)…]，type 是 "substring" 或 "regex"。
    """
    rules = []
    try:
        f = open(path, encoding="utf-8")
    except OSError as e:
        raise CheckError(f"无法读取反面词表 {path}：{e.strerror or e}")
    with f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "→" not in ln:
                continue
            bad, rest = ln.split("→", 1)
            bad = bad.strip()
            if "!" in rest:
                good, ex = rest.split("!", 1)
                good, excludes = good.strip(), ex.split()
            else:
                good, excludes = rest.strip(), []
            if not bad:
                continue
            if bad.startswith("re:"):
                try:
                    rules.append(("regex", re.compile(bad[3:]), good, []))
                except re.error as e:
                    raise CheckError(f"反面词表 {path} 的正则无效：{bad}（{e}）")
            else:
                rules.append(("substring", bad, good, excludes))
    return rules


def _hit_in_line(s, bad, excludes):
    """s 里只要有一处 bad 前面不紧跟任何例外前缀，就算命中。"""
    start = 0
    while True:
        i = s.find(bad, start)
        if i < 0:
            return False
        if not any(i >= len(ex) and s[i - len(ex):i] == ex for ex in excludes):
            return True
        start = i + len(bad)


def check_banned(text, rules, fname):
    """逐行查反面词，命中给行号与建议替换。"""
    findings = []
    for no, line in clean_lines(text):
        for rtype, pat, good, excludes in rules:
            if rtype == "regex":
                m = pat.search(line)
                word = m.group(0) if m else None
            else:
                word = pat if _hit_in_line(line, pat, excludes) else None
            if word:
                findings.append({
                    "file": fname, "line": no, "rule": "banned-word", "word": word, "suggestion": good,
                    "message": f"{fname}:{no} [反面词] {word} → {good}",
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


def run(paths, max_len, syn_path, as_json, banned_paths=None):
    """跑全部检查，按 --json 决定输出形式，返回命中数。

    syn_path 为 None 时用默认同义词表，banned_paths 为 None 时用默认反面词表；默认表不存在就跳过该项。
    用户显式传入的路径打不开则抛 CheckError，不静默放行。多个反面词表叠着查。
    """
    if syn_path is None:
        syn_path = DEFAULT_SYNONYMS if os.path.exists(DEFAULT_SYNONYMS) else None
    groups, exceptions = load_synonyms(syn_path) if syn_path else ([], [])
    if banned_paths is None:
        banned_paths = [DEFAULT_BANNED] if os.path.exists(DEFAULT_BANNED) else []
    rules = [r for bp in banned_paths for r in load_banned(bp)]
    findings = []
    for name, text in _read_sources(paths):
        findings += check_length(text, max_len, name)
        findings += check_synonyms(text, groups, exceptions, name)
        findings += check_banned(text, rules, name)
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
    ap.add_argument("--banned", action="append", default=None, help="反面词表，可重复传，默认 references/banned-words.txt")
    ap.add_argument("--strict", action="store_true", help="有命中时退出码 1")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    args = ap.parse_args(argv)
    try:
        hits = run(args.paths, args.max_len, args.synonyms, args.json, args.banned)
    except CheckError as e:
        print(e, file=sys.stderr)
        return 2
    return 1 if (args.strict and hits) else 0


if __name__ == "__main__":
    sys.exit(main())
