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


if __name__ == "__main__":
    unittest.main()
