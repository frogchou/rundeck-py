import asyncio
import hashlib
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .executor import ValidationError, build_command, run_task
from .task_manager import TaskStatus, task_manager


templates = Jinja2Templates(directory="templates")
app = FastAPI(title="RunDeck-Py")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _auth_token(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def require_auth(request: Request, settings=Depends(get_settings)):
    token = request.cookies.get("auth_token")
    if token != _auth_token(settings.access_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, settings=Depends(get_settings)):
    try:
        require_auth(request, settings)
    except HTTPException:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_script": settings.default_script,
            "allow_arbitrary": settings.allow_arbitrary_command,
            "allowed_root": settings.allowed_script_root,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, settings=Depends(get_settings)):
    try:
        require_auth(request, settings)
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    except HTTPException:
        return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
async def login(request: Request, password: str = Form(...), settings=Depends(get_settings)):
    if password != settings.access_password:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "密码错误"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("auth_token", _auth_token(settings.access_password), httponly=True, samesite="lax")
    return response


@app.post("/api/run")
async def api_run(payload: dict[str, str], auth=Depends(require_auth)):
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
async def stream(task_id: str, auth=Depends(require_auth)):
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
async def stop(task_id: str, auth=Depends(require_auth)):
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
