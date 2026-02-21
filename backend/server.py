from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import json
import asyncio
import httpx
import base64
import re
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime, timezone
import time
import anthropic
import traceback

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ============================================
# LOGGING SETUP (PRODUCTION READY)
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("gitopedia")


# ============================================
# HELPERS
# ============================================

def new_request_id():
    return str(uuid.uuid4())


def sse_event(event_type: str, payload: dict):

    return (
        f"event: {event_type}\n"
        f"data: {json.dumps(payload)}\n\n"
    )


async def mongo_debug(name: str, coro, request_id=None):

    start = time.time()

    try:

        result = await coro

        duration = time.time() - start

        logger.info(
            f"[REQ:{request_id}] [DB] {name} took {duration:.3f}s"
        )

        return result

    except Exception:

        logger.exception(
            f"[REQ:{request_id}] [DB ERROR] {name}"
        )

        raise


# ============================================
# FIREBASE
# ============================================

import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

firebase_cred = credentials.Certificate(
    str(ROOT_DIR / "firebase_config.json")
)

if not firebase_admin._apps:
    firebase_admin.initialize_app(firebase_cred)


# ============================================
# DATABASE
# ============================================

mongo_client = AsyncIOMotorClient(
    os.environ["MONGO_URL"],
    maxPoolSize=100,
    minPoolSize=10,
)

db = mongo_client[os.environ["DB_NAME"]]


# ============================================
# FASTAPI INIT
# ============================================

app = FastAPI()
api_router = APIRouter(prefix="/api")

security = HTTPBearer(auto_error=False)


# ============================================
# REQUEST LOGGING MIDDLEWARE
# ============================================

@app.middleware("http")
async def request_logging(request: Request, call_next):

    request_id = new_request_id()

    request.state.request_id = request_id

    start = time.time()

    logger.info(
        f"[REQ:{request_id}] START {request.method} {request.url}"
    )

    try:

        response = await call_next(request)

        duration = time.time() - start

        logger.info(
            f"[REQ:{request_id}] END status={response.status_code} "
            f"duration={duration:.3f}s"
        )

        return response

    except Exception:

        logger.exception(
            f"[REQ:{request_id}] FAILED"
        )

        raise


# ============================================
# AUTH
# ============================================

async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
):

    request_id = request.state.request_id

    if not creds:
        raise HTTPException(401, "Auth required")

    try:

        decoded = firebase_auth.verify_id_token(creds.credentials)

        return decoded

    except Exception:

        logger.exception(
            f"[REQ:{request_id}] Auth failed"
        )

        raise HTTPException(401, "Invalid token")


# ============================================
# GITHUB FETCH
# ============================================

async def fetch_github_data(owner, repo, request_id):

    url = f"https://api.github.com/repos/{owner}/{repo}"

    logger.info(
        f"[REQ:{request_id}] Fetch GitHub repo {owner}/{repo}"
    )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30)
    ) as client:

        resp = await client.get(url)

        if resp.status_code != 200:

            logger.error(
                f"[REQ:{request_id}] GitHub error {resp.status_code}"
            )

            raise HTTPException(
                502,
                "GitHub error"
            )

        logger.info(
            f"[REQ:{request_id}] GitHub rate remaining="
            f"{resp.headers.get('X-RateLimit-Remaining')}"
        )

        return resp.json()


# ============================================
# LLM GENERATION
# ============================================

