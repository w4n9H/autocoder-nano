import json

from loguru import logger
from tokenizers import Tokenizer
from multiprocessing import Pool, cpu_count

from autocoder_nano.actypes import VariableHolder


class RemoteTokenCounter:
    def __init__(self, tokenizer) -> None:
        self.tokenizer = tokenizer

    def count_tokens(self, text: str) -> int:
        try:
            v = self.tokenizer.chat_oai(
                conversations=[{"role": "user", "content": text}]
            )
            return int(v[0].output)
        except Exception as e:
            logger.error(f"Error counting tokens: {str(e)}")
            return -1


def initialize_tokenizer(tokenizer_path):
    global tokenizer_model
    try:
        tokenizer_model = Tokenizer.from_file(tokenizer_path)
    except Exception as err:
        logger.critical(f"Failed to initialize tokenizer: {str(err)}")
        raise  # 显式抛出异常，避免静默失败


def count_tokens(text: str) -> int:
    try:
        encoded = VariableHolder.TOKENIZER_MODEL.encode('{"role":"user","content":"' + text + '"}')
        v = len(encoded.ids)
        return v
    except Exception as e:
        logger.error(f"Error counting tokens: {str(e)}")
        return -1


def cut_tokens(text: str):
    try:
        # return VariableHolder.TOKENIZER_CUTTER.cutword(text)
        return VariableHolder.TOKENIZER_MODEL.encode(text).tokens
    except Exception as e:
        return []


def count_tokens_worker(text: str) -> int:
    try:
        encoded = tokenizer_model.encode('{"role":"user","content":"' + text + '"}')
        v = len(encoded.ids)
        return v
    except Exception as e:
        logger.error(f"Error counting tokens: {str(e)}")
        return -1


class TokenCounter:
    def __init__(self, tokenizer_path: str):
        self.tokenizer_path = tokenizer_path
        initialize_tokenizer(self.tokenizer_path)
        self.num_processes = max(1, cpu_count() // 2)
        self.pool = Pool(
            processes=self.num_processes,
            initializer=initialize_tokenizer,
            initargs=(self.tokenizer_path,),
        )

    def count_tokens(self, text: str) -> int:
        return self.pool.apply(count_tokens_worker, (text,))