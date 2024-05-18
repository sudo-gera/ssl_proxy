import pathlib
import asyncio
import logging
from functools import cache

from error_logger import error_logger


@error_logger
async def exec_command(*command, input=None):
    process = await asyncio.subprocess.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate(input=input)
    assert not await process.wait()


@error_logger
async def cert_init():
    certs = pathlib.Path(__file__).with_name('.certs')
    if not certs.exists():
        certs.mkdir()
    root_key = certs / 'ssl_proxy_root_CA.key'
    root_pem = certs / 'ssl_proxy_root_CA.pem'
    if not (root_key.exists()
        and root_pem.exists()):
        await exec_command('openssl', 'genrsa', '-out', root_key, '2048')
        await exec_command('openssl', 'req', '-x509', '-new', '-nodes','-key', root_key,
                  '-sha256', '-days', '9999', '-out', root_pem, '-subj', '/CN=ssl_proxy')
        logging.info(f'Created new root CA. You have to install {root_pem} as trusted in your system.')
    return root_key, root_pem

@cache
def lock_domain(domain):
    return asyncio.Lock()

@error_logger
async def cert_make(domain):
    async with lock_domain(domain):
        certs = pathlib.Path(__file__).with_name('.certs')
        root_key = certs / 'ssl_proxy_root_CA.key'
        root_pem = certs / 'ssl_proxy_root_CA.pem'
        if isinstance(domain, bytes):
            domain = domain.decode()
        domain_key = root_key.with_stem(domain)
        domain_csr = domain_key.with_suffix('.csr')
        domain_ext = domain_key.with_suffix('.ext')
        domain_crt = domain_key.with_suffix('.crt')
        if not (domain_key.exists() and domain_crt.exists() and domain_csr.exists() and domain_ext.exists()):
            await exec_command('openssl', 'genrsa', '-out', domain_key, '2048')
            await exec_command('openssl', 'req', '-new', '-key', domain_key, '-out', domain_csr, '-subj', '/CN=ssl_proxy')
            with domain_ext.open('w') as file:
                print('authorityKeyIdentifier=keyid,issuer', file=file)
                print('basicConstraints=CA:FALSE', file=file)
                print('keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment', file=file)
                print('subjectAltName = @alt_names', file=file)
                print('', file=file)
                print('[alt_names]', file=file)
                print(f'DNS.1 = {domain}', file=file)
            await exec_command('openssl', 'x509', '-req', '-in', domain_csr, '-CA', root_pem, '-CAkey', root_key,
                        '-CAcreateserial', '-out', domain_crt, '-days', '9999', '-sha256', '-extfile', domain_ext)
        return domain_crt, domain_key

