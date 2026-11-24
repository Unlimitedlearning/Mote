"""镜头库：目录稳定、详情可读、模型 id 与目录一致。"""

import unittest

from mote import lenses


class LensCatalogTest(unittest.TestCase):
    def test_count_and_shape(self):
        self.assertGreaterEqual(len(lenses.LENSES), 30)
        for key, item in lenses.LENSES.items():
            self.assertEqual(key, key.strip().lower())
            self.assertTrue(item["name"])
            self.assertTrue(item["category"])
            self.assertTrue(item["when"])
            self.assertGreaterEqual(len(item["questions"]), 3)
            for question in item["questions"]:
                self.assertTrue("？" in question or any(
                    verb in question for verb in ("列出", "写出", "把", "假设", "用", "算", "逐项")))

    def test_catalog_lists_every_lens_once(self):
        text = lenses.catalog()
        for key, item in lenses.LENSES.items():
            self.assertEqual(text.count(f"- {key} {item['name']}"), 1)
        self.assertIn("[元认知]", text)
        self.assertIn("[工程执行]", text)

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

    def test_catalog_is_deterministic(self):
        self.assertEqual(lenses.catalog(), lenses.catalog())


class LensShapeTest(unittest.TestCase):
    """仓库只带手写精选：数量与分类要稳定，不依赖外部数据。"""

    def test_curated_count_is_stable(self):
        self.assertEqual(len(lenses.LENSES), 46)


if __name__ == "__main__":
    unittest.main()
