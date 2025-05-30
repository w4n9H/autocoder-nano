from difflib import SequenceMatcher


class TextSimilarity:
    """
    找到 text_b 中与 text_a 最相似的部分(滑动窗口)
    返回相似度分数和最相似的文本片段
    """

    def __init__(self, text_a, text_b):
        self.text_a = text_a
        self.text_b = text_b
        self.lines_a = self._split_into_lines(text_a)
        self.lines_b = self._split_into_lines(text_b)
        self.m = len(self.lines_a)
        self.n = len(self.lines_b)

    @staticmethod
    def _split_into_lines(text):
        return text.splitlines()

    @staticmethod
    def _levenshtein_ratio(s1, s2):
        return SequenceMatcher(None, s1, s2).ratio()

    def get_best_matching_window(self):
        best_similarity = 0
        best_window = []

        for i in range(self.n - self.m + 1):  # 滑动窗口
            window_b = self.lines_b[i:i + self.m]
            similarity = self._levenshtein_ratio("\n".join(self.lines_a), "\n".join(window_b))

            if similarity > best_similarity:
                best_similarity = similarity
                best_window = window_b

        return best_similarity, "\n".join(best_window)