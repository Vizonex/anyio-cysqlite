import sys
import types
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeAlias, TypeVar

import cysqlite
from cysqlite.metadata import *

if sys.version_info >= (3, 12):
    from collections.abc import Buffer
else:
    from typing_extensions import Buffer

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

# cysqlite maintainer currently shows Zero intrest in the idea
# of utilizing typehints so that users don't have to second guess
# and validate code so we must do everything ourselves
# luckily, sqlite3 has a typeshed stubfile with pleantly of helpful information
# that we can safely utilize.

_SqliteData: TypeAlias = str | Buffer | int | float | None
_AdaptedInputData: TypeAlias = _SqliteData | Any
_Parameters: TypeAlias = (
    Sequence[_AdaptedInputData] | Mapping[str, _AdaptedInputData]
)
_IsolationLevel: TypeAlias = (
    Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None
)

T = TypeVar("T")
P = ParamSpec("P")


# Cysqlite doesn't have good typehints avalible yet so we have to do a bit
# Of hacking ourselves, The most optimal solution was to make
# mimics of the function signatures as abstract classes to get around the issue
# SEE: https://github.com/coleifer/cysqlite/issues/1

# NOTE: in 0.3.1+ coleifer and cysqlite maintainers takes my advice seriously.


# Know that these ABCs are not perfect but they try their best to typehint as a
# workaround
# this very bad issue.


class _callable_context_manager(ABC):
    @abstractmethod
    def __call__(self, fn: Callable[P, T]) -> Callable[P, T]: ...


class _Atomic(_callable_context_manager):
    @abstractmethod
    def __init__(
        self, conn: "cysqlite.Connection", lock: _IsolationLevel | str = None
    ) -> None: ...
    @abstractmethod
    def __enter__(self) -> Self: ...
    @abstractmethod
    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None: ...

    @abstractmethod
    def commit(self, begin: bool = True) -> None: ...
    @abstractmethod
    def rollback(self, begin: bool = True) -> None: ...


class _Savepoint(_callable_context_manager):
    @abstractmethod
    def __init__(
        self, conn: "cysqlite.Connection", sid: str | None = None
    ) -> None: ...
    @abstractmethod
    def commit(self, begin: bool = True) -> None: ...
    @abstractmethod
    def rollback(self) -> None: ...
    @abstractmethod
    def __enter__(self) -> Self: ...
    @abstractmethod
    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None: ...


class _Transaction(_callable_context_manager):
    @abstractmethod
    def __init__(
        self, conn: "cysqlite.Connection", lock: _IsolationLevel = None
    ) -> None: ...
    @abstractmethod
    def commit(self, begin: bool = True) -> None: ...
    @abstractmethod
    def rollback(self, begin: bool = True) -> None: ...
    @abstractmethod
    def __enter__(self) -> Self: ...
    @abstractmethod
    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> bool | None: ...
