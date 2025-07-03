import traceback

from loguru import logger

from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import AutoCoderArgs, CodeGenerateResult, RankResult


class CodeModificationRanker:
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM):
        self.args = args
        self.llm = llm
        self.llm.setup_default_model_name(args.code_model)
        self.llms = [self.llm]

    @prompt()
    def _rank_modifications(self, s: CodeGenerateResult) -> str:
        """
        对一组代码修改进行质量评估并排序。

        下面是修改需求：

        <edit_requirement>
        {{ s.conversations[0][-2]["content"] }}
        </edit_requirement>

        下面是相应的代码修改：
        {% for content in s.contents %}
        <edit_block id="{{ loop.index0 }}">
        {{content}}
        </edit_block>
        {% endfor %}

        请输出如下格式的评估结果,只包含 JSON 数据:

        ```json
        {
            "rank_result": [id1, id2, id3]  // id 为 edit_block 的 id,按质量从高到低排序
        }
        ```

        注意：
        1. 只输出前面要求的 Json 格式就好，不要输出其他内容，Json 需要使用 ```json ```包裹
        """

    def rank_modifications(self, generate_result: CodeGenerateResult) -> CodeGenerateResult:
        import time
        from collections import defaultdict

        start_time = time.time()
        logger.info(f"开始对 {len(generate_result.contents)} 个候选结果进行排序")

        try:
            results = []
            for llm in self.llms:
                v = self._rank_modifications.with_llm(llm).with_return_type(RankResult).run(generate_result)
                results.append(v.rank_result)

            if not results:
                raise Exception("All ranking requests failed")

            # 计算每个候选人的分数
            candidate_scores = defaultdict(float)
            for rank_result in results:
                for idx, candidate_id in enumerate(rank_result):
                    # Score is 1/(position + 1) since position starts from 0
                    candidate_scores[candidate_id] += 1.0 / (idx + 1)
            # 按分数降序对候选人进行排序
            sorted_candidates = sorted(candidate_scores.keys(),
                                       key=lambda x: candidate_scores[x],
                                       reverse=True)

            elapsed = time.time() - start_time
            score_details = ", ".join([f"candidate {i}: {candidate_scores[i]:.2f}" for i in sorted_candidates])
            logger.info(
                f"排序完成，耗时 {elapsed:.2f} 秒，最佳候选索引: {sorted_candidates[0]}，评分详情: {score_details}"
            )

            rerank_contents = [generate_result.contents[i] for i in sorted_candidates]
            rerank_conversations = [generate_result.conversations[i] for i in sorted_candidates]

            return CodeGenerateResult(contents=rerank_contents, conversations=rerank_conversations)

        except Exception as e:
            logger.error(f"排序过程失败: {str(e)}")
            logger.debug(traceback.format_exc())
            elapsed = time.time() - start_time
            logger.warning(f"排序失败，耗时 {elapsed:.2f} 秒，将使用原始顺序")
            return generate_result