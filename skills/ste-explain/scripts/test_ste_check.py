"""ste_check.py 的单元测试。运行：python -m unittest -v scripts/test_ste_check.py"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

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
        text = "正文。\n<!-- check_banned:off\n反例一。\n反例二。\n-->\n正文二。"
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


if __name__ == "__main__":
    unittest.main()
