import os
import logging
import functools
import traceback
import asyncio

LOGLEVEL = os.environ.get('LOGLEVEL', 'INFO').upper()
logging.basicConfig(
    level=LOGLEVEL,
    format='%(asctime)s %(levelname)s: %(message)s'
)


def error_logger(func):
    async def awaiter(r):
        try:
            r = await r
            return r
        except Exception:
            logging.debug(f'{func}:\n{traceback.format_exc()}')
    @functools.wraps(func)
    def wrapper(*a,**s):
        try:
            r=func(*a,**s)
            if asyncio.iscoroutine(r):
                return awaiter(r)
            return r
        except Exception:
            logging.debug(f'{func}:\n{traceback.format_exc()}')
    return wrapper

