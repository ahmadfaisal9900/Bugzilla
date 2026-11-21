"""Schema-only Phase 0 HTTP app. Stream A implements the routes later."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from bugzilla_serving.contracts.api_models import (
    AskResponse, ChatRequest, ErrorResponse, FeedbackRequest, FeedbackResponse,
    OptionsResponse, Preset, QuotaResponse, StatusResponse,
)


def create_app() -> FastAPI:
    app = FastAPI(title="Bugzilla QA", version="1.0.0")
    errors = {501: {"model": ErrorResponse}}

    @app.get("/v1/health", response_model=StatusResponse)
    def health():
        return StatusResponse(status="ok")

    def unavailable():
        return JSONResponse(status_code=501, content={"code": "internal", "message": "Phase 0 stub"})

    app.add_api_route("/v1/ready", unavailable, methods=["GET"],
                      response_model=StatusResponse, responses=errors)
    app.add_api_route("/v1/options", unavailable, methods=["GET"],
                      response_model=OptionsResponse, responses=errors)
    app.add_api_route("/v1/presets", unavailable, methods=["GET"],
                      response_model=list[Preset], responses=errors)
    app.add_api_route("/v1/examples", unavailable, methods=["GET"],
                      response_model=list[str], responses=errors)
    app.add_api_route("/v1/quota", unavailable, methods=["GET"],
                      response_model=QuotaResponse, responses=errors)

    @app.post("/v1/ask", response_model=AskResponse, responses=errors)
    def ask(body: ChatRequest):
        return unavailable()

    @app.post("/v1/chat/stream", responses={
        **errors, 200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}},
    })
    def stream(body: ChatRequest):
        return unavailable()

    @app.post("/v1/feedback", response_model=FeedbackResponse, responses=errors)
    def feedback(body: FeedbackRequest):
        return unavailable()

    return app


app = create_app()
