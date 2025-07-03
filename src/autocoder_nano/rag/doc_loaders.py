import copy
import mimetypes
import os
import re
import time
import traceback
from io import BytesIO
from typing import Union, Any, List, Optional, Tuple

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTImage, LTFigure
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pypdf import PdfReader

from autocoder_nano.actypes import SourceCode
from autocoder_nano.rag.token_counter import count_tokens, count_tokens_worker
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class FileConversionException(BaseException):
    pass


class UnsupportedFormatException(BaseException):
    pass


class DocumentConverterResult:
    """The result of converting a document to text."""
    def __init__(self, title: Union[str, None] = None, text_content: str = ""):
        self.title: Union[str, None] = title
        self.text_content: str = text_content


class DocumentConverter:
    """Abstract superclass of all DocumentConverters."""
    def convert(self, local_path: str, **kwargs: Any) -> Union[None, DocumentConverterResult]:
        raise NotImplementedError()


class PdfConverter(DocumentConverter):
    """
    Converts PDFs to Markdown with support for extracting and including images.
    """
    def convert(self, local_path, **kwargs) -> Union[None, DocumentConverterResult]:
        # Bail if not a PDF
        extension = kwargs.get("file_extension", "")
        if extension.lower() != ".pdf":
            return None

        text_content = []

        # Open and process PDF
        with open(local_path, "rb") as file:
            # Create PDF parser and document
            parser = PDFParser(file)
            document = PDFDocument(parser)
            rsrcmgr = PDFResourceManager()
            laparams = LAParams()
            device = PDFPageAggregator(rsrcmgr, laparams=laparams)
            interpreter = PDFPageInterpreter(rsrcmgr, device)

            # Process each page
            for page in PDFPage.create_pages(document):
                interpreter.process_page(page)
                layout = device.get_result()

                # Extract text and images from the page
                page_content = self._process_layout(layout)
                text_content.extend(page_content)

        return DocumentConverterResult(
            title=None,
            text_content="\n".join(text_content),
        )

    def _process_layout(self, layout) -> List[str]:
        """Process the layout of a PDF page, extracting both text and images."""
        content = []
        for lt_obj in layout:
            # Handle images
            if isinstance(lt_obj, LTImage) or (isinstance(lt_obj, LTFigure) and lt_obj.name.startswith("Im")):
                pass

            # Handle text
            if hasattr(lt_obj, "get_text"):
                text = lt_obj.get_text().strip()
                if text:
                    content.append(text)

            # Recursively process nested layouts
            elif hasattr(lt_obj, "_objs"):
                content.extend(self._process_layout(lt_obj._objs))

        return content


class PlainTextConverter(DocumentConverter):
    """Anything with content type text/plain"""

    def convert(self, local_path: str, **kwargs: Any) -> Union[None, DocumentConverterResult]:
        # Guess the content type from any file extension that might be around
        content_type, _ = mimetypes.guess_type("__placeholder" + kwargs.get("file_extension", ""))

        # Only accept text files
        if content_type is None:
            return None
        elif "text/" not in content_type.lower():
            return None

        text_content = ""
        with open(local_path, "rt", encoding="utf-8") as fh:
            text_content = fh.read()
        return DocumentConverterResult(
            title=None,
            text_content=text_content,
        )


