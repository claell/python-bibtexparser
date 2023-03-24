import abc
import logging
import re
from typing import Optional

import pylatexenc
from pylatexenc import latexencode, latexwalker
from pylatexenc.latex2text import LatexNodes2Text, MacroTextSpec
from pylatexenc.latexencode import (
    RULE_REGEX,
    UnicodeToLatexConversionRule,
    UnicodeToLatexEncoder,
    unicode_to_latex,
)

from bibtexparser.middlewares.middleware import BlockMiddleware
from bibtexparser.middlewares.names import NameParts
from bibtexparser.model import Block, Entry, String


class _PyStringTransformerMiddleware(BlockMiddleware, abc.ABC):
    """Abstract utility class allowing to modify python-strings"""

    @abc.abstractmethod
    def _transform_python_value_string(self, python_string: str) -> str:
        """Called for every python (value, not key) string found on Entry and String blocks"""
        raise NotImplementedError("called abstract method")

    # docstr-coverage: inherited
    def transform_entry(self, entry: Entry, library: "Library") -> Block:
        for field in entry.fields:
            if isinstance(field.value, str):
                field.value = self._transform_python_value_string(field.value)
            elif isinstance(field.value, NameParts):
                field.value.first = [
                    self._transform_python_value_string(f) for f in field.value.first
                ]
                field.value.last = [
                    self._transform_python_value_string(n) for n in field.value.last
                ]
                field.value.von = [
                    self._transform_python_value_string(v) for v in field.value.von
                ]
                field.value.jr = [
                    self._transform_python_value_string(j) for j in field.value.jr
                ]
            else:
                logging.info(
                    f" [{self.metadata_key()}] Cannot python-str transform field {field.key}"
                    f" with value type {type(field.value)}"
                )
        return entry

    # docstr-coverage: inherited
    def transform_string(self, string: String, library: "Library") -> Block:
        if isinstance(string.value, str):
            string.value = self._transform_python_value_string(string.value)
        else:
            logging.info(
                f" [{self.metadata_key()}] Cannot python-str transform string {string.key}"
                f" with value type {type(string.value)}"
            )
        return string


class LatexEncodingMiddleware(_PyStringTransformerMiddleware):
    """Latex-Encodes all strings in the library"""

    def __init__(
        self,
        allow_inplace_modification: bool,
        keep_math: bool = None,
        enclose_urls: bool = None,
        encoder: Optional[UnicodeToLatexEncoder] = None,
    ):
        super().__init__(allow_inplace_modification, allow_parallel_execution=True)

        if encoder is not None and (keep_math is not None or enclose_urls is not None):
            raise ValueError(
                "Cannot specify both encoder and keep_math or enclose_urls."
                "If you want to use a custom encoder, you have to specify it completely."
            )

        # Defaults (not specified as defaults in args,
        #   to make sure we can identify if they were specified)
        keep_math = keep_math if keep_math is not None else True
        enclose_urls = enclose_urls if enclose_urls is not None else True

        # Build encoder if no encoder was specified
        if encoder is None:
            conversion_rules = []
            if keep_math is True:
                conversion_rules.append(
                    UnicodeToLatexConversionRule(
                        rule_type=RULE_REGEX,
                        # keep math mode parts as is
                        rule=[(re.compile(r"(?<!\\)(\$.*[^\\]\$)"), r"\1")],
                    )
                )
            if enclose_urls is True:
                conversion_rules.append(
                    UnicodeToLatexConversionRule(
                        rule_type=RULE_REGEX,
                        rule=[
                            (re.compile(r"(https?://\S*\.\S*)"), r"\\url{\1}"),
                            (re.compile(r"(www.\S*\.\S*)"), r"\\url{\1}"),
                        ],
                    )
                )

            conversion_rules.append("defaults")
            encoder = UnicodeToLatexEncoder(conversion_rules=conversion_rules)
        self._encoder = encoder

    # docstr-coverage: inherited
    def metadata_key(self) -> str:
        return "latex_encoding"

    # docstr-coverage: inherited
    def _transform_python_value_string(self, python_string: str) -> str:
        return self._encoder.unicode_to_latex(python_string)


class LatexDecodingMiddleware(_PyStringTransformerMiddleware):
    """Latex-Decodes all strings in the library"""

    def __init__(
        self,
        allow_inplace_modification: bool,
        keep_braced_groups: bool = None,
        keep_math_mode: bool = None,
        decoder: Optional[LatexNodes2Text] = None,
    ):
        super().__init__(allow_inplace_modification, allow_parallel_execution=True)

        if decoder is not None and (
            keep_braced_groups is not None or keep_math_mode is not None
        ):
            raise ValueError(
                "Cannot specify both encoder and one of "
                "`keep_braced_groups` or `keep_braced_groups`."
                "If you want to use a custom encoder, "
                "you have to specify it completely."
            )

        # Defaults (not specified as defaults in args,
        #   to make sure we can identify if they were specified)
        keep_braced_groups = (
            keep_braced_groups if keep_braced_groups is not None else False
        )
        keep_math_mode = keep_math_mode if keep_math_mode is not None else True

        if decoder is None:
            lw_context_db = pylatexenc.latex2text.get_default_latex_context_db()
            lw_context_db.add_context_category(
                "bibtexparse-default-context",
                prepend=True,
                macros=[
                    # Do not wrap urls in '< ... >'
                    MacroTextSpec("url", simplify_repl="%s")
                ],
            )

            decoder = LatexNodes2Text(
                # Use custom latex context
                latex_context=lw_context_db,
                # Optionally, do not remove curly braces
                keep_braced_groups=keep_braced_groups,
                # Optionally, decode math notation
                math_mode="verbatim" if keep_math_mode is True else "text",
            )

        self._decoder = decoder

    # docstr-coverage: inherited
    def metadata_key(self) -> str:
        return "latex_decoding"

    # docstr-coverage: inherited
    def _transform_python_value_string(self, python_string: str) -> str:
        # TODO this fails for invalid latex.
        #   We have to create modes to keep original or to create a failed block
        return self._decoder.latex_to_text(python_string)