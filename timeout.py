import asyncio
import traceback
import typing

async def run_with_timeout(coro: typing.Coroutine[typing.Any, typing.Any, typing.Any], timeout: float) -> typing.Any:
    task = asyncio.create_task(coro)
    await asyncio.wait([task], timeout=timeout)
    if task.done():
        return task.result()
    task.cancel()
    raise asyncio.TimeoutError

async def get_with_timeout(queue, timeout):
    return await run_with_timeout(queue.get(), timeout) 

async def _test():
    try:
        print('begin')
        await asyncio.sleep(1)
        print('end')
    finally:
        print(traceback.format_exc())

async def _main():
    await run_with_timeout(_test(), 1.5)
    await run_with_timeout(_test(), 0.5)

if __name__ == '__main__':
    asyncio.run(_main())