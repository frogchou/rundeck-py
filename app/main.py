import asyncio
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .executor import ValidationError, build_command, run_task
from .task_manager import TaskStatus, task_manager


templates = Jinja2Templates(directory="templates")
app = FastAPI(title="RunDeck-Py")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_script": settings.default_script,
            "allow_arbitrary": settings.allow_arbitrary_command,
            "allowed_root": settings.allowed_script_root,
        },
    )


@app.post("/api/run")
async def api_run(payload: dict[str, str]):
    mode = payload.get("mode")
    value = payload.get("value", "")
    try:
        build_command(mode, value)
    except ValidationError as exc:
        return JSONResponse({"success": False, "error": exc.detail}, status_code=exc.status_code)
    except HTTPException as exc:
        return JSONResponse(
            {"success": False, "error": {"code": "invalid", "message": str(exc.detail)}},
            status_code=exc.status_code,
        )

    try:
        task = await run_task(mode, value)
    except RuntimeError as exc:
        return JSONResponse(
            {"success": False, "error": {"code": "busy", "message": str(exc)}},
            status_code=status.HTTP_409_CONFLICT,
        )
    except ValidationError as exc:
        return JSONResponse({"success": False, "error": exc.detail}, status_code=exc.status_code)

    return {"success": True, "task_id": task.task_id}


@app.get("/api/stream/{task_id}")
async def stream(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_generator():
        # Send existing buffered output first
        for chunk in list(task.output_buffer):
            yield f"data: {chunk}\n\n"
        queue = task.subscribe()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {item}\n\n"
                except asyncio.TimeoutError:
                    # Keep connection alive
                    if task.status != TaskStatus.RUNNING:
                        break
                    continue
        finally:
            task.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/stop/{task_id}")
async def stop(task_id: str):
    task = task_manager.get_task(task_id)
    if not task:
        return JSONResponse(
            {"success": False, "error": {"code": "not_found", "message": "Task not found"}},
            status_code=404,
        )
    await task_manager.stop_task(task_id)
    return {"success": True}


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    return JSONResponse({"success": False, "error": exc.detail}, status_code=exc.status_code)
