from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class GameError(Exception):
    """Ошибка игровой логики, которую можно показать пользователю."""


@dataclass
class Player:
    id: str
    name: str
    is_host: bool = False
    ready: bool = False
    connected: bool = False
    total_score: int = 0
    character: str = ""
    character_set_by: Optional[str] = None
    target_id: Optional[str] = None
    giver_id: Optional[str] = None
    notes: str = ""
    guessed: bool = False
    surrendered: bool = False
    queue_removed: bool = False
    surrender_requested_at: Optional[float] = None
    joined_at: float = field(default_factory=time.time)


@dataclass
class Room:
    code: str
    host_id: str
    players: Dict[str, Player] = field(default_factory=dict)
    phase: str = "lobby"  # lobby | assigning | playing | game_over
    game_number: int = 0
    turn_order: List[str] = field(default_factory=list)
    active_player_id: Optional[str] = None
    active_index: int = 0
    votes: Dict[str, str] = field(default_factory=dict)  # player_id -> yes/no/unknown
    guessed_order: List[str] = field(default_factory=list)
    resolved_order: List[str] = field(default_factory=list)
    round_scores: Dict[str, int] = field(default_factory=dict)
    round_awarded: bool = False
    last_answer: Optional[str] = None
    last_event: str = ""
    created_at: float = field(default_factory=time.time)


