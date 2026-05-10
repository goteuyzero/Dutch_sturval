from __future__ import annotations

from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .game_engine import GameEngine, GameError

app = FastAPI(title="Голландский штурвал")
engine = GameEngine()


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: Dict[str, Dict[str, WebSocket]] = {}

    async def connect(self, room_code: str, player_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(room_code, {})[player_id] = websocket
        engine.set_connected(room_code, player_id, True)
        await self.broadcast(room_code)

    async def disconnect(self, room_code: str, player_id: str) -> None:
        room_connections = self.connections.get(room_code)
        if room_connections and room_connections.get(player_id):
            room_connections.pop(player_id, None)
        try:
            engine.set_connected(room_code, player_id, False)
            await self.broadcast(room_code)
        except GameError:
            pass

    async def broadcast(self, room_code: str) -> None:
        room_connections = self.connections.get(room_code, {})
        dead: list[str] = []
        for player_id, websocket in list(room_connections.items()):
            try:
                await websocket.send_json(engine.player_view(room_code, player_id))
            except Exception:
                dead.append(player_id)
        for player_id in dead:
            room_connections.pop(player_id, None)
            try:
                engine.set_connected(room_code, player_id, False)
            except GameError:
                pass


manager = ConnectionManager()


class PlayerRequest(BaseModel):
    player_id: str
    name: str


class JoinRequest(BaseModel):
    player_id: str
    name: str
    room_code: str


class ReadyRequest(BaseModel):
    player_id: str
    ready: bool


class ActionRequest(BaseModel):
    player_id: str


class SetCharacterRequest(BaseModel):
    player_id: str
    target_id: Optional[str] = None
    character: str


class VoteRequest(BaseModel):
    player_id: str
    vote: str


class NotesRequest(BaseModel):
    player_id: str
    notes: str = ""


class TargetRequest(BaseModel):
    player_id: str
    target_id: str


class ForceAnswerRequest(BaseModel):
    player_id: str
    answer: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/create-room")
async def create_room(payload: PlayerRequest):
    try:
        room = engine.create_room(payload.player_id, payload.name)
        return {"ok": True, "room_code": room.code}
    except GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/join-room")
async def join_room(payload: JoinRequest):
    try:
        room = engine.join_room(payload.room_code, payload.player_id, payload.name)
        await manager.broadcast(room.code)
        return {"ok": True, "room_code": room.code}
    except GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/room/{room_code}/ready")
async def set_ready(room_code: str, payload: ReadyRequest):
    return await _do_and_broadcast(room_code, lambda: engine.set_ready(room_code, payload.player_id, payload.ready))


@app.post("/api/room/{room_code}/start")
async def start_game(room_code: str, payload: ActionRequest):
    return await _do_and_broadcast(room_code, lambda: engine.start_game(room_code, payload.player_id))


@app.post("/api/room/{room_code}/set-character")
async def set_character(room_code: str, payload: SetCharacterRequest):
    return await _do_and_broadcast(
        room_code,
        lambda: engine.set_character(room_code, payload.player_id, payload.target_id, payload.character),
    )


@app.post("/api/room/{room_code}/vote")
async def vote(room_code: str, payload: VoteRequest):
    return await _do_and_broadcast(room_code, lambda: engine.vote(room_code, payload.player_id, payload.vote))


@app.post("/api/room/{room_code}/confirm-guessed")
async def confirm_guessed(room_code: str, payload: ActionRequest):
    return await _do_and_broadcast(room_code, lambda: engine.confirm_guessed(room_code, payload.player_id))


@app.post("/api/room/{room_code}/surrender")
async def surrender(room_code: str, payload: ActionRequest):
    try:
        room, status = engine.surrender(room_code, payload.player_id)
        await manager.broadcast(room.code)
        return {"ok": True, "status": status}
    except GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/room/{room_code}/notes")
async def save_notes(room_code: str, payload: NotesRequest):
    return await _do_and_broadcast(room_code, lambda: engine.save_notes(room_code, payload.player_id, payload.notes))


@app.post("/api/room/{room_code}/new-game")
async def new_game(room_code: str, payload: ActionRequest):
    return await _do_and_broadcast(room_code, lambda: engine.new_game(room_code, payload.player_id))


@app.post("/api/room/{room_code}/admin/kick-player")
async def kick_player(room_code: str, payload: TargetRequest):
    return await _do_and_broadcast(room_code, lambda: engine.kick_player(room_code, payload.player_id, payload.target_id))


@app.post("/api/room/{room_code}/admin/remove-from-queue")
async def remove_from_queue(room_code: str, payload: TargetRequest):
    return await _do_and_broadcast(room_code, lambda: engine.remove_from_queue(room_code, payload.player_id, payload.target_id))


@app.post("/api/room/{room_code}/admin/skip-turn")
async def skip_turn(room_code: str, payload: ActionRequest):
    return await _do_and_broadcast(room_code, lambda: engine.skip_turn(room_code, payload.player_id))


@app.post("/api/room/{room_code}/admin/force-answer")
async def force_answer(room_code: str, payload: ForceAnswerRequest):
    return await _do_and_broadcast(room_code, lambda: engine.force_answer(room_code, payload.player_id, payload.answer))


@app.websocket("/ws/{room_code}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_code: str, player_id: str):
    try:
        # Проверяем, что комната и игрок существуют, до accept.
        room = engine.get_room(room_code)
        if player_id not in room.players:
            raise GameError("Игрок не найден в комнате.")
        await manager.connect(room_code, player_id, websocket)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(room_code, player_id)
    except GameError:
        await websocket.close(code=1008)


async def _do_and_broadcast(room_code: str, action):
    try:
        room = action()
        await manager.broadcast(room.code)
        return {"ok": True}
    except GameError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


app.mount("/static", StaticFiles(directory="app/static"), name="static")
