"""镜头库：目录稳定、详情可读、模型 id 与目录一致。"""

import unittest

from mote.services import lenses


class LensCatalogTest(unittest.TestCase):
    def test_catalog_shape_and_stability(self):
        # 仓库只带手写精选：数量与分类稳定，不依赖外部数据
        self.assertEqual(len(lenses.LENSES), 46)
        for key, item in lenses.LENSES.items():
            self.assertEqual(key, key.strip().lower())
            self.assertTrue(item["name"])
            self.assertTrue(item["category"])
            self.assertTrue(item["when"])
            self.assertGreaterEqual(len(item["questions"]), 3)
            for question in item["questions"]:
                self.assertTrue("？" in question or any(
                    verb in question for verb in ("列出", "写出", "把", "假设", "用", "算", "逐项")))

        text = lenses.catalog()
        for key, item in lenses.LENSES.items():
            self.assertEqual(text.count(f"- {key} {item['name']}"), 1)
        self.assertIn("[元认知]", text)
        self.assertIn("[工程执行]", text)
        self.assertEqual(text, lenses.catalog())  # 相同输入必须给出相同目录

    def test_detail_has_questions(self):
        for key, item in lenses.LENSES.items():
            text = lenses.detail(key)
            self.assertIsNotNone(text)
            self.assertIn(item["name"], text)
            for index, question in enumerate(item["questions"], 1):
                self.assertIn(f"{index}. {question}", text)

    def test_detail_unknown_or_malformed(self):
        self.assertIsNone(lenses.detail("不存在的镜头"))
        self.assertIsNone(lenses.detail(None))
        self.assertIsNotNone(lenses.detail("  INVERSION  "))


if __name__ == "__main__":
    unittest.main()
