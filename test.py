import asyncio
from cocon_client import CoConClient
from pprint import pprint


async def handler(data: dict) -> None:
    print(data.__class__)
    pprint(data)


def handler_error(exc: Exception, data: dict) -> None:
    print(f"handler error: {exc}\n")
    pprint(data)


async def main() -> None:
    async with CoConClient(
        url="10.17.30.231", port=8890, handler=handler, on_handler_error=handler_error
    ) as cocon_server:
        while True:
            await asyncio.sleep(2)
            print(await cocon_server.send("GetCoconServerVersion"))


if __name__ == "__main__":
    asyncio.run(main())
