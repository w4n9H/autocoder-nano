from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_types import AutoCoderArgs
from autocoder_nano.rag.doc_entry import RAGFactory


def rag_retrieval(llm: AutoLLM, args: AutoCoderArgs, path: str):
    rag_factory = RAGFactory()
    rag = rag_factory.get_rag(llm=llm, args=args, path=path)
    contexts = rag.search(query=args.query)
    return contexts


def rag_build_cache(llm: AutoLLM, args: AutoCoderArgs, path: str):
    rag_factory = RAGFactory()
    rag = rag_factory.get_rag(llm=llm, args=args, path=path)
    rag.build_cache()


__all__ = ["rag_retrieval", "rag_build_cache"]


