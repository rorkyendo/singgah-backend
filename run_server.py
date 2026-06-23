import asyncio
import sys

# On Windows, default ProactorEventLoop cannot spawn subprocesses from the
# same event loop that runs FastAPI. Playwright needs subprocess to launch
# Chromium. Force SelectorEventLoop before importing anything else.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        loop="asyncio",
        use_colors=True,
    )
