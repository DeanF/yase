import argparse
import asyncio
import itertools

import aiodns

DEFAULT_BOUND = 1500
S3_NOT_FOUND_INDICATION = 's3-directional'
SEPARATORS = ("-", ".", "_", "")
QUERY_TYPE = 'CNAME'
NAMESERVERS = ['8.8.8.8', '8.8.4.4', '1.1.1.1']
CARES_KEEP_OPEN = 16
DNS_RETRIES = 4


async def fetch_bucket(bucket_name):
    try:
        result = await resolver.query(f'{bucket_name}.s3.amazonaws.com', QUERY_TYPE)
        if S3_NOT_FOUND_INDICATION in result.cname:
            return False, bucket_name
        return True, bucket_name
    except aiodns.error.DNSError:
        return False, bucket_name


def generate_buckets(target, prefixes):
    yield target
    for name in prefixes:
        for c in SEPARATORS:
            yield f'{target}{c}{name}'
            yield f'{name}{c}{target}'


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


async def main(target, prefixes, bound=DEFAULT_BOUND):
    for res in bounded_as_completed(
            (fetch_bucket(name) for name in generate_buckets(target, prefixes)),
            bound=bound
    ):
        result = await res
        if result[0]:
            print(result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Yet Another S3 Enumerator')
    parser.add_argument('--target', '-t', required=True)
    parser.add_argument('--prefixes', '-p', type=argparse.FileType('r'),
                        default=open('common_prefixes.txt'))
    parser.add_argument('--bound', '-b', type=int, default=DEFAULT_BOUND)
    namespace = parser.parse_args()

    loop = asyncio.get_event_loop()
    resolver = aiodns.DNSResolver(loop=loop,
                                  nameservers=NAMESERVERS,
                                  tries=DNS_RETRIES,
                                  flags=CARES_KEEP_OPEN)

    loop.run_until_complete(
        main(
            namespace.target,
            namespace.prefixes.read().splitlines()
        )
    )
