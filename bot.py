import asyncio
import html
import logging
import random

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)


from words import WORDS_DB

TOKEN = "ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН"

MIN_PLAYERS = 4
MAX_PLAYERS = 15


bot = Bot(token=TOKEN)
dp = Dispatcher()


games = {}


def get_player_name(player):
    return html.escape(player["name"])


def create_lobby_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Присоединиться",
                    callback_data="join_game",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Начать игру",
                    callback_data="start_game",
                )
            ],
        ]
    )


def create_finish_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Закончить игру",
                    callback_data="finish_game",
                )
            ]
        ]
    )


def create_next_turn_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я сказал",
                    callback_data="next_turn",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Начать голосование",
                    callback_data="start_voting",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Закончить игру",
                    callback_data="finish_game",
                )
            ],
        ]
    )


def create_vote_keyboard(players):
    buttons = []

    for user_id, player in players.items():
        buttons.append(
            [
                InlineKeyboardButton(
                    text=player["name"],
                    callback_data=f"vote:{user_id}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="Отменить игру",
                callback_data="finish_game",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def create_restart_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Новая игра",
                    callback_data="new_game",
                )
            ]
        ]
    )


def get_lobby_text(game):
    players = game["players"]

    if players:
        players_list = "\n".join(
            f"{i + 1}. {get_player_name(player)}"
            for i, player in enumerate(players.values())
        )
    else:
        players_list = "Пока никто не присоединился."

    return (
        "🕵️ <b>КТО ШПИОН?</b>\n\n"
        f"Игроки: <b>{len(players)}/{MAX_PLAYERS}</b>\n\n"
        f"{players_list}\n\n"
        f"Минимум для старта: <b>{MIN_PLAYERS}</b>"
    )


async def safe_send_role(user_id, text):
    """
    Пытаемся отправить игроку личное сообщение.
    Возвращаем True, если получилось.
    """

    try:
        await bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
        )
        return True

    except Exception as error:
        logging.warning(
            "Не удалось отправить сообщение пользователю %s: %s",
            user_id,
            error,
        )
        return False