class GameEngine:
    def __init__(self) -> None:
        self.rooms: Dict[str, Room] = {}

    # ---------- Room and player management ----------

    def create_room(self, player_id: str, name: str) -> Room:
        player_id = self._require_text(player_id, "Не найден ID игрока")
        name = self._normalize_name(name)
        code = self._generate_room_code()
        room = Room(code=code, host_id=player_id)
        room.players[player_id] = Player(
            id=player_id,
            name=name,
            is_host=True,
        )
        room.last_event = f"{name} создал комнату."
        self.rooms[code] = room
        return room

    def join_room(self, code: str, player_id: str, name: str) -> Room:
        room = self.get_room(code)
        player_id = self._require_text(player_id, "Не найден ID игрока")
        name = self._normalize_name(name)

        if player_id in room.players:
            player = room.players[player_id]
            player.name = name
            room.last_event = f"{name} вернулся в комнату."
            return room

        if room.phase != "lobby":
            # Игрок может подключиться во время партии, но он не должен ломать текущую очередь
            # и не должен становиться обязательным голосующим в текущем раунде.
            room.players[player_id] = Player(id=player_id, name=name, ready=True, queue_removed=True)
            room.last_event = f"{name} подключился как зритель текущей партии."
            return room

        room.players[player_id] = Player(id=player_id, name=name)
        room.last_event = f"{name} подключился к комнате."
        return room

    def set_connected(self, code: str, player_id: str, connected: bool) -> None:
        room = self.get_room(code)
        player = room.players.get(player_id)
        if player:
            player.connected = connected

    def set_ready(self, code: str, player_id: str, ready: bool) -> Room:
        room = self.get_room(code)
        player = self._get_player(room, player_id)
        if room.phase != "lobby":
            raise GameError("Ready можно менять только в лобби.")
        player.ready = bool(ready)
        room.last_event = f"{player.name} {'готов' if player.ready else 'не готов'}."
        return room

    def start_game(self, code: str, player_id: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, player_id)
        if room.phase != "lobby":
            raise GameError("Игру можно начать только из лобби.")
        if not room.players:
            raise GameError("В комнате нет игроков.")
        if not all(player.ready for player in room.players.values()):
            raise GameError("Не все игроки нажали ready.")
        self._setup_new_round(room)
        room.last_event = "Игра началась. Игроки загадывают персонажей."
        return room

    def new_game(self, code: str, player_id: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, player_id)
        if room.phase != "game_over":
            raise GameError("Новую игру можно начать только после завершения текущей.")
        self._setup_new_round(room)
        room.last_event = "Началась новая игра. Очки сохранены."
        return room

    # ---------- Character assignment ----------

    def set_character(self, code: str, player_id: str, target_id: Optional[str], character: str) -> Room:
        room = self.get_room(code)
        player = self._get_player(room, player_id)
        if room.phase != "assigning":
            raise GameError("Персонажей можно задавать только перед началом раунда.")
        if player.id not in room.turn_order:
            raise GameError("Ты не участвуешь в текущей очереди.")
        if not player.target_id:
            raise GameError("Для тебя не назначен игрок, которому нужно загадать персонажа.")
        if target_id and target_id != player.target_id:
            raise GameError("Ты пытаешься задать персонажа не своему игроку.")
        target = self._get_player(room, player.target_id)
        character = self._require_text(character, "Введи имя персонажа")
        if len(character) > 80:
            raise GameError("Имя персонажа слишком длинное. Максимум 80 символов.")
        target.character = character
        target.character_set_by = player.id
        room.last_event = f"{player.name} задал персонажа для {target.name}."

        if self._all_characters_ready(room):
            room.phase = "playing"
            first_active = self._first_active_player(room)
            room.active_player_id = first_active
            room.active_index = room.turn_order.index(first_active) if first_active else 0
            room.votes.clear()
            room.last_answer = None
            room.last_event = "Все персонажи заданы. Первый ход начался."
        return room

    # ---------- Gameplay ----------

    def vote(self, code: str, player_id: str, vote: str) -> Room:
        room = self.get_room(code)
        player = self._get_player(room, player_id)
        if room.phase != "playing":
            raise GameError("Сейчас нельзя голосовать.")
        if not room.active_player_id:
            raise GameError("Сейчас нет активного игрока.")
        if player.id == room.active_player_id:
            raise GameError("Активный игрок не голосует.")
        vote = self._normalize_vote(vote)

        eligible = self._eligible_voters(room)
        if player.id not in eligible:
            raise GameError("Ты сейчас не можешь голосовать.")
        if player.id in room.votes:
            raise GameError("Ты уже проголосовал в этом вопросе.")

        room.votes[player.id] = vote
        room.last_event = f"{player.name} проголосовал."

        if len(room.votes) >= len(eligible) and eligible:
            no_count = sum(1 for v in room.votes.values() if v == "no")
            if no_count * 2 >= len(eligible):
                room.last_answer = "no"
                active = self._get_player(room, room.active_player_id)
                room.last_event = f"Ответ: нет. Ход переходит дальше после вопроса {active.name}."
                self._next_turn(room)
            else:
                room.last_answer = self._dominant_non_no_answer(room)
                active = self._get_player(room, room.active_player_id)
                room.votes.clear()
                room.last_event = f"Ответ не был \"нет\". {active.name} продолжает задавать вопросы."
        return room

    def confirm_guessed(self, code: str, player_id: str) -> Room:
        room = self.get_room(code)
        actor = self._get_player(room, player_id)
        if room.phase != "playing":
            raise GameError("Сейчас нельзя отмечать угадывание.")
        if not room.active_player_id:
            raise GameError("Сейчас нет активного игрока.")
        active = self._get_player(room, room.active_player_id)
        can_confirm = actor.is_host or (active.giver_id == actor.id and actor.id != active.id)
        if not can_confirm:
            raise GameError("Кнопка \"Угадал\" доступна только хосту и тому, кто загадывал персонажа активному игроку.")
        if not self._is_in_rotation(active):
            raise GameError("Этот игрок уже не находится в очереди.")

        active.guessed = True
        active.surrender_requested_at = None
        if active.id not in room.guessed_order:
            room.guessed_order.append(active.id)
        if active.id not in room.resolved_order:
            room.resolved_order.append(active.id)
        room.last_answer = "guessed"
        room.last_event = f"{active.name} угадал персонажа."
        self._next_turn(room)
        return room

    def surrender(self, code: str, player_id: str) -> Tuple[Room, str]:
        room = self.get_room(code)
        player = self._get_player(room, player_id)
        if room.phase != "playing":
            raise GameError("Сдаться можно только во время игры.")
        if not self._is_in_rotation(player):
            raise GameError("Ты уже не находишься в очереди вопросов.")

        now = time.time()
        if player.surrender_requested_at is None or now - player.surrender_requested_at > 30:
            player.surrender_requested_at = now
            room.last_event = f"{player.name} хочет сдаться. Нужно подтверждение через 3 секунды."
            return room, "pending"

        elapsed = now - player.surrender_requested_at
        if elapsed < 3:
            raise GameError(f"Подтверждение сдачи будет доступно через {max(1, int(3 - elapsed + 0.99))} сек.")

        player.surrendered = True
        player.surrender_requested_at = None
        if player.id not in room.resolved_order:
            room.resolved_order.append(player.id)
        room.last_answer = "surrender"
        room.last_event = f"{player.name} сдался. Персонаж раскрыт."
        if room.active_player_id == player.id:
            self._next_turn(room)
        elif not self._any_active_players(room):
            self._finish_game(room)
        return room, "surrendered"

    def save_notes(self, code: str, player_id: str, notes: str) -> Room:
        room = self.get_room(code)
        player = self._get_player(room, player_id)
        player.notes = (notes or "")[:5000]
        return room

    # ---------- Host actions ----------

    def kick_player(self, code: str, actor_id: str, target_id: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, actor_id)
        target = self._get_player(room, target_id)
        if target.id == room.host_id:
            raise GameError("Хоста нельзя кикнуть из собственной комнаты.")

        was_active = room.active_player_id == target.id
        old_index = room.active_index
        target_name = target.name

        del room.players[target.id]
        room.turn_order = [pid for pid in room.turn_order if pid != target.id]
        room.guessed_order = [pid for pid in room.guessed_order if pid != target.id]
        room.resolved_order = [pid for pid in room.resolved_order if pid != target.id]
        room.round_scores.pop(target.id, None)
        room.votes.pop(target.id, None)

        for player in room.players.values():
            if player.target_id == target.id or player.giver_id == target.id:
                player.target_id = None if player.target_id == target.id else player.target_id
                player.giver_id = None if player.giver_id == target.id else player.giver_id
                if room.phase == "assigning":
                    player.character = ""
                    player.character_set_by = None

        if room.phase == "assigning":
            self._setup_assignments(room, preserve_game_number=True)
            room.last_event = f"{target_name} удален из игры. Назначения персонажей пересобраны."
            return room

        if room.phase == "playing":
            if not room.turn_order:
                self._finish_game(room)
            elif was_active:
                room.active_index = old_index - 1 if old_index < len(room.turn_order) else -1
                self._next_turn(room)
            elif not self._any_active_players(room):
                self._finish_game(room)

        room.last_event = f"{target_name} удален из игры."
        return room

    def remove_from_queue(self, code: str, actor_id: str, target_id: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, actor_id)
        target = self._get_player(room, target_id)
        if room.phase != "playing":
            raise GameError("Убрать игрока из очереди можно только во время игры.")
        if target.id not in room.turn_order:
            raise GameError("Этот игрок не участвует в текущей очереди.")
        if not self._is_in_rotation(target) and room.phase == "playing":
            raise GameError("Этот игрок уже не находится в очереди.")

        target.queue_removed = True
        target.surrender_requested_at = None
        if target.id not in room.resolved_order:
            room.resolved_order.append(target.id)
        room.votes.pop(target.id, None)
        room.last_event = f"{target.name} убран из очереди хостом."

        if room.active_player_id == target.id:
            self._next_turn(room)
        elif not self._any_active_players(room):
            self._finish_game(room)
        return room

    def skip_turn(self, code: str, actor_id: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, actor_id)
        if room.phase != "playing":
            raise GameError("Скипнуть ход можно только во время игры.")
        if not room.active_player_id:
            raise GameError("Сейчас нет активного игрока.")
        active_name = room.players.get(room.active_player_id).name if room.active_player_id in room.players else "игрока"
        room.last_answer = "skip"
        room.last_event = f"Хост передал ход после игрока {active_name}."
        self._next_turn(room)
        return room

    def force_answer(self, code: str, actor_id: str, answer: str) -> Room:
        room = self.get_room(code)
        self._require_host(room, actor_id)
        if room.phase != "playing":
            raise GameError("Принудительный ответ можно поставить только во время игры.")
        answer = self._normalize_vote(answer)
        active_name = room.players.get(room.active_player_id).name if room.active_player_id in room.players else "игрок"
        room.last_answer = answer
        if answer == "no":
            room.last_event = f"Хост принудительно поставил ответ \"нет\". Ход {active_name} завершен."
            self._next_turn(room)
        else:
            room.votes.clear()
            room.last_event = f"Хост принудительно поставил ответ \"{self._vote_label(answer)}\". {active_name} продолжает ход."
        return room

    # ---------- Views ----------

    def player_view(self, code: str, viewer_id: str) -> Dict[str, Any]:
        room = self.get_room(code)
        viewer = room.players.get(viewer_id)
        ordered_ids = self._ordered_player_ids(room)
        players_view = [self._player_public_view(room, pid, viewer_id) for pid in ordered_ids if pid in room.players]
        active = room.players.get(room.active_player_id) if room.active_player_id else None
        eligible_voters = self._eligible_voters(room) if room.phase == "playing" else []
        votes_summary = self._votes_summary(room, eligible_voters)

        me = None
        if viewer:
            target = room.players.get(viewer.target_id) if viewer.target_id else None
            giver = room.players.get(viewer.giver_id) if viewer.giver_id else None
            me = {
                "id": viewer.id,
                "name": viewer.name,
                "is_host": viewer.is_host,
                "ready": viewer.ready,
                "connected": viewer.connected,
                "total_score": viewer.total_score,
                "notes": viewer.notes,
                "target_id": viewer.target_id,
                "target_name": target.name if target else None,
                "giver_id": viewer.giver_id,
                "giver_name": giver.name if giver else None,
                "guessed": viewer.guessed,
                "surrendered": viewer.surrendered,
                "queue_removed": viewer.queue_removed,
                "in_rotation": self._is_in_rotation(viewer),
                "surrender_pending": viewer.surrender_requested_at is not None,
                "surrender_seconds_left": self._surrender_seconds_left(viewer),
            }

        active_character_visible = False
        active_character = None
        if active:
            active_character_visible = self._can_view_character(active, viewer_id, room)
            active_character = active.character if active_character_visible else None

        can_vote = bool(
            viewer
            and room.phase == "playing"
            and room.active_player_id
            and viewer.id in eligible_voters
            and viewer.id not in room.votes
        )
        can_confirm_guessed = bool(
            viewer
            and active
            and room.phase == "playing"
            and self._is_in_rotation(active)
            and (viewer.is_host or (active.giver_id == viewer.id and active.id != viewer.id))
        )
        can_surrender = bool(viewer and room.phase == "playing" and self._is_in_rotation(viewer))

        return {
            "room_code": room.code,
            "phase": room.phase,
            "game_number": room.game_number,
            "host_id": room.host_id,
            "me": me,
            "players": players_view,
            "turn_order": room.turn_order,
            "active_player_id": room.active_player_id,
            "active_player_name": active.name if active else None,
            "active_character": active_character,
            "active_character_visible": active_character_visible,
            "votes": votes_summary,
            "my_vote": room.votes.get(viewer_id),
            "can_vote": can_vote,
            "can_confirm_guessed": can_confirm_guessed,
            "can_surrender": can_surrender,
            "can_start": bool(viewer and viewer.is_host and room.phase == "lobby" and room.players and all(p.ready for p in room.players.values())),
            "all_ready": bool(room.players and all(p.ready for p in room.players.values())),
            "all_characters_set": self._all_characters_ready(room) if room.phase == "assigning" else False,
            "guessed_order": room.guessed_order,
            "resolved_order": room.resolved_order,
            "round_scores": room.round_scores,
            "round_awarded": room.round_awarded,
            "last_answer": room.last_answer,
            "last_event": room.last_event,
            "server_time": time.time(),
        }

    # ---------- Internal helpers ----------

    def get_room(self, code: str) -> Room:
        code = (code or "").strip().upper()
        if code not in self.rooms:
            raise GameError("Комната не найдена.")
        return self.rooms[code]

    def _setup_new_round(self, room: Room) -> None:
        room.game_number += 1
        room.phase = "assigning"
        room.votes.clear()
        room.guessed_order.clear()
        room.resolved_order.clear()
        room.round_scores.clear()
        room.round_awarded = False
        room.last_answer = None
        room.active_player_id = None
        room.active_index = 0

        for player in room.players.values():
            player.character = ""
            player.character_set_by = None
            player.target_id = None
            player.giver_id = None
            player.notes = ""
            player.guessed = False
            player.surrendered = False
            player.queue_removed = False
            player.surrender_requested_at = None
            player.ready = True

        self._setup_assignments(room, preserve_game_number=True)

    def _setup_assignments(self, room: Room, preserve_game_number: bool = True) -> None:
        active_ids = list(room.players.keys())
        random.shuffle(active_ids)
        room.turn_order = active_ids
        room.active_player_id = None
        room.active_index = 0
        room.votes.clear()
        room.last_answer = None

        for player in room.players.values():
            player.target_id = None
            player.giver_id = None
            player.character = ""
            player.character_set_by = None
            player.guessed = False
            player.surrendered = False
            player.queue_removed = False
            player.surrender_requested_at = None

        if not active_ids:
            room.phase = "game_over"
            return

        for index, player_id in enumerate(active_ids):
            target_id = active_ids[(index + 1) % len(active_ids)]
            giver_id = active_ids[(index - 1) % len(active_ids)]
            room.players[player_id].target_id = target_id
            room.players[player_id].giver_id = giver_id

    def _all_characters_ready(self, room: Room) -> bool:
        participating = [room.players[pid] for pid in room.turn_order if pid in room.players and not room.players[pid].queue_removed]
        if not participating:
            return False
        return all(bool(player.character.strip()) for player in participating)

    def _first_active_player(self, room: Room) -> Optional[str]:
        for pid in room.turn_order:
            player = room.players.get(pid)
            if player and self._is_in_rotation(player):
                return pid
        return None

    def _next_turn(self, room: Room) -> None:
        room.votes.clear()
        if not room.turn_order or not self._any_active_players(room):
            self._finish_game(room)
            return

        if room.active_player_id in room.turn_order:
            start_index = room.turn_order.index(room.active_player_id)
        else:
            start_index = room.active_index

        count = len(room.turn_order)
        for offset in range(1, count + 1):
            idx = (start_index + offset) % count
            pid = room.turn_order[idx]
            player = room.players.get(pid)
            if player and self._is_in_rotation(player):
                room.active_player_id = pid
                room.active_index = idx
                return

        self._finish_game(room)

    def _finish_game(self, room: Room) -> None:
        if room.phase == "game_over":
            return
        room.phase = "game_over"
        room.active_player_id = None
        room.votes.clear()
        if not room.round_awarded:
            self._award_round_scores(room)
        room.last_event = "Игра завершена. Можно начать новую игру."

    def _award_round_scores(self, room: Room) -> None:
        score_table = [10, 8, 6, 4, 2]
        last_resolved_id = room.resolved_order[-1] if room.resolved_order else None
        room.round_scores = {pid: 0 for pid in room.players}
        scoring_candidates = [pid for pid in room.guessed_order if pid in room.players and pid != last_resolved_id]
        for index, pid in enumerate(scoring_candidates):
            points = score_table[index] if index < len(score_table) else 0
            room.round_scores[pid] = points
            room.players[pid].total_score += points
        room.round_awarded = True

    def _any_active_players(self, room: Room) -> bool:
        return any(self._is_in_rotation(player) for player in room.players.values())

    def _is_in_rotation(self, player: Player) -> bool:
        return not player.guessed and not player.surrendered and not player.queue_removed

    def _eligible_voters(self, room: Room) -> List[str]:
        if not room.active_player_id:
            return []
        voters: List[str] = []
        for pid, player in room.players.items():
            if pid == room.active_player_id:
                continue
            if pid not in room.turn_order:
                continue
            # Уже угадавшие/сдавшиеся/убранные из очереди продолжают голосовать. Отключенных не ждем.
            if player.connected:
                voters.append(pid)
        return voters

    def _votes_summary(self, room: Room, eligible_voters: List[str]) -> Dict[str, Any]:
        yes = sum(1 for v in room.votes.values() if v == "yes")
        no = sum(1 for v in room.votes.values() if v == "no")
        unknown = sum(1 for v in room.votes.values() if v == "unknown")
        eligible_count = len(eligible_voters)
        return {
            "yes": yes,
            "no": no,
            "unknown": unknown,
            "total": len(room.votes),
            "eligible": eligible_count,
            "remaining": max(0, eligible_count - len(room.votes)),
            "no_needed_to_end_turn": (eligible_count + 1) // 2 if eligible_count else 0,
            "voters": list(room.votes.keys()),
        }

    def _dominant_non_no_answer(self, room: Room) -> str:
        yes = sum(1 for v in room.votes.values() if v == "yes")
        unknown = sum(1 for v in room.votes.values() if v == "unknown")
        return "yes" if yes >= unknown else "unknown"

    def _ordered_player_ids(self, room: Room) -> List[str]:
        ids: List[str] = []
        for pid in room.turn_order:
            if pid in room.players and pid not in ids:
                ids.append(pid)
        for pid, player in sorted(room.players.items(), key=lambda item: item[1].joined_at):
            if pid not in ids:
                ids.append(pid)
        return ids

    def _player_public_view(self, room: Room, player_id: str, viewer_id: str) -> Dict[str, Any]:
        player = room.players[player_id]
        target = room.players.get(player.target_id) if player.target_id else None
        giver = room.players.get(player.giver_id) if player.giver_id else None
        can_view_character = self._can_view_character(player, viewer_id, room)
        return {
            "id": player.id,
            "name": player.name,
            "is_host": player.is_host,
            "ready": player.ready,
            "connected": player.connected,
            "total_score": player.total_score,
            "character": player.character if can_view_character else None,
            "character_visible": can_view_character,
            "character_set": bool(player.character.strip()),
            "character_set_by": player.character_set_by,
            "target_id": player.target_id,
            "target_name": target.name if target else None,
            "giver_id": player.giver_id,
            "giver_name": giver.name if giver else None,
            "guessed": player.guessed,
            "surrendered": player.surrendered,
            "queue_removed": player.queue_removed,
            "in_rotation": self._is_in_rotation(player),
            "is_active": player.id == room.active_player_id,
            "turn_index": room.turn_order.index(player.id) if player.id in room.turn_order else None,
            "round_score": room.round_scores.get(player.id, 0),
        }

    def _can_view_character(self, player: Player, viewer_id: str, room: Room) -> bool:
        if not player.character:
            return False
        if room.phase == "game_over":
            return True
        if player.id != viewer_id:
            return True
        return player.guessed or player.surrendered or player.queue_removed

    def _surrender_seconds_left(self, player: Player) -> int:
        if player.surrender_requested_at is None:
            return 0
        return max(0, int(3 - (time.time() - player.surrender_requested_at) + 0.99))

    def _generate_room_code(self) -> str:
        for _ in range(200):
            code = "".join(random.choice(string.digits) for _ in range(4))
            if code not in self.rooms:
                return code
        raise GameError("Не удалось создать код комнаты. Попробуй еще раз.")

    def _get_player(self, room: Room, player_id: str) -> Player:
        player_id = self._require_text(player_id, "Не найден ID игрока")
        if player_id not in room.players:
            raise GameError("Игрок не найден в комнате.")
        return room.players[player_id]

    def _require_host(self, room: Room, player_id: str) -> Player:
        player = self._get_player(room, player_id)
        if not player.is_host or room.host_id != player.id:
            raise GameError("Это действие доступно только хосту.")
        return player

    def _normalize_vote(self, vote: str) -> str:
        vote = (vote or "").strip().lower()
        aliases = {
            "да": "yes",
            "yes": "yes",
            "y": "yes",
            "нет": "no",
            "no": "no",
            "n": "no",
            "не знаю": "unknown",
            "незнаю": "unknown",
            "unknown": "unknown",
            "idk": "unknown",
        }
        if vote not in aliases:
            raise GameError("Неизвестный вариант ответа.")
        return aliases[vote]

    def _vote_label(self, vote: str) -> str:
        return {"yes": "да", "no": "нет", "unknown": "не знаю"}.get(vote, vote)

    def _normalize_name(self, name: str) -> str:
        name = self._require_text(name, "Введи имя")
        return name[:40]

    def _require_text(self, value: Optional[str], message: str) -> str:
        value = (value or "").strip()
        if not value:
            raise GameError(message)
        return value
