import argparse
import asyncio
import itertools

import aiodns
import aiohttp

DEFAULT_BOUND = 1500
S3_NOT_FOUND_INDICATION = 's3-directional'
SEPARATORS = ("-", ".", "_", "")
QUERY_TYPE = 'CNAME'
NAMESERVERS = ['8.8.8.8', '8.8.4.4', '1.1.1.1']
CARES_KEEP_OPEN = 16
DNS_RETRIES = 4


async def fetch_bucket_gcp(bucket_name):
    try:
        async with session.head(f'http://storage.googleapis.com/{bucket_name}') as res:
            if res.status in {400, 404}:
                return None
            return f'gs://{bucket_name}'
    except aiohttp.ClientError:
        return None


async def fetch_bucket_s3(bucket_name):
    try:
        result = await resolver.query(f'{bucket_name}.s3.amazonaws.com', QUERY_TYPE)
        if S3_NOT_FOUND_INDICATION in result.cname:
            return None
        return f's3://{bucket_name}'
    except aiodns.error.DNSError:
        return None


def prefix_permutations(target, prefix, modifiers):
    yield f'{target}.{prefix}'
    yield f'{target}-{prefix}'
    yield f'{target}{prefix}'
    yield f'{prefix}.{target}'
    yield f'{prefix}-{target}'
    yield f'{prefix}{target}'


def mod_permutations(target, prefix, modifiers):
    for mod in modifiers:
        yield f'{target}-{prefix}-{mod}'
        yield f'{target}-{mod}-{prefix}'
        yield f'{target}.{prefix}.{mod}'
        yield f'{target}.{mod}.{prefix}'
        yield f'{target}.{prefix}-{mod}'
        yield f'{target}.{mod}-{prefix}'
        yield f'{target}-{prefix}.{mod}'
        yield f'{target}-{mod}.{prefix}'
        yield f'{target}-{prefix}{mod}'
        yield f'{target}-{mod}{prefix}'


def generate_buckets(target, prefixes, modifiers):
    yield target
    for name in prefixes:
        yield from mod_permutations(target, name, modifiers)
        yield from prefix_permutations(target, name, modifiers)


def bounded_as_completed(coros, bound):
    futures = [
        asyncio.ensure_future(c)
        for c in itertools.islice(coros, 0, bound)
    ]

    async def first_to_finish():
        while True:
            await asyncio.sleep(0)
            for f in futures:
                if f.done():
                    futures.remove(f)
                    try:
                        newf = next(coros)
                        futures.append(
                            asyncio.ensure_future(newf))
                    except StopIteration as e:
                        pass
                    return f.result()
    while len(futures) > 0:
        yield first_to_finish()


def unique_everseen(iterable, key=None):
    "List unique elements, preserving order. Remember all elements ever seen."
    # unique_everseen('AAAABBBCCDAABBB') --> A B C D
    # unique_everseen('ABBCcAD', str.lower) --> A B C D
    seen = set()
    seen_add = seen.add
    if key is None:
        for element in itertools.filterfalse(seen.__contains__, iterable):
            seen_add(element)
            yield element
    else:
        for element in iterable:
            k = key(element)
            if k not in seen:
                seen_add(k)
                yield element


async def main(target, prefixes, modifiers, bound=DEFAULT_BOUND):
    for res in bounded_as_completed(
            itertools.chain.from_iterable(
                (fetch_bucket_s3(name), fetch_bucket_gcp(name))
                for name in unique_everseen(generate_buckets(target, prefixes, modifiers))
            ),
            bound=bound
    ):
        result = await res
        if result:
            print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Yet Another S3 Enumerator')
    parser.add_argument('--target', '-t', required=True)
    parser.add_argument('--prefixes', '-p', type=argparse.FileType('r'),
                        default=open('common_prefixes.txt'))
    parser.add_argument('--modifiers', '-m', type=argparse.FileType('r'),
                        default=open('common_modifiers.txt'))
    parser.add_argument('--bound', '-b', type=int, default=DEFAULT_BOUND)
    namespace = parser.parse_args()

    loop = asyncio.get_event_loop()
    resolver = aiodns.DNSResolver(loop=loop,
                                  nameservers=NAMESERVERS,
                                  tries=DNS_RETRIES,
                                  flags=CARES_KEEP_OPEN)
    session = aiohttp.ClientSession()

    loop.run_until_complete(
        main(
            namespace.target,
            namespace.prefixes.read().splitlines(),
            namespace.modifiers.read().splitlines(),
            namespace.bound
        )
    )
    loop.run_until_complete(session.close())