@dp.message(Command("spy"))
async def start_lobby(message: Message):

    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Игру можно запускать только в группе.")
        return

    chat_id = message.chat.id

    if chat_id in games:
        await message.answer("В этом чате уже есть активная игра.")
        return

    games[chat_id] = {
        "creator_id": message.from_user.id,
        "players": {},
        "status": "lobby",
    }

    await message.answer(
        get_lobby_text(games[chat_id]),
        reply_markup=create_lobby_keyboard(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "join_game")
async def join_game(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] != "lobby":
        await callback.answer(
            "Игра уже началась.",
            show_alert=True,
        )
        return

    user = callback.from_user
    players = game["players"]

    if user.id in players:
        await callback.answer(
            "Ты уже в игре!",
            show_alert=True,
        )
        return

    if len(players) >= MAX_PLAYERS:
        await callback.answer(
            f"Максимум игроков: {MAX_PLAYERS}.",
            show_alert=True,
        )
        return

    players[user.id] = {
        "name": user.full_name,
        "username": user.username,
    }

    await callback.message.edit_text(
        get_lobby_text(game),
        reply_markup=create_lobby_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer("Ты присоединился к игре!")


@dp.callback_query(F.data == "start_game")
async def start_game(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] != "lobby":
        await callback.answer(
            "Игра уже запущена.",
            show_alert=True,
        )
        return

    if callback.from_user.id != game["creator_id"]:
        await callback.answer(
            "Только создатель игры может её начать.",
            show_alert=True,
        )
        return

    players = game["players"]

    if len(players) < MIN_PLAYERS:
        await callback.answer(
            f"Нужно минимум {MIN_PLAYERS} игрока.",
            show_alert=True,
        )
        return

    chosen_item = random.choice(WORDS_DB)

    secret_word = chosen_item["word"]
    spy_hint = random.choice(chosen_item["spy_hints"])

    player_ids = list(players.keys())

    spy_id = random.choice(player_ids)

    turn_order = player_ids.copy()
    random.shuffle(turn_order)

    game["status"] = "playing"
    game["secret_word"] = secret_word
    game["spy_hint"] = spy_hint
    game["spy_id"] = spy_id
    game["turn_order"] = turn_order
    game["current_index"] = 0
    game["votes"] = {}

    failed_players = []

    for user_id in player_ids:
        if user_id == spy_id:
            text = (
                "🕵️ <b>ТЫ ШПИОН!</b>\n\n"
                f"Твоя подсказка: <b>{html.escape(spy_hint)}</b>\n\n"
                "Попробуй понять, какое слово знают остальные, "
                "и не выдай себя."
            )
        else:
            text = (
                "🤫 <b>ТВОЁ СЕКРЕТНОЕ СЛОВО</b>\n\n"
                f"<b>{html.escape(secret_word)}</b>\n\n"
                "Не показывай его другим игрокам!"
            )

        success = await safe_send_role(user_id, text)

        if not success:
            failed_players.append(user_id)

    if failed_players:
        game["status"] = "lobby"
        game.pop("secret_word", None)
        game.pop("spy_hint", None)
        game.pop("spy_id", None)
        game.pop("turn_order", None)
        game.pop("current_index", None)
        game.pop("votes", None)

        failed_names = [get_player_name(players[user_id]) for user_id in failed_players]

        names = ", ".join(failed_names)

        await callback.message.edit_text(
            get_lobby_text(game) + "\n\n"
            "<b>Игра не началась.</b>\n"
            f"Этим игрокам нужно сначала открыть бота в личке:\n"
            f"{names}\n\n"
            "После этого снова нажмите «Начать игру».",
            reply_markup=create_lobby_keyboard(),
            parse_mode="HTML",
        )

        await callback.answer(
            "Не удалось отправить роли всем игрокам.",
            show_alert=True,
        )
        return

    first_player_id = turn_order[0]
    first_player = players[first_player_id]

    first_name = get_player_name(first_player)

    await callback.message.edit_text(
        "<b>ИГРА НАЧАЛАСЬ!</b>\n\n"
        "Роли отправлены всем игрокам в личные сообщения.\n\n"
        f"🗣 <b>Первым говорит:</b> {first_name}\n\n"
        "Когда игрок закончит, нажмите кнопку «Я сказал».",
        reply_markup=create_next_turn_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer()


@dp.callback_query(F.data == "next_turn")
async def next_turn(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] != "playing":
        await callback.answer(
            "Сейчас нет активной очереди.",
            show_alert=True,
        )
        return

    current_player_id = game["turn_order"][game["current_index"]]

    if callback.from_user.id != current_player_id:
        current_player = game["players"][current_player_id]

        await callback.answer(
            f"Сейчас говорит {current_player['name']}.",
            show_alert=True,
        )
        return

    game["current_index"] += 1

    if game["current_index"] >= len(game["turn_order"]):
        game["status"] = "voting"

        await callback.message.edit_text(
            "<b>ВСЕ ВЫСКАЗАЛИСЬ!</b>\n\n"
            "Теперь голосование.\n"
            "Выбери игрока, которого считаешь шпионом.",
            reply_markup=create_vote_keyboard(game["players"]),
            parse_mode="HTML",
        )

        await callback.answer("Все игроки высказались!")
        return

    next_player_id = game["turn_order"][game["current_index"]]
    next_player = game["players"][next_player_id]

    next_name = get_player_name(next_player)

    await callback.message.edit_text(
        "🗣 <b>Следующий игрок</b>\n\n"
        f"Теперь говорит: <b>{next_name}</b>\n\n"
        "После ответа нажмите «Я сказал».",
        reply_markup=create_next_turn_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer()


@dp.callback_query(F.data == "start_voting")
async def start_voting(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] != "playing":
        await callback.answer(
            "Сейчас нельзя начать голосование.",
            show_alert=True,
        )
        return

    if callback.from_user.id not in game["players"]:
        await callback.answer(
            "Ты не участвуешь в этой игре.",
            show_alert=True,
        )
        return

    game["status"] = "voting"
    game["votes"] = {}

    await callback.message.edit_text(
        "🗳 <b>ГОЛОСОВАНИЕ</b>\n\n"
        "Выберите игрока, которого считаете шпионом.\n\n"
        "Каждый игрок может проголосовать только один раз.",
        reply_markup=create_vote_keyboard(game["players"]),
        parse_mode="HTML",
    )

    await callback.answer()


@dp.callback_query(F.data.startswith("vote:"))
async def vote(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] != "voting":
        await callback.answer(
            "Сейчас голосование не проводится.",
            show_alert=True,
        )
        return

    voter_id = callback.from_user.id

    if voter_id not in game["players"]:
        await callback.answer(
            "Ты не участник игры.",
            show_alert=True,
        )
        return

    if voter_id in game["votes"]:
        await callback.answer(
            "Ты уже проголосовал.",
            show_alert=True,
        )
        return

    try:
        target_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer(
            "Некорректный голос.",
            show_alert=True,
        )
        return

    if target_id not in game["players"]:
        await callback.answer(
            "Такого игрока нет.",
            show_alert=True,
        )
        return

    if target_id == voter_id:
        await callback.answer(
            "Нельзя голосовать за себя.",
            show_alert=True,
        )
        return

    game["votes"][voter_id] = target_id

    total_players = len(game["players"])
    total_votes = len(game["votes"])

    if total_votes < total_players:
        await callback.answer(f"Голос принят: {total_votes}/{total_players}")

        await callback.message.edit_text(
            "🗳 <b>ГОЛОСОВАНИЕ</b>\n\n"
            f"Проголосовало: <b>{total_votes}/{total_players}</b>\n\n"
            "Если ты уже проголосовал — жди остальных.",
            reply_markup=create_vote_keyboard(game["players"]),
            parse_mode="HTML",
        )

        return

    vote_counts = {}

    for target_id in game["votes"].values():
        vote_counts[target_id] = vote_counts.get(target_id, 0) + 1

    max_votes = max(vote_counts.values())

    candidates = [
        user_id for user_id, count in vote_counts.items() if count == max_votes
    ]

    if len(candidates) > 1:
        names = []

        for user_id in candidates:
            names.append(f"• {get_player_name(game['players'][user_id])}")

        game["status"] = "finished"

        await callback.message.edit_text(
            "⚖️ <b>НИЧЬЯ!</b>\n\n"
            f"Одинаковое количество голосов получили:\n"
            f"{chr(10).join(names)}\n\n"
            f"🕵️ Настоящим шпионом был: "
            f"<b>{get_player_name(game['players'][game['spy_id']])}</b>\n\n"
            f"🤫 Слово: <b>{html.escape(game['secret_word'])}</b>\n\n"
            "Шпион победил из-за ничьей.",
            reply_markup=create_restart_keyboard(),
            parse_mode="HTML",
        )

        await callback.answer()
        return

    voted_out_id = candidates[0]

    spy_id = game["spy_id"]

    voted_out_name = get_player_name(game["players"][voted_out_id])

    spy_name = get_player_name(game["players"][spy_id])

    secret_word = html.escape(game["secret_word"])

    if voted_out_id == spy_id:
        result = (
            "🎉 <b>МИРНЫЕ ПОБЕДИЛИ!</b>\n\n"
            f"Игроки вычислили шпиона: <b>{voted_out_name}</b>\n\n"
            f"🕵️ Шпион: <b>{spy_name}</b>\n"
            f"🤫 Слово: <b>{secret_word}</b>"
        )

    else:
        result = (
            "🕵️ <b>ШПИОН ПОБЕДИЛ!</b>\n\n"
            f"Игроки выбрали: <b>{voted_out_name}</b>\n\n"
            f"Но настоящий шпион был: <b>{spy_name}</b>\n"
            f"🤫 Слово: <b>{secret_word}</b>"
        )

    game["status"] = "finished"

    await callback.message.edit_text(
        result,
        reply_markup=create_restart_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer("Голосование завершено!")


@dp.callback_query(F.data == "finish_game")
async def finish_game(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    if chat_id not in games:
        await callback.answer(
            "Игра не найдена.",
            show_alert=True,
        )
        return

    game = games[chat_id]

    if game["status"] == "lobby":
        await callback.answer(
            "Игра ещё не началась.",
            show_alert=True,
        )
        return

    spy_id = game["spy_id"]

    spy_name = get_player_name(
        game["players"].get(spy_id, {"name": "Неизвестный игрок"})
    )

    secret_word = html.escape(game["secret_word"])

    game["status"] = "finished"

    await callback.message.edit_text(
        "🛑 <b>ИГРА ЗАВЕРШЕНА</b>\n\n"
        f"🤫 Секретное слово: <b>{secret_word}</b>\n"
        f"🕵️ Шпион: <b>{spy_name}</b>",
        reply_markup=create_restart_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer("Игра завершена.")


@dp.callback_query(F.data == "new_game")
async def new_game(callback: CallbackQuery):

    if not callback.message:
        await callback.answer()
        return

    chat_id = callback.message.chat.id

    games.pop(chat_id, None)

    games[chat_id] = {
        "creator_id": callback.from_user.id,
        "players": {},
        "status": "lobby",
    }

    await callback.message.edit_text(
        get_lobby_text(games[chat_id]),
        reply_markup=create_lobby_keyboard(),
        parse_mode="HTML",
    )

    await callback.answer("Новая игра создана!")


async def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    logging.info("Бот запускается...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
