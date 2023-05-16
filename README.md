## UnlimitedChatGPTWebAPI

Resolve Cloudflare Challenge To use ChatGPT Web API

### Installation

```shell
pip3 install UnlimitedChatGPTWebAPI
```

then you should run `playwright install chromium`

> For windows,  maybe you should use it -> `playwright install-deps chromium`

### Configuration

1. Make sure your network or agent can access `https://chat.openai.com`
2. Please make sure that the VPS RAM is not too small.

### Usage

#### Basic example

```python
import asyncio

from UnlimitedChatGPTWebAPI import ChatSession


async def main():
    async with ChatSession(proxies="socks5://localhost:7890") as session:
        # or use this if you want to use the same session for multiple requests
        # example:
        # session = ChatSession(proxies="socks5://localhost:7890")
        # await session.init_page()
        async with session.fetch(
            method="GET",
            url="/backend-api/models",
            headers={"Authorization": "Bearer xxx"}
        ) as resp:
            print(await resp.json())

if __name__ == "__main__":
    asyncio.run(main())

```

#### Streaming example

```python
import asyncio

from UnlimitedChatGPTWebAPI import ChatSession


async def main():
    async with ChatSession(proxies="socks5://localhost:7890") as session:
        # or use this if you want to use the same session for multiple requests
        # example:
        # session = ChatSession(proxies="socks5://localhost:7890")
        # await session.init_page()
        async with session.fetch(
            method="GET",
            url="/backend-api/models",
            headers={"Authorization": "Bearer xxx"}
        ) as resp:
            data = b""
            async for chunk in resp.iter_chunked():
                data += chunk
            print(data.decode())

if __name__ == "__main__":
    asyncio.run(main())

```

