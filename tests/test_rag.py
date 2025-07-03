import os

from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.rag import rag_build_cache, rag_retrieval


def rag_retrieval_test():
    doc_path = ""

    llm = AutoLLM()
    llm.setup_sub_client(
        client_name="ark-deepseek-v3",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="deepseek-v3-250324"
    )
    llm.setup_sub_client(
        client_name="emb",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="doubao-embedding-text-240715"
    )

    args = AutoCoderArgs()
    args.model_max_input_length = 100000
    args.chunk_model = "ark-deepseek-v3"
    args.qa_model = "ark-deepseek-v3"
    args.recall_model = "ark-deepseek-v3"
    args.emb_model = "emb"
    args.enable_hybrid_index = True
    args.query = ""

    print(rag_retrieval(llm=llm, args=args, path=doc_path))


def rag_build_cache_test():
    doc_path = ""

    llm = AutoLLM()
    llm.setup_sub_client(
        client_name="emb",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="doubao-embedding-text-240715"
    )

    args = AutoCoderArgs()
    args.model_max_input_length = 100000
    args.chunk_model = "ark-deepseek-v3"
    args.qa_model = "ark-deepseek-v3"
    args.recall_model = "ark-deepseek-v3"
    args.emb_model = "emb"
    args.enable_hybrid_index = True
    args.required_exts = ".pdf,.doc"

    rag_build_cache(llm=llm, args=args, path=doc_path)


if __name__ == '__main__':
    rag_build_cache_test()