class RAGConverter:
    def __init__(self, mlm_client: Optional[Any] = None, mlm_model: Optional[Any] = None,):
        self._mlm_client = mlm_client
        self._mlm_model = mlm_model
        self._page_converters: List[DocumentConverter] = []
        self.register_page_converter(PdfConverter())
        self.register_page_converter(PlainTextConverter())

    def convert(self, source: str, **kwargs: Any) -> DocumentConverterResult | None:
        # Local path or url
        if isinstance(source, str):
            return self.convert_local(source, **kwargs)
        else:
            pass

    def convert_local(self, path: str, **kwargs: Any) -> DocumentConverterResult:  # TODO: deal with kwargs
        # Prepare a list of extensions to try (in order of priority)
        ext = kwargs.get("file_extension")
        extensions = [ext] if ext is not None else []

        # Get extension alternatives from the path and puremagic
        base, ext = os.path.splitext(path)    # pdf
        self._append_ext(extensions, ext)     # extensions=[pdf]

        # Convert
        return self._convert(path, extensions, **kwargs)

    @staticmethod
    def _append_ext(extensions, ext):
        """Append a unique non-None, non-empty extension to a list of extensions."""
        if ext is None:
            return
        ext = ext.strip()
        if ext == "":
            return
        # if ext not in extensions:
        if True:
            extensions.append(ext)

    def _convert(self, local_path: str, extensions: List[Union[str, None]], **kwargs) -> DocumentConverterResult:
        error_trace = ""
        res = None
        for ext in extensions + [None]:  # Try last with no extension
            for converter in self._page_converters:
                _kwargs = copy.deepcopy(kwargs)
                # Overwrite file_extension appropriately
                if ext is None:
                    if "file_extension" in _kwargs:
                        del _kwargs["file_extension"]
                else:
                    _kwargs.update({"file_extension": ext})

                # Copy any additional global options
                if "mlm_client" not in _kwargs and self._mlm_client is not None:
                    _kwargs["mlm_client"] = self._mlm_client
                if "mlm_model" not in _kwargs and self._mlm_model is not None:
                    _kwargs["mlm_model"] = self._mlm_model

                # If we hit an error log it and keep trying
                try:
                    res = converter.convert(local_path, **_kwargs)
                except Exception:
                    error_trace = ("\n\n" + traceback.format_exc()).strip()
                if res is not None:
                    # Normalize the content
                    res.text_content = "\n".join(
                        [line.rstrip()
                         for line in re.split(r"\r?\n", res.text_content)]
                    )
                    res.text_content = re.sub(r"\n{3,}", "\n\n", res.text_content)

                    # Todo
                    return res
        # If we got this far without success, report any exceptions
        if len(error_trace) > 0:
            raise FileConversionException(
                f"Could not convert '{local_path}' to Markdown. File type was recognized as {extensions}. While "
                f"converting the file, the following error was encountered:\n\n{error_trace}"
            )

        # Nothing can handle it!
        raise UnsupportedFormatException(
            f"Could not convert '{local_path}' to Markdown. The formats {extensions} are not supported."
        )

    def register_page_converter(self, converter: DocumentConverter) -> None:
        """Register a page text converter."""
        self._page_converters.insert(0, converter)


def extract_text_from_pdf_old(file_path):
    with open(file_path, "rb") as f:
        pdf_content = f.read()
    pdf_file = BytesIO(pdf_content)
    pdf_reader = PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text


def extract_text_from_pdf(file_path):
    try:
        md_converter = RAGConverter()
        result = md_converter.convert(file_path)
        return result.text_content
    except (BaseException, Exception) as e:
        traceback.print_exc()
        return extract_text_from_pdf_old(file_path)


def process_file_local(file_path: str) -> List[SourceCode]:
    start_time = time.time()
    try:
        if file_path.endswith(".pdf"):
            content = extract_text_from_pdf(file_path)
            v = [
                SourceCode(
                    module_name=file_path,
                    source_code=content,
                    tokens=count_tokens(content),
                )
            ]
        else:
            with open(file_path, "r", encoding="utf-8") as fp:
                content = fp.read()
            v = [
                SourceCode(
                    module_name=f"##File: {file_path}",
                    source_code=content,
                    tokens=count_tokens(content),
                )
            ]
        printer.print_text(f"解析文件 {file_path}, 耗时: {time.time() - start_time}", style="green")
        return v
    except (BaseException, Exception) as e:
        printer.print_text(f"解析文件 {file_path} 失败: {str(e)}", style="red")
        traceback.print_exc()
        return []


def process_file_in_multi_process(file_info: Tuple[str, str, float, str]) -> List[SourceCode]:
    start_time = time.time()
    file_path, relative_path, _, _ = file_info
    try:
        if file_path.endswith(".pdf"):
            content = extract_text_from_pdf(file_path)
            v = [
                SourceCode(
                    module_name=file_path,
                    source_code=content,
                    tokens=count_tokens_worker(content),
                )
            ]
        else:
            with open(file_path, "r", encoding="utf-8") as fp:
                content = fp.read()
            v = [
                SourceCode(
                    module_name=f"##File: {file_path}",
                    source_code=content,
                    tokens=count_tokens_worker(content),
                )
            ]
        printer.print_text(f"解析文件 {file_path}, 耗时: {time.time() - start_time}", style="green")
        return v
    except (BaseException, Exception) as e:
        printer.print_text(f"解析文件 {file_path} 失败: {str(e)}", style="red")
        return []