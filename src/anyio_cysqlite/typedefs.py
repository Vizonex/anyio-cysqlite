import sys
import types
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeAlias, TypeVar

from cysqlite import _cysqlite
from cysqlite.metadata import Column, ForeignKey, Index, View

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
# NOTE: Needed for typehinting pragma function
SENTINEL: object = _cysqlite.SENTINEL

# Cysqlite doesn't have good typehints avalible yet so we have to do a bit
# Of hacking ourselves, The most optimal solution was to make
# mimics of the function signatures as abstract classes to get
# around the issue.
# SEE: https://github.com/coleifer/cysqlite/issues/1

# There is currently some hope that we don't have to rely on all of these 
# anymore, SEE: https://github.com/coleifer/cysqlite/pull/2

# Know that these ABCs are not perfect but they try their best to
# typehint as a workaround this very bad issue.


class _callable_context_manager(AbstractContextManager):
    @abstractmethod
    def __call__(self, fn: Callable[P, T]) -> Callable[P, T]: ...


class _Atomic(_callable_context_manager):
    @abstractmethod
    def __init__(
        self, conn: "_Connection", lock: _IsolationLevel | str = None
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
        self, conn: "_Connection", sid: str | None = None
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
        self, conn: "_Connection", lock: _IsolationLevel = None
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


class _Connection(_callable_context_manager):
    """
    Used as an abstraction of `cysqlite.Connection` due to it's
    lack of typehint support.
    """

    @abstractmethod
    def __init__(
        self,
        database: str | Path,
        flags: int | None = None,
        timeout: float = 5.0,
        vfs: str | None = None,
        uri: bool = False,
        cached_statements: int = 100,
        extensions: bool = True,
        row_factory: Callable[..., "_Row"] | None = None,
        autoconnect: bool = True,
    ) -> None: ...

    @property
    def callback_error(self) -> BaseException | None: ...

    @abstractmethod
    def atomic(self) -> _Atomic: ...
    @abstractmethod
    def attach(self, filename: str, name: str) -> None: ...
    @abstractmethod
    def authorizer(self, fn: Callable[..., Any]) -> None: ...
    def autocommit(self) -> int: ...
    @abstractmethod
    def backup(
        self,
        dest: "_Connection",
        pages: int | None = None,
        name: str | None = None,
        progress: Callable[[int, int, bool], None] | None = None,
        src_name: str | None = None,
    ) -> None: ...
    @abstractmethod
    def backup_to_file(
        self,
        filename: str,
        pages: int | None = None,
        name: str | None = None,
        progress: Callable[[int, int, bool], None] | None = None,
        src_name: str | None = None,
    ) -> None: ...
    @abstractmethod
    def begin(self, lock: _IsolationLevel = None) -> None: ...
    # def blob_open(self, *args, **kwargs): ... # Todo
    @abstractmethod
    def changes(self) -> int: ...
    @abstractmethod
    def checkpoint(
        self,
        full: bool = False,
        truncate: bool = False,
        restart: bool = False,
        name: str | None = None,
    ) -> tuple[int, int]: ...
    @abstractmethod
    def close(self): ...
    @abstractmethod
    def commit(self) -> None: ...
    @abstractmethod
    def commit_hook(self, fn: Callable[..., None]) -> None: ...
    @abstractmethod
    def connect(self) -> bool: ...
    @abstractmethod
    def converter(self, *args, **kwargs): ...
    @abstractmethod
    def create_aggregate(
        self,
        agg: Callable[..., Any],
        name: str | None = None,
        nargs: int = -1,
        deterministic: bool = True,
    ) -> None: ...
    @abstractmethod
    def create_collation(
        self, fn: Callable[..., Any], name: str | None = None
    ) -> None: ...
    @abstractmethod
    def create_function(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        nargs=-1,
        deterministic: bool = True,
    ): ...
    @abstractmethod
    def create_window_function(
        self,
        fn: Callable[..., Any],
        name: str | None = None,
        nargs=-1,
        deterministic: bool = True,
    ): ...
    @abstractmethod
    def cursor(self) -> "_Cursor": ...
    @abstractmethod
    def database_list(self) -> tuple[Any, Any]: ...
    @abstractmethod
    def detach(self, name: str) -> None: ...
    @abstractmethod
    def execute(self, sql: str, params: _Parameters | None = None) -> Self: ...
    @abstractmethod
    def execute_one(
        self, sql: str, params: _Parameters | None = None
    ) -> "_Row | Any": ...
    @abstractmethod
    def executemany(
        self, sql: str, params: Sequence[_Parameters] | None = None
    ) -> "_Cursor": ...
    @abstractmethod
    def execute_scalar(
        self, sql: str, params: _Parameters | None = None
    ) -> Any: ...
    @abstractmethod
    def execute_simple(
        self, sql: str, callback: Callable[..., Any] | None = None
    ) -> None: ...
    @abstractmethod
    def executescript(self, sql: str) -> "_Cursor": ...
    @abstractmethod
    def finalize_statements(self, finalize: bool = False) -> None: ...
    @abstractmethod
    def get_columns(
        self, table: str, database: str | None = None
    ) -> list[Column]: ...
    @abstractmethod
    def get_foreign_keys(
        self, table: str, database: str | None = None
    ) -> list[ForeignKey]: ...
    @abstractmethod
    def get_foreign_keys_enabled(self) -> bool: ...
    @abstractmethod
    def get_indexes(
        self, table: str, database: str | None = None
    ) -> list[Index]: ...
    @abstractmethod
    def get_load_extension(self) -> bool: ...
    @abstractmethod
    def get_primary_keys(
        self, table: str, database: str | None = None
    ) -> list[str]: ...
    @abstractmethod
    def get_stmt_usage(self) -> tuple[int, int]: ...
    @abstractmethod
    def get_tables(self, database: str | None = None) -> list["_Row"]: ...
    @abstractmethod
    def get_triggers_enabled(self) -> int: ...
    @abstractmethod
    def get_views(self, database: str | None = None) -> list[View]: ...
    @abstractmethod
    def getlimit(self, category: int) -> int: ...
    @abstractmethod
    def interrupt(self) -> None: ...
    @abstractmethod
    def is_closed(self) -> bool: ...
    @abstractmethod
    def last_insert_rowid(self) -> int: ...  # long long in C...
    @abstractmethod
    def load_extension(self, name: str) -> None: ...
    @abstractmethod
    def optimize(
        self,
        debug: bool = False,
        run_tables: bool = True,
        set_limit: bool = True,
        check_table_sizes: bool = False,
        dry_run: bool = False,
    ) -> None: ...
    @abstractmethod
    def pragma(
        self,
        key: str,
        value: Any = ...,
        database: str | None = None,
        multi: bool = False,
    ) -> Any | Sequence[Any]: ...
    @abstractmethod
    def progress(
        self, fn: Callable[[int, int, bool], None], n: int = 1
    ) -> None: ...
    @abstractmethod
    def register_converter(self, *args, **kwargs): ...
    @abstractmethod
    def rollback(self) -> None: ...
    @abstractmethod
    def rollback_hook(self, *args, **kwargs): ...
    @abstractmethod
    def savepoint(self, sid: str | None = None): ...
    @abstractmethod
    def set_autocheckpoint(self, n: int) -> None: ...
    @abstractmethod
    def set_busy_handler(self, timeout: float = 5.0) -> None: ...
    @abstractmethod
    def set_foreign_keys_enabled(self, enabled: int | bool): ...
    @abstractmethod
    def set_load_extension(self, enabled: int | bool): ...
    @abstractmethod
    def set_main_db_name(self, name: str | bytes): ...
    @abstractmethod
    def set_shared_cache(self, enabled: int | bool): ...
    @abstractmethod
    def set_triggers_enabled(self, enabled: int | bool): ...
    @abstractmethod
    def setlimit(self, category: int, limit: int): ...
    @abstractmethod
    def status(self, flag: int) -> tuple[int, int]: ...
    @abstractmethod
    def table_column_metadata(
        self,
        table: str | bytes,
        column: str | bytes,
        database: str | None = None,
    ): ...
    @abstractmethod
    def total_changes(self) -> int: ...
    @abstractmethod
    def trace(self, fn: Callable[..., Any], mask: int = 2) -> None: ...
    @abstractmethod
    def transaction(self, lock: _IsolationLevel = None): ...
    @abstractmethod
    def unregister_converter(self, data_type: str) -> bool: ...
    @abstractmethod
    def update_hook(self, fn: Callable[..., Any]): ...
    @abstractmethod
    def __enter__(self) -> Self: ...
    @abstractmethod
    def __exit__(
        self,
        type: type[BaseException] | None,
        value: BaseException | None,
        traceback: types.TracebackType | None,
    ): ...


_Connection.register(_cysqlite.Connection)


class _Cursor(_callable_context_manager):
    @abstractmethod
    def __init__(self, conn: _Connection) -> None: ...
    @abstractmethod
    def close(self) -> None: ...
    @abstractmethod
    def columns(
        self,
    ) -> list[
        Any
    ]: ...  # until I can make a better typehint this is temporary.
    @abstractmethod
    def execute(self, sql: str, params: _Parameters | None = None) -> Self: ...
    @abstractmethod
    def executemany(
        self, sql: str, params: Sequence[_Parameters] | None = None
    ) -> Self: ...
    @abstractmethod
    def fetchall(self) -> list["_Row"]: ...
    @abstractmethod
    def fetchone(self) -> "_Row": ...
    @abstractmethod
    def value(self) -> Any: ...
    @abstractmethod
    def __next__(self) -> "_Row": ...


_Cursor.register(_cysqlite.Cursor)


class _Row(_callable_context_manager):
    @abstractmethod
    def __init__(self, cursor: _Cursor, data: tuple[Any, ...]) -> None: ...

    @abstractmethod
    def __getitem__(self, key: int | str) -> Any: ...

    @abstractmethod
    def __getattr__(self, name: str) -> Any: ...

    @abstractmethod
    def __iter__(self) -> Any: ...

    @abstractmethod
    def __len__(self) -> int: ...

    @abstractmethod
    def __repr__(self) -> str: ...

    @abstractmethod
    def __eq__(self, other: "_Row | tuple[Any, ...]") -> bool: ...

    @abstractmethod
    def __ne__(self, other: "_Row | tuple[Any, ...]") -> bool: ...

    @abstractmethod
    def __hash__(self) -> int: ...

    @abstractmethod
    def keys(self) -> list[str]: ...

    @abstractmethod
    def values(self) -> list[Any]: ...

    @abstractmethod
    def items(self) -> list[tuple[str, Any]]: ...

    @abstractmethod
    def as_dict(self) -> dict[str, Any]: ...


_Row.register(_cysqlite.Row)
