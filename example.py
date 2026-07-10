import asyncio
from k4f import KimiAPI


async def main():
    api = KimiAPI(
        auth_token="your-kimi-auth-jwt-here",
    )

    # Upload a file
    print("Uploading file...")
    upload = await api.upload_file("example.py")
    file_id = upload["file"]["id"]
    print(f"File ID: {file_id}")

    # Wait for parsing to complete
    print("Waiting for parse...")
    while True:
        progs = await api.get_file_parse_progress([file_id])
        status = progs[0]["status"]
        print(f"  status: {status}")
        if status in ("PROCESS_STATUS_SUCCESS", "PROCESS_STATUS_FAILED"):
            break
        await asyncio.sleep(0.5)

    # Chat with the file as context
    print("\nChat with file context:")
    async for chunk in api.chat_stream(
        content="summarize this file",
        file_ids=[file_id],
    ):
        print(chunk["content"], end="", flush=True)
    print(f"\n(chat_id: {api.last_chat_id})\n")

    await api.close()


asyncio.run(main())
