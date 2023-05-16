import asyncio

from UnlimitedChatGPTWebAPI import ChatSession


async def main():
    async with ChatSession() as session:
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