async def generate_report_content(data, request_id):

    prompt = f"Analyze repo: {data.get('full_name')}"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if not anthropic_key:
        raise HTTPException(500, "Missing ANTHROPIC_API_KEY")

    client = anthropic.AsyncAnthropic(
        api_key=anthropic_key,
        timeout=httpx.Timeout(
            connect=10,
            read=600,
            write=10,
            pool=10,
        ),
    )

    logger.info(
        f"[REQ:{request_id}] LLM call started"
    )

    try:

        response = await asyncio.wait_for(

            client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            ),

            timeout=600,
        )

        content = response.content[0].text

        logger.info(
            f"[REQ:{request_id}] LLM success "
            f"{len(content)} chars"
        )

        return content

    except asyncio.TimeoutError:

        logger.error(
            f"[REQ:{request_id}] LLM timeout"
        )

        raise HTTPException(
            504,
            "LLM timeout"
        )

    except Exception:

        logger.exception(
            f"[REQ:{request_id}] LLM error"
        )

        raise


# ============================================
# CREDIT ATOMIC DEDUCTION
# ============================================

async def deduct_credits(uid, amount, request_id):

    result = await mongo_debug(

        "deduct_credits",

        db.users.update_one(
            {
                "uid": uid,
                "credits": {"$gte": amount},
            },
            {
                "$inc": {"credits": -amount},
                "$set": {
                    "updated_at":
                        datetime.now(timezone.utc).isoformat()
                },
            },
        ),

        request_id,
    )

    if result.modified_count == 0:

        raise HTTPException(
            402,
            "Insufficient credits",
        )


async def refund_credits(uid, amount, request_id):

    await mongo_debug(

        "refund_credits",

        db.users.update_one(
            {"uid": uid},
            {"$inc": {"credits": amount}},
        ),

        request_id,
    )


# ============================================
# STREAM REPORT
# ============================================

@api_router.post("/reports/generate")
async def generate_report(
    req: dict,
    request: Request,
    user=Depends(get_current_user),
):

    request_id = request.state.request_id

    uid = user["uid"]

    repo_url = req["repo_url"]

    match = re.search(
        r"github\.com/([^/]+)/([^/]+)",
        repo_url,
    )

    if not match:

        raise HTTPException(
            400,
            "Invalid repo URL",
        )

    owner, repo = match.groups()

    async def stream():

        credits_deducted = False

        llm_task = None

        try:

            await deduct_credits(
                uid,
                2,
                request_id,
            )

            credits_deducted = True

            yield sse_event(
                "status",
                {"message": "Fetching GitHub..."},
            )

            github = await fetch_github_data(
                owner,
                repo,
                request_id,
            )

            yield sse_event(
                "status",
                {"message": "Generating report..."},
            )

            llm_task = asyncio.create_task(
                generate_report_content(
                    github,
                    request_id,
                )
            )

            while True:

                if llm_task.done():
                    break

                await asyncio.sleep(5)

                yield sse_event(
                    "ping",
                    {"message": "Still processing"},
                )

            content = await llm_task

            yield sse_event(
                "status",
                {"message": "Streaming"},
            )

            for i in range(0, len(content), 50):

                yield sse_event(
                    "content",
                    {"text": content[i:i+50]},
                )

            await mongo_debug(

                "insert_report",

                db.reports.insert_one(
                    {
                        "id": new_request_id(),
                        "repo": repo_url,
                        "content": content,
                        "generated_at":
                            datetime.now(timezone.utc).isoformat(),
                    }
                ),

                request_id,
            )

            credits_deducted = False

            yield sse_event(
                "done",
                {"message": "Complete"},
            )

        except asyncio.CancelledError:

            logger.warning(
                f"[REQ:{request_id}] client disconnected"
            )

            if llm_task:
                llm_task.cancel()

            raise

        except Exception:

            logger.exception(
                f"[REQ:{request_id}] generation failed"
            )

            yield sse_event(
                "error",
                {"message": "Failed"},
            )

        finally:

            if credits_deducted:

                await refund_credits(
                    uid,
                    2,
                    request_id,
                )

    return StreamingResponse(

        stream(),

        media_type="text/event-stream",

        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================
# ROUTER + CORS
# ============================================

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)


# ============================================
# SHUTDOWN
# ============================================

@app.on_event("shutdown")
async def shutdown():

    mongo_client.close()

    logger.info("Mongo closed")