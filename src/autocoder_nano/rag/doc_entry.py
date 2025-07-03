from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.rag.long_context_rag import LongContextRAG


class RAGFactory:
    @staticmethod
    def get_rag(llm: AutoLLM, args: AutoCoderArgs, path: str, **kargs) -> LongContextRAG:
        """
        Factory method to get the appropriate RAG implementation based on arguments.
        Args:
            llm (AutoLLM): The ByzerLLM instance.
            args (AutoCoderArgs): The arguments for configuring RAG.
            path (str): The path to the data.
        Returns:
            SimpleRAG or LongContextRAG: The appropriate RAG implementation.
        """
        return LongContextRAG(llm, args, path, **kargs)