"""ste_check.py 的单元测试。运行：python -m unittest -v scripts/test_ste_check.py"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ste_check  # noqa: E402


class CleanLinesTest(unittest.TestCase):
    def test_fence_skipped(self):
        text = "正文一。\n```\n代码里的长句。代码里的长句。\n```\n正文二。"
        lines = ste_check.clean_lines(text)
        self.assertEqual([no for no, _ in lines], [1, 5])

    def test_inline_code_and_link_target_removed(self):
        text = "运行 `python3 很长很长的命令` 后看 [文档](https://example.com/very/long/path)。"
        _, line = ste_check.clean_lines(text)[0]
        self.assertNotIn("很长很长的命令", line)
        self.assertNotIn("https://", line)
        self.assertIn("文档", line)

    def test_multiline_html_comment_skipped(self):
        text = "正文。\n<!-- 下面是注释\n反例一。\n反例二。\n-->\n正文二。"
        lines = ste_check.clean_lines(text)
        joined = "".join(l for _, l in lines)
        self.assertNotIn("反例", joined)
        self.assertIn("正文二", joined)

    def test_heading_and_list_marker_removed(self):
        self.assertEqual(ste_check.clean_lines("## 标题")[0][1], "标题")
        self.assertEqual(ste_check.clean_lines("- 列表项")[0][1], "列表项")
        self.assertEqual(ste_check.clean_lines("1. 第一步")[0][1], "第一步")


class SplitAndCountTest(unittest.TestCase):
    def test_split_on_cjk_terminators(self):
        self.assertEqual(ste_check.split_sentences("甲。乙！丙？丁；戊"), ["甲", "乙", "丙", "丁", "戊"])

    def test_table_cells_and_list_marker(self):
        self.assertEqual(ste_check.split_sentences("| 规则 | 改前。改后 |"), ["规则", "改前", "改后"])

    def test_count_units_mixed(self):
        self.assertEqual(ste_check.count_units("检查 CI 日志"), 5)      # 检 查 日 志 + CI
        self.assertEqual(ste_check.count_units("run_1296 失败，重跑"), 5)  # run_1296 + 失 败 重 跑
        self.assertEqual(ste_check.count_units("，。！"), 0)


class LengthCheckTest(unittest.TestCase):
    def test_long_sentence_reported_with_line(self):
        text = "短句。\n" + "字" * 46 + "。"
        found = ste_check.check_length(text, 45, "t.md")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line"], 2)
        self.assertEqual(found[0]["count"], 46)
        self.assertEqual(found[0]["rule"], "sentence-length")
        self.assertIn("t.md:2 [句长] 46 字，上限 45：", found[0]["message"])

    def test_sentence_at_limit_not_reported(self):
        self.assertEqual(ste_check.check_length("字" * 45 + "。", 45, "t.md"), [])

    def test_excerpt_truncated_to_30(self):
        text = "字" * 60 + "。"
        found = ste_check.check_length(text, 45, "t.md")
        self.assertTrue(found[0]["excerpt"].endswith("…"))
        self.assertEqual(len(found[0]["excerpt"]), 31)


class CliTest(unittest.TestCase):
    def _run(self, argv, stdin=""):
        out = io.StringIO()
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out):
                code = ste_check.main(argv)
        finally:
            sys.stdin = sys.__stdin__
        return code, out.getvalue()

    def test_stdin_default_exit_zero(self):
        code, out = self._run(["--max-len", "5"], stdin="一二三四五六。")
        self.assertEqual(code, 0)
        self.assertIn("<stdin>:1 [句长] 6 字，上限 5", out)

    def test_strict_exit_one(self):
        code, _ = self._run(["--strict", "--max-len", "5"], stdin="一二三四五六。")
        self.assertEqual(code, 1)

    def test_strict_clean_exit_zero(self):
        code, out = self._run(["--strict", "--max-len", "5"], stdin="一二三。")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_json_output(self):
        code, out = self._run(["--json", "--max-len", "5"], stdin="一二三四五六。")
        data = json.loads(out)
        self.assertEqual(data[0]["rule"], "sentence-length")
        self.assertEqual(data[0]["count"], 6)


class SynonymTest(unittest.TestCase):
    GROUPS = [["检查", "校验", "验证", "确认"], ["删除", "移除", "清除"]]
    EXC = ["验证码", "检查点"]

    def test_two_words_same_group_reported(self):
        text = "先检查日志。\n再验证结果。\n最后检查输出。"
        found = ste_check.check_synonyms(text, self.GROUPS, self.EXC, "t.md")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["rule"], "synonym-rotation")
        self.assertEqual(found[0]["words"], {"检查": [1, 3], "验证": [2]})
        self.assertEqual(found[0]["message"], "t.md [同义词] 检查 / 验证 同组出现 2 个词：检查 第 1、3 行；验证 第 2 行")

    def test_single_word_not_reported(self):
        text = "先检查日志。\n再检查结果。"
        self.assertEqual(ste_check.check_synonyms(text, self.GROUPS, self.EXC, "t.md"), [])

    def test_exception_word_removed(self):
        text = "先检查日志。\n输入验证码。"
        self.assertEqual(ste_check.check_synonyms(text, self.GROUPS, self.EXC, "t.md"), [])

    def test_code_block_ignored(self):
        text = "先检查日志。\n```\n验证\n```"
        self.assertEqual(ste_check.check_synonyms(text, self.GROUPS, self.EXC, "t.md"), [])

    def test_load_synonyms_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("# 注释\n检查/校验/验证/确认\n\n删除/移除/清除\n!验证码\n!检查点\n单词\n")
            path = f.name
        groups, exc = ste_check.load_synonyms(path)
        os.unlink(path)
        self.assertEqual(groups, self.GROUPS)
        self.assertEqual(exc, self.EXC)

    def test_run_includes_synonyms(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("检查/验证\n")
            syn = f.name
        out = io.StringIO()
        sys.stdin = io.StringIO("先检查。\n再验证。")
        try:
            with redirect_stdout(out):
                hits = ste_check.run([], 45, syn, False)
        finally:
            sys.stdin = sys.__stdin__
            os.unlink(syn)
        self.assertEqual(hits, 1)
        self.assertIn("[同义词] 检查 / 验证", out.getvalue())

    def test_default_synonyms_missing_is_skipped(self):
        saved = ste_check.DEFAULT_SYNONYMS
        ste_check.DEFAULT_SYNONYMS = "/nonexistent/default-synonyms.txt"
        out = io.StringIO()
        sys.stdin = io.StringIO("先检查。\n再校验。")
        try:
            with redirect_stdout(out):
                hits = ste_check.run([], 45, None, False)
        finally:
            sys.stdin = sys.__stdin__
            ste_check.DEFAULT_SYNONYMS = saved
        self.assertEqual(hits, 0)

    def test_explicit_missing_synonyms_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        sys.stdin = io.StringIO("先检查。\n再校验。")
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = ste_check.main(["--synonyms", "/nonexistent/syn.txt"])
        finally:
            sys.stdin = sys.__stdin__
        self.assertEqual(code, 2)
        self.assertIn("/nonexistent/syn.txt", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())


class NestedFenceTest(unittest.TestCase):
    def test_tilde_fence_inside_backtick_fence_is_content(self):
        text = "```\n" + "字" * 50 + "。\n~~~\n" + "字" * 50 + "。\n```\n正文。"
        self.assertEqual(ste_check.check_length(text, 45, "t.md"), [])
        self.assertEqual([no for no, _ in ste_check.clean_lines(text)], [6])

    def test_longer_fence_wraps_shorter_fence(self):
        text = "````markdown\n```\n" + "字" * 50 + "。\n```\n````\n正文。"
        self.assertEqual(ste_check.check_length(text, 45, "t.md"), [])
        self.assertEqual([no for no, _ in ste_check.clean_lines(text)], [6])


class FileErrorTest(unittest.TestCase):
    def test_missing_input_file_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ste_check.main(["/nonexistent/input.md"])
        self.assertEqual(code, 2)
        self.assertIn("/nonexistent/input.md", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

    def test_file_argument_is_reported_with_its_path(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("一二三四五六。\n")
            path = f.name
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = ste_check.main([path, "--max-len", "5"])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertIn(f"{path}:1 [句长] 6 字，上限 5", out.getvalue())


class MarkerAndQuoteTest(unittest.TestCase):
    def test_blockquote_skipped(self):
        text = "> " + "字" * 50 + "。\n正文。"
        self.assertEqual([no for no, _ in ste_check.clean_lines(text)], [2])

    def test_off_on_markers_skip_region(self):
        text = "正文一。\n<!-- ste_check:off -->\n反例。\n<!-- ste_check:on -->\n正文二。"
        self.assertEqual([no for no, _ in ste_check.clean_lines(text)], [1, 5])

    def test_skip_marker_skips_one_line(self):
        text = "正文一。\n反例。 <!-- check_banned:skip -->\n正文二。"
        self.assertEqual([no for no, _ in ste_check.clean_lines(text)], [1, 3])


class BannedWordTest(unittest.TestCase):
    def _rules(self, body):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(body)
            path = f.name
        rules = ste_check.load_banned(path)
        os.unlink(path)
        return rules

    def test_load_banned_formats(self):
        rules = self._rules("# 注释\n有坑 → 已知冲突\n翻转 → 回滚 ! 图像 行为\nre:在.*的情况下 → 删掉\n没有箭头的行\n")
        self.assertEqual(len(rules), 3)
        self.assertEqual(rules[0][:3], ("substring", "有坑", "已知冲突"))
        self.assertEqual(rules[1][3], ["图像", "行为"])
        self.assertEqual(rules[2][0], "regex")

    def test_substring_hit_with_suggestion(self):
        rules = self._rules("有坑 → 已知冲突\n")
        found = ste_check.check_banned("这里有坑。", rules, "t.md")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["rule"], "banned-word")
        self.assertEqual(found[0]["message"], "t.md:1 [反面词] 有坑 → 已知冲突")

    def test_exception_prefix_suppresses(self):
        rules = self._rules("翻转 → 回滚 ! 图像 行为\n")
        self.assertEqual(ste_check.check_banned("图像翻转后保存。", rules, "t.md"), [])
        self.assertEqual(len(ste_check.check_banned("配置翻转回去。", rules, "t.md")), 1)

    def test_regex_hit(self):
        rules = self._rules("re:在.*的情况下 → 删掉\n")
        found = ste_check.check_banned("在网络断开的情况下重试。", rules, "t.md")
        self.assertEqual(found[0]["message"], "t.md:1 [反面词] 在网络断开的情况下 → 删掉")

    def test_code_and_quote_not_checked(self):
        rules = self._rules("有坑 → 已知冲突\n")
        self.assertEqual(ste_check.check_banned("`有坑`\n> 有坑\n```\n有坑\n```", rules, "t.md"), [])

    def test_cli_explicit_missing_banned_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        sys.stdin = io.StringIO("正文。")
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = ste_check.main(["--banned", "/nonexistent/banned.txt"])
        finally:
            sys.stdin = sys.__stdin__
        self.assertEqual(code, 2)
        self.assertIn("/nonexistent/banned.txt", err.getvalue())

    def test_cli_banned_repeatable(self):
        import tempfile
        paths = []
        for body in ("有坑 → 已知冲突\n", "跑通 → 验证通过\n"):
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(body)
                paths.append(f.name)
        out = io.StringIO()
        sys.stdin = io.StringIO("有坑，但跑通了。")
        try:
            with redirect_stdout(out):
                code = ste_check.main(["--strict", "--banned", paths[0], "--banned", paths[1]])
        finally:
            sys.stdin = sys.__stdin__
            for p in paths:
                os.unlink(p)
        self.assertEqual(code, 1)
        self.assertIn("[反面词] 有坑 → 已知冲突", out.getvalue())
        self.assertIn("[反面词] 跑通 → 验证通过", out.getvalue())


class RulesSelectionTest(unittest.TestCase):
    def test_rules_banned_only_skips_length_and_synonyms(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("有坑 → 已知冲突\n")
            banned = f.name
        out = io.StringIO()
        sys.stdin = io.StringIO("先检查，再校验，这里有坑。" + "字" * 50 + "。")
        try:
            with redirect_stdout(out):
                code = ste_check.main(["--strict", "--rules", "banned", "--banned", banned])
        finally:
            sys.stdin = sys.__stdin__
            os.unlink(banned)
        self.assertEqual(code, 1)
        self.assertIn("[反面词] 有坑", out.getvalue())
        self.assertNotIn("[句长]", out.getvalue())
        self.assertNotIn("[同义词]", out.getvalue())

    def test_rules_unknown_name_exits_two(self):
        out, err = io.StringIO(), io.StringIO()
        sys.stdin = io.StringIO("正文。")
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = ste_check.main(["--rules", "lengthh"])
        finally:
            sys.stdin = sys.__stdin__
        self.assertEqual(code, 2)
        self.assertIn("lengthh", err.getvalue())


if __name__ == "__main__":
    unittest.main()
