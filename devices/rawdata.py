from __future__ import annotations

import struct
from dataclasses import dataclass
from functools import cache
from inspect import get_annotations
from typing import Annotated, ClassVar, TypeVar, get_args, get_origin

T = TypeVar("T", bound="RawData")


class RawData:
    """Kleine Helper-Basis zum Parsen fixer Binärstrukturen via typing.Annotated."""

    _STRUCT_FMT: ClassVar[str]
    SIZE: ClassVar[int]

    def __init_subclass__(cls) -> None:
        format_str = list(getattr(cls, "_FULL_STRUCT_FMT", ["<"]))
        for name, annotation in get_annotations(cls, eval_str=True).items():
            if get_origin(annotation) is Annotated:
                _, *metadata = get_args(annotation)
                if not metadata:
                    continue
                format_str.append(metadata[0])
                setattr(cls, name, None)

        dataclass(cls)
        cls._FULL_STRUCT_FMT = format_str
        cls._STRUCT_FMT = "".join(format_str)
        cls.SIZE = struct.calcsize(cls._STRUCT_FMT)

    @classmethod
    def from_bytes(cls: type[T], data: bytes) -> T:
        return cls(*cls.unpack(data))

    @classmethod
    def unpack(cls, data: bytes):
        struct_fmt = cls._STRUCT_FMT
        size = cls.SIZE
        if (data_len := len(data)) < cls.SIZE:
            struct_fmt, size = cls._fit_struct_to_data(data_len)
        return struct.unpack(struct_fmt, data[:size])

    @classmethod
    @cache
    def _fit_struct_to_data(cls, data_len: int) -> tuple[str, int]:
        format_str = list(cls._STRUCT_FMT)
        while format_str:
            struct_fmt = "".join(format_str)
            size = struct.calcsize(struct_fmt)
            if size <= data_len:
                return struct_fmt, size
            format_str.pop()
        return "<", 0
