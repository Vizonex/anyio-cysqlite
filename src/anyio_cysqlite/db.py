import sys
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractContextManager, asynccontextmanager
from functools import partial, wraps
from logging import Logger, getLogger
from pathlib import Path
from types import TracebackType
from typing import Any, Generic, TypeVar

import cysqlite
from anyio import (
    AsyncContextManagerMixin,
    CapacityLimiter,
)
from anyio.to_thread import run_sync

from .typedefs import (
    SENTINEL,
    P,
    T,
    _Atomic,
    _Connection,
    _Cursor,
    _IsolationLevel,
    _Parameters,
    _Row,
    _Savepoint,
    _Transaction,
)

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self  # pragma: nocover

if sys.version_info >= (3, 13):
    from typing import TypeVarTuple, Unpack
else:
    from typing_extensions import TypeVarTuple, Unpack

Ts = TypeVarTuple("Ts", default=())
_RC = TypeVar("_RC", bound=AbstractContextManager)


# NOTE: anyio's AsyncContextManagerMixin can't be used because we
# need to bind exiting objects around __aexit__
class AsyncAction(Generic[_RC]):
    """helper for handling other wrappers like atomic,
    savepoint and transaction"""

    # NOTE: you can subclass AsyncAction's subclasses it's just not recommended
    __slots__ = ("_real", "_limiter", "__weakref__")

    def __init__(self, real: _RC, limiter: CapacityLimiter):
        self._real = real
        self._limiter = limiter

    async def __aenter__(self):
        # setting self._real here for Atomic's sake since it can be hybrid.
        self._real: _RC = await run_sync(
            self._real.__enter__, limiter=self._limiter
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return await run_sync(
            self._real.__exit__,
            exc_type,
            exc_val,
            exc_tb,
            limiter=self._limiter,
        )

    def __call__(self, func: Callable[P, Awaitable[T]]):
        """wraps function to the database note: it's limited to non-async
        generators"""

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async with self:
                return await func(*args, **kwargs)

        return wrapper

    async def run(
        self, func: Callable[[Unpack[Ts]], Awaitable[T]], *args: Unpack[Ts]
    ) -> T:
        """
        Custom function that Runs context manager inside a function
        without having to setup a wrapper when database is not
        outside of the main funciton
        """
        async with self:
            return await func(*args)


class Transaction(AsyncAction[_Transaction]):
    async def commit(self, begin: bool = True) -> None:
        await run_sync(self._real.commit, begin, limiter=self._limiter)

    async def rollback(self, begin: bool = True) -> None:
        await run_sync(self._real.rollback, begin, limiter=self._limiter)


class Savepoint(AsyncAction[_Savepoint]):
    async def commit(self, begin: bool = True):
        await run_sync(self._real.commit, begin, limiter=self._limiter)

    async def rollback(self):
        await run_sync(self._real.rollback, limiter=self._limiter)


class Atomic(AsyncAction[_Atomic]):
    async def commit(self, begin: bool = True):
        await run_sync(self._real.commit, begin, limiter=self._limiter)

    # it varies. hence *args and not begin: bool = True
    async def rollback(self, *args):
        await run_sync(self._real.rollback, *args, limiter=self._limiter)


# inspired by sqlite-anyio with a few of my own tweaks

# TODO: Organize functions in a-z order.


class Cursor:
    def __init__(
        self,
        real_cursor: _Cursor,
        limiter: CapacityLimiter,
        exception_handler: Callable[
            [type[BaseException], BaseException, TracebackType, Logger], bool
        ]
        | None,
        log: Logger,
    ) -> None:
        self._real_cursor = real_cursor
        self._limiter = limiter
        self._exception_handler = exception_handler
        self._log = log

        # Deques can maker iterating a bit faster over the
        # standard list object as linked lists are known to speed
        # things up.
        self._buffer: deque[Any | _Row] = deque()

    @property
    def description(self) -> Any:
        return self._real_cursor.description

    @property
    def lastrowid(self) -> int:
        return self._real_cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._real_cursor.rowcount

    async def close(self) -> None:
        await run_sync(self._real_cursor.close, limiter=self._limiter)

    async def execute(
        self, sql: str, parameters: Sequence[Any] = (), /
    ) -> Self:
        await run_sync(
            self._real_cursor.execute, sql, parameters, limiter=self._limiter
        )
        return self

    async def executemany(
        self, sql: str, parameters: Sequence[Any], /
    ) -> Self:
        await run_sync(
            self._real_cursor.executemany,
            sql,
            parameters,
            limiter=self._limiter,
        )
        return self

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return await run_sync(
            self._real_cursor.fetchall, limiter=self._limiter
        )

    async def fetchone(self) -> _Row | None:
        return await run_sync(
            self._real_cursor.fetchone, limiter=self._limiter
        )

    async def scalar(self) -> Any:
        return await run_sync(self._real_cursor.scalar, limiter=self._limiter)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.close()
        if exc_val is None:
            return None

        assert exc_type is not None
        assert exc_val is not None
        assert exc_tb is not None
        exception_handled = False
        if self._exception_handler is not None:
            exception_handled = self._exception_handler(
                exc_type, exc_val, exc_tb, self._log
            )
        return exception_handled

    async def fetchmany(self, size: int = 100) -> list[_Row | Any]:
        # next part comes form cysqlite/aio.py
        def _fetch():
            rows = list()
            for _ in range(size):
                try:
                    rows.append(self._real_cursor.__next__())
                except StopIteration:
                    break
            return rows

        return await run_sync(_fetch, limiter=self._limiter)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._buffer:
            self._buffer.extend(await self.fetchmany())
            if not self._buffer:
                raise StopAsyncIteration
        return self._buffer.popleft()


class Connection:
    def __init__(
        self,
        real_connection: _Connection,
        exception_handler: Callable[
            [type[BaseException], BaseException, TracebackType, Logger], bool
        ]
        | None = None,
        log: Logger | None = None,
    ) -> None:
        self._conn = real_connection
        self._exception_handler = exception_handler
        self._log = log or getLogger(__name__)
        self._limiter = CapacityLimiter(1)

    def _cursor_factory(self, cursor: _Cursor) -> "Cursor":
        return Cursor(
            cursor,
            self._limiter,
            exception_handler=self._exception_handler,
            log=self._log,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        await self.close()

        if exc_val is None:
            return None

        assert exc_type is not None
        assert exc_val is not None
        assert exc_tb is not None

        exception_handled = False
        if self._exception_handler is not None:
            exception_handled = self._exception_handler(
                exc_type, exc_val, exc_tb, self._log
            )
        return exception_handled

    async def backup(
        self,
        dest: "Connection",
        pages: int | None = None,
        name: str | None = None,
        progress: Callable[[int, int, bool], None] | None = None,
        src_name: str | None = None,
    ) -> None:
        return await run_sync(
            self._conn.backup,
            dest._conn,
            pages,
            name,
            progress,
            src_name,
            limiter=self._limiter,
        )

    async def backup_to_file(
        self,
        filename: str,
        pages: int | None = None,
        name: str | None = None,
        progress: Callable[[int, int, bool], None] | None = None,
        src_name: str | None = None,
    ) -> None:
        await run_sync(
            self._conn.backup_to_file,
            filename,
            pages,
            name,
            progress,
            src_name,
            limiter=self._limiter,
        )

    async def begin(self, lock: _IsolationLevel = None) -> None:
        await run_sync(self._conn.begin, lock, limiter=self._limiter)

    async def execute(
        self, sql: str, parameters: _Parameters | None = None, /
    ) -> "Cursor":
        cursor = await run_sync(
            self._conn.execute,
            sql,
            parameters,
            limiter=self._limiter,
        )
        return self._cursor_factory(cursor)

    async def executemany(
        self, sql: str, seq_of_params: Sequence[_Parameters] | None = None
    ) -> "Cursor":
        cursor = await run_sync(
            self._conn.executemany, sql, seq_of_params, limiter=self._limiter
        )
        return self._cursor_factory(cursor)

    async def executescript(self, sql: str) -> "Cursor":
        cursor = await run_sync(
            self._conn.executescript, sql, limiter=self._limiter
        )
        return self._cursor_factory(cursor)

    async def close(self) -> None:
        await run_sync(self._conn.close, limiter=self._limiter)

    async def checkpoint(
        self,
        full: bool = False,
        truncate: bool = False,
        restart: bool = False,
        name: str | None = None,
    ) -> tuple[int, int]:
        return await run_sync(
            self._conn.checkpoint,
            full,
            truncate,
            restart,
            name,
            limiter=self._limiter,
        )

    async def commit(self) -> None:
        await run_sync(self._conn.commit, limiter=self._limiter)

    async def rollback(self) -> None:
        await run_sync(self._conn.rollback, limiter=self._limiter)

    async def cursor(self) -> "Cursor":
        return self._cursor_factory(
            await run_sync(self._conn.cursor, limiter=self._limiter)
        )

    async def execute_one(self, sql: str, params: _Parameters | None = None):
        return await run_sync(
            self._conn.execute_one, sql, params, limiter=self._limiter
        )

    async def execute_scalar(
        self, sql: str, params: _Parameters | None = None
    ):
        return await run_sync(
            self._conn.execute_scalar, sql, params, limiter=self._limiter
        )

    async def autocommit(self) -> int:
        return await run_sync(self._conn.autocommit, limiter=self._limiter)

    def atomic(self) -> Atomic:
        """Opens a new atomic function, this can be used as both an async
        wrapper or wrappable function"""
        return Atomic(self._conn.atomic(), self._limiter)

    def savepoint(self, sid: str | None = None) -> Savepoint:
        """Opens a new savepoint, this can be used as both an async wrapper
        or wrappable function"""
        return Savepoint(self._conn.savepoint(sid), self._limiter)

    def transaction(self, lock: _IsolationLevel = None):
        """Opens a new transaction, this can be used as both an async wrapper
        or wrappable function"""
        return Transaction(self._conn.transaction(lock), self._limiter)

    async def last_insert_rowid(self) -> int:
        return await run_sync(
            self._conn.last_insert_rowid, limiter=self._limiter
        )

    @property
    def in_transaction(self):
        return self._conn.in_transaction

    async def status(self, flag: int) -> tuple[int, int]:
        return await run_sync(self._conn.status, flag, limiter=self._limiter)

    async def pragma(
        self,
        key: str,
        value: Any = SENTINEL,
        database: str | None = None,
        multi: bool = False,
    ) -> Any | Sequence[Any]:
        return await run_sync(
            self._conn.pragma,
            key,
            value,
            database,
            multi,
            limiter=self._limiter,
        )


async def connect(
    database: str | Path,
    flags: int | None = None,
    timeout: float = 5.0,
    vfs: str | None = None,
    uri: bool = False,
    cached_statements: int = 100,
    extensions: bool = True,
    row_factory: Callable[..., "_Row"] | None = None,
    autoconnect: bool = True,
    log: Logger | None = None,
    exception_handler: Callable[
        [type[BaseException], BaseException, TracebackType, Logger], bool
    ]
    | None = None,
) -> Connection:
    """
    Open a Connection to the provided database.

    :param database: database filename or ':memory:' for an in-memory
        database.
    :type database: str | pathlib.Path
    :param flags: control how database is opened. See Sqlite Connection Flags.
    :type flags: int | None
    :param timeout: seconds to retry acquiring write lock before raising a
        OperationalError when table is locked.
    :type timeout: float
    :param vfs: VFS to use, optional.
    :type vfs: str | None
    :param uri: Allow connecting using a URI.
    :type uri: bool
    :param cached_statements: Size of statement cache.
    :type cached_statements: int
    :param extensions: Support run-time loadable extensions.
    :type extensions: bool
    :param row_factory: Factory implementation for constructing rows, e.g. Row
    :type row_factory: Callable[..., _T] | None
    :param autoconnect: Open connection when initiated
    :type autoconnect: bool
    :rtype: Connection
    :returns: Connection to database under an anyio asynchronous wrapper
    """
    conn = await run_sync(
        partial(
            cysqlite.connect,
            database=database,
            flags=flags,
            timeout=timeout,
            vfs=vfs,
            uri=uri,
            cached_statements=cached_statements,
            extensions=extensions,
            row_factory=row_factory or cysqlite.Row,
            autoconnect=autoconnect,
        )
    )
    return Connection(conn, exception_handler, log)


def exception_logger(
    exc_type: type[BaseException] | None,
    exc_val: BaseException | None,
    exc_tb: TracebackType | None,
    log: Logger,
) -> bool:
    """An exception handler that logs the exception and discards it."""
    log.error("SQLite exception", exc_info=exc_val)
    return True  # the exception was handled
