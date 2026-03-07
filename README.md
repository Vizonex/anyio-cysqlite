<img src="https://raw.githubusercontent.com/Vizonex/anyio-cysqlite/main/anyio-cysqlite-logo.PNG"/>

# anyio-cysqlite
A Bidning for cysqlite that makes the database asynchronous
with any asynchronous library that can be binded to anyio 
meaning that it will work with many server implementations and applications including FastAPI, Starlette and Litestar to name a few server libraries.

```python
from anyio_cysqlite import connect


async def main():
    async with await connect("cysqlite.db") as db:
        await db.execute('create table IF NOT EXISTS data (k, v)')

        async with db.atomic():
            await db.executemany('insert into data (k, v) values (?, ?)',
                           [(f'k{i:02d}', f'v{i:02d}') for i in range(10)])
            print(await db.last_insert_rowid())  # 10.

        curs = await db.execute('select * from data')
        async for row in curs:
            print(row)  # e.g., ('k00', 'v00')

        # We can use named parameters with a dict as well.
        row = await db.execute_one('select * from data where k = :key and v = :val',
                             {'key': 'k05', 'val': 'v05'})
        print(row)  # ('k05', 'v05')

        await db.close()

if __name__ == "__main__":
    import anyio
    anyio.run(main)
```

## Updated functionality is better
When it comes to database execution updated functionality normally results in better performance such as providing wrappers for `atomic`, `transaction`, and `savepoint` functions which the standard sqlite3 library doesn't currently have. Instead of having a completely seperate thread for the database all operations are done using the anyio's `CapacityLimiter` and `run_sync` making the database less resource heavy.


## Batteries included
Unlike cysqlite (As of currently), this library retains access to typehints right out of the box making the library less of a function and attribute guessing game.



